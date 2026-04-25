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
import psycopg2
from psycopg2 import OperationalError

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from feature_engineering import compute_technical_features, merge_macro_from_csv  # noqa: E402


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
_DEFAULT_THRESHOLD = float(os.getenv("ONNX_SIGNAL_THRESHOLD", "0.65"))

_stop = False


def _handle_stop(signum: int, frame) -> None:  # noqa: ARG001
    global _stop
    _stop = True


def fetch_candles_postgresql() -> pd.DataFrame:
    """
    Last N hourly XAUUSD rows from DigitalOcean Managed Postgres (or any PG).

    Connection: ``EXECUTOR_PG_DSN`` **or** host/port/db/user + ``EXECUTOR_PG_PASSWORD``.
    Defaults match a typical DO cluster hostname/port/db/user/sslmode; never commit passwords.
    """
    dsn = os.getenv("EXECUTOR_PG_DSN")
    try:
        if dsn:
            conn = psycopg2.connect(dsn)
        else:
            password = os.getenv("EXECUTOR_PG_PASSWORD")
            if not password:
                raise RuntimeError(
                    "Defina EXECUTOR_PG_PASSWORD ou EXECUTOR_PG_DSN (senha fora do código / git). "
                    "Host padrão: cluster DO em EXECUTOR_PG_HOST se necessário."
                )
            conn = psycopg2.connect(
                host=os.getenv("EXECUTOR_PG_HOST", "dbaas-db-6174717-do-user-24755128-0.k.db.ondigitalocean.com"),
                port=int(os.getenv("EXECUTOR_PG_PORT", "25060")),
                dbname=os.getenv("EXECUTOR_PG_DB", "defaultdb"),
                user=os.getenv("EXECUTOR_PG_USER", "doadmin"),
                password=password,
                sslmode=os.getenv("EXECUTOR_PG_SSLMODE", "require"),
            )
    except OperationalError as exc:
        err = str(exc).lower()
        if "password authentication failed" in err:
            raise RuntimeError(
                "PostgreSQL recusou a password do utilizador doadmin. "
                "No DigitalOcean: Databases > o teu cluster > Connection Details, copia a password real "
                "(não uses o texto de exemplo do tutorial). "
                "Caracteres especiais na password: preferível EXECUTOR_PG_DSN com password URL-encoded."
            ) from exc
        raise
    ativo = os.getenv("EXECUTOR_PG_ATIVO", "XAUUSD_1H")
    # Default >96 so rolling ma_200 / indicators are defined after dropna()
    limit = int(os.getenv("EXECUTOR_PG_FETCH_LIMIT", "280"))
    query = """
        SELECT time, open, high, low, close, volume
        FROM precos
        WHERE ativo = %s
        ORDER BY time DESC
        LIMIT %s
    """
    try:
        df = pd.read_sql(query, conn, params=[ativo, limit])
    finally:
        conn.close()
    return df.sort_values("time").reset_index(drop=True)


def to_jsonl(payload: dict, log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True) + "\n")


def load_scaler(meta: dict) -> object | None:
    """Load sklearn scaler if configured in metadata."""
    scaler_obj = meta.get("scaler")
    scaler_path = meta.get("scaler_path")
    if scaler_path:
        path = Path(str(scaler_path))
        if not path.exists():
            raise FileNotFoundError(f"Scaler path not found: {path}")
        if path.suffix.lower() in {".pkl", ".joblib"}:
            import joblib

            return joblib.load(path)
        import pickle

        return pickle.loads(path.read_bytes())
    if scaler_obj is None:
        return None
    # If someone inlined a serialized blob (not recommended), ignore.
    return None


