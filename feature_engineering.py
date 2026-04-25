"""
Canonical feature engineering for XAUUSD pipelines.

All training / validation / ONNX inference code should import from here to
avoid drift between offline CSV generation and online inference.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


FEATURE_PARAMS = {
    "schema_version": 1,
    "rsi_period": 14,
    "atr_period": 14,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "ret_short_lag": 1,
    "ret_long_lag": 24,
    "volatility_window": 24,
    "ma_fast": 50,
    "ma_slow": 200,
    "macro_keys": ("dxy", "us10y", "xagusd"),
}


@dataclass(frozen=True)
class MacroPaths:
    dxy: Path | None = None
    us10y: Path | None = None
    xagusd: Path | None = None


def compute_technical_features(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Add RSI/ATR/MACD/vol/MA features on an OHLC dataframe (sorted by time)."""
    p = params or FEATURE_PARAMS
    out = df.copy()

    c, h, l = out["close"], out["high"], out["low"]

    rsi_period = int(p["rsi_period"])
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(rsi_period).mean()
    loss = (-delta.clip(upper=0)).rolling(rsi_period).mean()
    rs = gain / (loss + 1e-9)
    out[f"rsi_{rsi_period}"] = 100 - 100 / (1 + rs)

    atr_period = int(p["atr_period"])
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    out[f"atr_{atr_period}"] = tr.rolling(atr_period).mean()

    fast, slow, sig = int(p["macd_fast"]), int(p["macd_slow"]), int(p["macd_signal"])
    ema12 = c.ewm(span=fast, adjust=False).mean()
    ema26 = c.ewm(span=slow, adjust=False).mean()
    out["macd"] = ema12 - ema26
    out["macd_signal"] = out["macd"].ewm(span=sig, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    out["ret_1h"] = c.pct_change(int(p["ret_short_lag"]))
    out["ret_24h"] = c.pct_change(int(p["ret_long_lag"]))
    out["volatility_24h"] = out["ret_1h"].rolling(int(p["volatility_window"])).std()
    out[f"ma_{int(p['ma_fast'])}"] = c.rolling(int(p["ma_fast"])).mean()
    out[f"ma_{int(p['ma_slow'])}"] = c.rolling(int(p["ma_slow"])).mean()
    return out


def merge_macro_from_csv(df: pd.DataFrame, root: Path, params: dict | None = None) -> pd.DataFrame:
    """Merge daily macro closes from *_h1_db.csv series (last close per UTC day)."""
    p = params or FEATURE_PARAMS
    out = df.copy()
    out["date"] = pd.to_datetime(out["time"], errors="coerce").dt.normalize()

    keys: Iterable[str] = p.get("macro_keys", ())
    for key in keys:
        path = root / "data" / f"{key}_h1_db.csv"
        if not path.exists():
            continue
        m = pd.read_csv(path, parse_dates=["time"])
        m["date"] = m["time"].dt.normalize()
        daily = m.groupby("date", as_index=False)["close"].last().rename(columns={"close": f"macro_{key}"})
        out = pd.merge_asof(out.sort_values("date"), daily.sort_values("date"), on="date", direction="backward")
    return out


def build_model_feature_matrix(df: pd.DataFrame, feature_names: list[str]) -> pd.DataFrame:
    """Return X aligned to feature_names (numeric, inf cleaned, NaN filled with 0)."""
    X = df[feature_names].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return X.astype(np.float32)


def default_feature_columns() -> list[str]:
    """Feature order used by xauusd_1h_features + current CatBoost v2."""
    p = FEATURE_PARAMS
    return [
        f"rsi_{p['rsi_period']}",
        f"atr_{p['atr_period']}",
        "macd",
        "macd_signal",
        "macd_hist",
        "ret_1h",
        "ret_24h",
        "volatility_24h",
        f"ma_{p['ma_fast']}",
        f"ma_{p['ma_slow']}",
        "macro_dxy",
        "macro_us10y",
        "macro_xagusd",
    ]
