import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd


def _default_paths() -> tuple[Path, Path, Path]:
    """Resolve model/meta/log paths for both MonetaBot-Pro and maria-helena layouts."""
    here = Path(__file__).resolve().parent
    cand_model = here / "models" / "xauusd_model.onnx"
    cand_meta = here / "models" / "xauusd_catboost_v2_meta.json"
    if cand_model.exists() and cand_meta.exists():
        log = Path(os.getenv("EXECUTOR_LOG_PATH", str(here / "logs" / "demo_monitor.jsonl")))
        return cand_model, cand_meta, log
    return (
        Path(os.getenv("MODEL_PATH", "/root/MonetaBot-Pro/ai/models/xauusd_model.onnx")),
        Path(os.getenv("META_PATH", "/root/MonetaBot-Pro/ai/models/xauusd_catboost_v2_meta.json")),
        Path(os.getenv("EXECUTOR_LOG_PATH", "/root/maria-helena/logs/demo_monitor.jsonl")),
    )


MODEL_PATH, META_PATH, LOG_PATH = _default_paths()
THRESHOLD = float(os.getenv("ONNX_SIGNAL_THRESHOLD", "0.65"))

_stop = False


def _handle_stop(signum: int, frame) -> None:  # noqa: ARG001
    global _stop
    _stop = True


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["rsi_14"] = 100 - 100 / (1 + rs)
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["ret_1h"] = c.pct_change(1)
    df["ret_24h"] = c.pct_change(24)
    df["volatility_24h"] = df["ret_1h"].rolling(24).std()
    df["ma_50"] = c.rolling(50).mean()
    df["ma_200"] = c.rolling(200).mean()
    return df


def fetch_candles_yfinance(limit: int = 300) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download("GC=F", period="60d", interval="1h", progress=False, auto_adjust=False)
    if data.empty:
        raise RuntimeError("No Yahoo candles returned.")
    data = data.reset_index().rename(
        columns={"Datetime": "time", "Open": "open", "High": "high", "Low": "low", "Close": "close"}
    )
    return data[["time", "open", "high", "low", "close"]].tail(limit).reset_index(drop=True)


def to_jsonl(payload: dict, log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def run_loop(iterations: int, sleep_s: float, log_path: Path, model_path: Path, meta_path: Path) -> list[float]:
    if not model_path.exists():
        raise FileNotFoundError(f"ONNX model not found at {model_path}")
    if not meta_path.exists():
        raise FileNotFoundError(
            f"Metadata JSON not found at {meta_path}. Copy xauusd_catboost_v2_meta.json next to the model."
        )

    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    model_features = json.loads(meta_path.read_text(encoding="utf-8")).get("features", [])

    probs: list[float] = []
    consecutive_errors = 0
    i = 0
    while not _stop:
        i += 1
        if iterations > 0 and i > iterations:
            break
        try:
            candles = fetch_candles_yfinance()
            candles["time"] = pd.to_datetime(candles["time"], utc=True, errors="coerce")
            candles = compute_features(candles).dropna().reset_index(drop=True)
            for col in model_features:
                if col not in candles.columns:
                    candles[col] = 0.0
            row = candles.iloc[-1]
            x = row[model_features].astype(np.float32).to_numpy().reshape(1, -1)
            pred_label, pred_probs = sess.run(None, {in_name: x})
            prob = float(pred_probs[0].get(1, pred_probs[0].get("1", 0.0)))
            signal = prob > THRESHOLD
            probs.append(prob)
            consecutive_errors = 0
            to_jsonl(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "iter": i,
                    "probability": prob,
                    "signal": bool(signal),
                    "threshold": THRESHOLD,
                },
                log_path,
            )
            if signal:
                to_jsonl(
                    {"ts": datetime.now(timezone.utc).isoformat(), "event": "order_candidate", "probability": prob},
                    log_path,
                )
        except Exception as exc:
            consecutive_errors += 1
            to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "iter": i, "error": str(exc)}, log_path)
            if consecutive_errors >= 3:
                to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "alert": "3_consecutive_errors"}, log_path)
        time.sleep(max(sleep_s, 0.0))
    return probs


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ONNX inference loop for XAUUSD (Yahoo 1h proxy).")
    p.add_argument("--iterations", type=int, default=int(os.getenv("EXECUTOR_ITERATIONS", "0")), help="0 = run until stopped")
    p.add_argument("--sleep", type=float, default=float(os.getenv("EXECUTOR_SLEEP_SECONDS", "60")), help="Seconds between iterations")
    p.add_argument("--model", type=Path, default=MODEL_PATH)
    p.add_argument("--meta", type=Path, default=META_PATH)
    p.add_argument("--log", type=Path, default=LOG_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global MODEL_PATH, META_PATH, LOG_PATH
    args = parse_args(argv or sys.argv[1:])
    MODEL_PATH, META_PATH, LOG_PATH = args.model, args.meta, args.log

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    probs = run_loop(iterations=args.iterations, sleep_s=args.sleep, log_path=args.log, model_path=args.model, meta_path=args.meta)
    if args.iterations > 0:
        print("Probabilities:", [round(p, 4) for p in probs])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