def run_loop(
    iterations: int,
    sleep_s: float,
    log_path: Path,
    model_path: Path,
    meta_path: Path,
    threshold: float,
) -> list[float]:
    if not model_path.exists():
        raise FileNotFoundError(f"ONNX model not found at {model_path}")
    if not meta_path.exists():
        raise FileNotFoundError(
            f"Metadata JSON not found at {meta_path}. Copy xauusd_catboost_v2_meta.json next to the model."
        )

    sess = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    model_features = meta.get("features", [])
    scaler = load_scaler(meta)

    probs: list[float] = []
    consecutive_errors = 0
    i = 0
    while not _stop:
        i += 1
        if iterations > 0 and i > iterations:
            break
        try:
            candles = fetch_candles_postgresql()
            candles["time"] = pd.to_datetime(candles["time"], utc=True, errors="coerce")
            candles = compute_technical_features(candles)
            # Macro merge uses the same CSV sources as training dataset builder (when present).
            candles = merge_macro_from_csv(candles, ROOT)
            candles = candles.dropna().reset_index(drop=True)
            for col in model_features:
                if col not in candles.columns:
                    candles[col] = 0.0
            row = candles.iloc[-1]
            row_dict = {k: (float(row[k]) if k in row.index else 0.0) for k in model_features}
            rag_summary: dict | None = None
            if os.getenv("ONNX_USE_RAG", "1").strip().lower() not in ("0", "false", "no"):
                try:
                    from rag_pipeline.vector_store import VectorStore

                    hours = int(os.getenv("RAG_LOOKBACK_HOURS", "24"))
                    vs = VectorStore()
                    context = vs.get_context_recent(hours)
                    derived = vs.get_context_derived(hours)
                    rag_summary = {
                        "empty": not context.strip(),
                        "derived": derived,
                        "text_preview": context[:400],
                        "faiss_docs": vs.count(),
                    }
                    if not context.strip() and i == 1:
                        print(
                            "[executor_onnx] RAG: FAISS vazio ou sem docs na janela "
                            "(só features técnicas; correr python3 rag_pipeline/ingestion_pipeline.py)",
                            file=sys.stderr,
                        )
                    for k, v in derived.items():
                        if k in model_features:
                            row_dict[k] = float(v)
                except Exception as exc:
                    if i == 1:
                        print(f"[executor_onnx] RAG unavailable: {exc}", file=sys.stderr)
            x = np.array([[row_dict[k] for k in model_features]], dtype=np.float32)
            if scaler is not None:
                x = scaler.transform(x)
            if i <= 5:
                vec = {k: float(row_dict[k]) for k in model_features}
                vec_scaled = None
                if scaler is not None:
                    vec_scaled = [float(v) for v in np.asarray(x).reshape(-1)]
                out = {
                    "iter": i,
                    "features_pre_prediction": vec,
                    "features_after_scaler": vec_scaled,
                }
                if rag_summary is not None:
                    out["rag_context"] = rag_summary
                print(json.dumps(out, ensure_ascii=True))
            pred_label, pred_probs = sess.run(None, {in_name: x})
            prob = float(pred_probs[0].get(1, pred_probs[0].get("1", 0.0)))
            signal = prob > threshold
            probs.append(prob)
            consecutive_errors = 0
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "iter": i,
                "probability": prob,
                "signal": bool(signal),
                "threshold": threshold,
            }
            if rag_summary is not None:
                payload["rag_context"] = rag_summary
            to_jsonl(payload, log_path)
            if signal:
                to_jsonl(
                    {"ts": datetime.now(timezone.utc).isoformat(), "event": "order_candidate", "probability": prob},
                    log_path,
                )
        except Exception as exc:
            consecutive_errors += 1
            if iterations > 0 and consecutive_errors <= 3:
                print(f"[executor_onnx] iter {i} failed: {exc}", file=sys.stderr)
            to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "iter": i, "error": str(exc)}, log_path)
            if consecutive_errors >= 3:
                to_jsonl({"ts": datetime.now(timezone.utc).isoformat(), "alert": "3_consecutive_errors"}, log_path)
        time.sleep(max(sleep_s, 0.0))
    return probs


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ONNX inference loop for XAUUSD (PostgreSQL 1h candles).")
    p.add_argument(
        "--iterations",
        "--max-iterations",
        type=int,
        default=int(os.getenv("EXECUTOR_ITERATIONS", "0")),
        dest="iterations",
        help="0 = run until stopped (alias: --max-iterations)",
    )
    p.add_argument(
        "--sleep",
        "--interval",
        type=float,
        default=float(os.getenv("EXECUTOR_SLEEP_SECONDS", "60")),
        dest="sleep",
        help="Seconds between iterations (alias: --interval)",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        help="Probability threshold for signal (default: ONNX_SIGNAL_THRESHOLD or 0.65)",
    )
    p.add_argument("--model", type=Path, default=MODEL_PATH)
    p.add_argument("--meta", type=Path, default=META_PATH)
    p.add_argument("--log", type=Path, default=LOG_PATH)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global MODEL_PATH, META_PATH, LOG_PATH
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    args = parse_args(argv or sys.argv[1:])
    MODEL_PATH, META_PATH, LOG_PATH = args.model, args.meta, args.log

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    probs = run_loop(
        iterations=args.iterations,
        sleep_s=args.sleep,
        log_path=args.log,
        model_path=args.model,
        meta_path=args.meta,
        threshold=args.threshold,
    )
    if args.iterations > 0:
        print("Probabilities:", [round(p, 4) for p in probs])
        if len(probs) != args.iterations:
            print(
                f"[executor_onnx] expected {args.iterations} successful iterations, got {len(probs)} "
                f"(check PostgreSQL env: EXECUTOR_PG_PASSWORD or EXECUTOR_PG_DSN; log: {args.log})",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
