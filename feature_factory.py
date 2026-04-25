"""
Unified PostgreSQL candle fetch + canonical feature preparation for inference.

Uses ``compute_technical_features`` from ``feature_engineering`` (single source
of truth for indicator math). Connection env mirrors ``executor_onnx``:
``EXECUTOR_PG_DSN`` or ``EXECUTOR_PG_HOST`` / ``PORT`` / ``DB`` / ``USER`` /
``PASSWORD`` / ``EXECUTOR_PG_SSLMODE``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2

from feature_engineering import FEATURE_PARAMS, compute_technical_features

_OHLCV = ("open", "high", "low", "close", "volume")


def _connect_pg() -> psycopg2.extensions.connection:
    dsn = os.getenv("EXECUTOR_PG_DSN")
    if dsn:
        return psycopg2.connect(dsn)
    sslmode = os.getenv("EXECUTOR_PG_SSLMODE", "prefer")
    return psycopg2.connect(
        host=os.getenv("EXECUTOR_PG_HOST", "localhost"),
        port=int(os.getenv("EXECUTOR_PG_PORT", "5432")),
        dbname=os.getenv("EXECUTOR_PG_DB", "trading"),
        user=os.getenv("EXECUTOR_PG_USER", "postgres"),
        password=os.getenv("EXECUTOR_PG_PASSWORD", "postgres"),
        sslmode=sslmode,
    )


def _audit_path(audit_dir: Path) -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return audit_dir / f"feature_audit_{day}.jsonl"


def _row_to_audit_payload(row: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in row.items():
        if pd.isna(v) and not isinstance(v, (bool, np.bool_)):
            out[k] = None
        elif isinstance(v, (pd.Timestamp, datetime)):
            ts = pd.Timestamp(v)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            out[k] = ts.isoformat()
        elif isinstance(v, np.floating):
            out[k] = float(v)
        elif isinstance(v, np.integer):
            out[k] = int(v)
        elif isinstance(v, np.bool_):
            out[k] = bool(v)
        elif isinstance(v, (float, int, str, bool)):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def _append_daily_feature_audit(row: pd.Series, audit_dir: Path) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = _audit_path(audit_dir)
    payload = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "row": _row_to_audit_payload(row),
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")


def _floor_utc_hour(s: pd.Series) -> pd.Series:
    ts = pd.to_datetime(s, utc=True, errors="coerce")
    return ts.dt.floor("1h")


def _fetch_precos_ohlcv(conn: psycopg2.extensions.connection, ativo: str, limit: int) -> pd.DataFrame:
    q = """
        SELECT time, open, high, low, close, volume
        FROM precos
        WHERE ativo = %s
        ORDER BY time DESC
        LIMIT %s
    """
    df = pd.read_sql(q, conn, params=[ativo, limit])
    return df.sort_values("time").reset_index(drop=True)


def _hourly_grid_ffill(df: pd.DataFrame) -> pd.DataFrame:
    """UTC hourly index from min..max time, forward-fill OHLCV, ``is_gap_filled``."""
    if df.empty:
        return df.assign(is_gap_filled=pd.Series(dtype=bool))

    work = df.copy()
    work["time"] = _floor_utc_hour(work["time"])
    work = work.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last").sort_values("time")
    if work.empty:
        return work.assign(is_gap_filled=pd.Series(dtype=bool))

    g = work.set_index("time").sort_index()
    full_idx = pd.date_range(g.index.min(), g.index.max(), freq="1h", tz="UTC")
    reindexed = g.reindex(full_idx)
    was_missing = reindexed[list(_OHLCV)].isna().any(axis=1)
    reindexed[list(_OHLCV)] = reindexed[list(_OHLCV)].ffill()
    if reindexed[list(_OHLCV)].isna().any().any():
        reindexed[list(_OHLCV)] = reindexed[list(_OHLCV)].bfill()
    reindexed["is_gap_filled"] = was_missing.to_numpy(dtype=bool)
    out = reindexed.reset_index(names="time")
    out["time"] = _floor_utc_hour(out["time"])
    return out


def get_features_for_inference(
    *,
    ativo: str = "XAUUSD_1H",
    params: dict | None = None,
    audit_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Load OHLCV from PostgreSQL, normalize to UTC hourly grid with forward-fill,
    run ``compute_technical_features``, append last row to daily JSONL audit.

    PostgreSQL ``LIMIT`` defaults to ``max(96, ma_slow + 32)`` so rolling
    indicators (e.g. MA 200) are well-defined; override with
    ``FEATURE_FACTORY_PG_FETCH_LIMIT``. After ``compute_technical_features``,
    the dataframe is trimmed to the last ``FEATURE_FACTORY_OUTPUT_TAIL`` rows
    (default ``96``; set ``0`` to keep the full grid).
    """
    p = params or FEATURE_PARAMS
    ma_slow = int(p.get("ma_slow", 200))
    default_limit = max(96, ma_slow + 32)
    fetch_limit = max(96, int(os.getenv("FEATURE_FACTORY_PG_FETCH_LIMIT", str(default_limit))))

    audit_base = audit_dir or Path(os.getenv("FEATURE_FACTORY_AUDIT_DIR", str(Path(__file__).resolve().parent / "logs")))

    conn = _connect_pg()
    try:
        raw = _fetch_precos_ohlcv(conn, ativo, fetch_limit)
    finally:
        conn.close()

    if raw.empty:
        raise ValueError(f"No rows returned for ativo={ativo!r}")

    raw["time"] = _floor_utc_hour(raw["time"])
    raw = raw.dropna(subset=["time"]).drop_duplicates(subset=["time"], keep="last").sort_values("time").reset_index(drop=True)

    gridded = _hourly_grid_ffill(raw)
    gridded["time"] = _floor_utc_hour(gridded["time"])

    feats = compute_technical_features(gridded, params=p)
    feats["time"] = _floor_utc_hour(feats["time"])

    tail_s = os.getenv("FEATURE_FACTORY_OUTPUT_TAIL", "96").strip()
    if tail_s.isdigit() and int(tail_s) > 0:
        n = int(tail_s)
        feats = feats.iloc[-n:].reset_index(drop=True)
        feats["time"] = _floor_utc_hour(feats["time"])

    last = feats.iloc[-1]
    _append_daily_feature_audit(last, audit_base)

    return feats
