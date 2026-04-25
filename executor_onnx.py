import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd


MODEL_PATH = Path("/root/MonetaBot-Pro/ai/models/xauusd_model.onnx")
META_PATH = Path("/root/MonetaBot-Pro/ai/models/xauusd_catboost_v2_meta.json")
LOG_PATH = Path("/root/maria-helena/logs/demo_monitor.jsonl")
THRESHOLD = float(os.getenv("ONNX_SIGNAL_THRESHOLD", "0.65"))


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
    data = data.reset_index().rename(columns={"Datetime": "time", "Open": "open", "High": "high", "Low": "low", "Close": "close"})
    return data[["time", "open", "high", "low", "close"]].tail(limit).reset_index(drop=True)


def to_jsonl(payload: dict):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def run_demo(iterations: int = 10):
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"ONNX model not found at {MODEL_PATH}")
    sess = ort.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    model_features = json.loads(META_PATH.read_text(encoding="utf-8")).get("features", [])
    probs = []
    consecutive_errors = 0
    for i in range(iterations):
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
            # CatBoost ONNX exports probability as seq(map(class->prob)).
            prob = float(pred_probs[0].get(1, pred_probs[0].get("1", 0.0)))
            signal = prob > THRESHOLD
            probs.append(prob)
            consecutive_errors = 0
            to_jsonl(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "iter": i + 1,
                    "probability": prob,
                    "signal": bool(signal),
                    "threshold": THRESHOLD,
                }
            )
            if signal:
                to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "event": "order_candidate", "probability": prob})
        except Exception as exc:
            consecutive_errors += 1
            to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "iter": i + 1, "error": str(exc)})
            if consecutive_errors >= 3:
                to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "alert": "3_consecutive_errors"})
        time.sleep(1)
    print("Probabilities:", [round(p, 4) for p in probs])


if __name__ == "__main__":
    run_demo(iterations=10)
