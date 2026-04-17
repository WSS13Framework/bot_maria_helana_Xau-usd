import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "xauusd_feature_table.csv"
DEFAULT_OUTPUT = DATA_DIR / "xauusd_feature_table_with_exogenous.csv"


def _safe_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce").ffill().bfill().fillna(0.0)
    return pd.Series(np.zeros(len(frame), dtype=float), index=frame.index, dtype=float)


def _first_available_series(frame: pd.DataFrame, candidates: list[str]) -> pd.Series:
    for column in candidates:
        if column in frame.columns:
            return _safe_series(frame, column)
    return pd.Series(np.zeros(len(frame), dtype=float), index=frame.index, dtype=float)


def _compute_news_shock_score(frame: pd.DataFrame) -> pd.Series:
    news_1h = _safe_series(frame, "news_count_1h")
    news_4h = _safe_series(frame, "news_count_4h")
    denom = np.maximum(news_4h.to_numpy(dtype=float), 1.0)
    burst = np.clip(news_1h.to_numpy(dtype=float) / denom, 0.0, 1.0)
    count_score = np.clip((news_1h / 3.0) + (news_4h / 8.0), 0.0, 1.0).to_numpy(dtype=float)

    keyword_columns = [column for column in frame.columns if column.startswith("news_kw_") and column.endswith("_4h")]
    if keyword_columns:
        keyword_sum = pd.to_numeric(frame[keyword_columns].sum(axis=1), errors="coerce").fillna(0.0)
        keyword_score = np.clip((keyword_sum / max(4.0, len(keyword_columns) * 0.5)), 0.0, 1.0).to_numpy(dtype=float)
    else:
        keyword_score = np.zeros(len(frame), dtype=float)

    news_score = (0.45 * count_score) + (0.30 * burst) + (0.25 * keyword_score)
    return pd.Series(np.clip(news_score, 0.0, 1.0), index=frame.index, dtype=float)


def _compute_macro_shock_score(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    dxy = _first_available_series(frame, ["macro_dxy_yahoo", "macro_dxy_fred_proxy"])
    vix = _first_available_series(frame, ["macro_vix_yahoo"])
    us10y = _first_available_series(frame, ["macro_us10y_fred"])

    dxy_move = dxy.pct_change().abs().fillna(0.0)
    vix_move = vix.pct_change().abs().fillna(0.0)
    us10y_move = us10y.diff().abs().fillna(0.0)

    dxy_score = np.clip(dxy_move / 0.0035, 0.0, 1.0)
    vix_score = np.clip(vix_move / 0.0600, 0.0, 1.0)
    us10y_score = np.clip(us10y_move / 0.0800, 0.0, 1.0)

    macro_score = (0.35 * dxy_score) + (0.40 * vix_score) + (0.25 * us10y_score)
    macro_score = pd.Series(np.clip(macro_score, 0.0, 1.0), index=frame.index, dtype=float)
    return macro_score, dxy, vix, us10y


def _compute_cross_market_shock_score(frame: pd.DataFrame) -> pd.Series:
    candidate_return_columns = [
        "us_sp500_ret1d",
        "us_nasdaq_ret1d",
        "eu_dax_ret1d",
        "eu_ftse_ret1d",
        "asia_nikkei_ret1d",
        "asia_hsi_ret1d",
        "copper_fut_ret1d",
        "silver_fut_ret1d",
    ]
    available = [column for column in candidate_return_columns if column in frame.columns]
    if not available:
        return pd.Series(np.zeros(len(frame), dtype=float), index=frame.index, dtype=float)

    stress_components: list[pd.Series] = []
    for column in available:
        ret = _safe_series(frame, column).abs()
        stress_components.append(np.clip(ret / 0.0150, 0.0, 1.0))

    stacked = pd.concat(stress_components, axis=1)
    return stacked.mean(axis=1).clip(0.0, 1.0)


def _compute_gold_bias(
    frame: pd.DataFrame,
    dxy: pd.Series,
    vix: pd.Series,
    us10y: pd.Series,
) -> pd.Series:
    dxy_dir = dxy.pct_change().fillna(0.0)
    vix_dir = vix.pct_change().fillna(0.0)
    us10y_dir = us10y.diff().fillna(0.0)
    sp500_ret = _first_available_series(frame, ["us_sp500_ret1d", "us_dow_ret1d"])
    nasdaq_ret = _first_available_series(frame, ["us_nasdaq_ret1d"])

    long_pressure = (
        np.clip(vix_dir / 0.05, 0.0, None)
        + np.clip((-sp500_ret) / 0.020, 0.0, None)
        + np.clip((-nasdaq_ret) / 0.025, 0.0, None)
    )
    short_pressure = (
        np.clip(dxy_dir / 0.004, 0.0, None)
        + np.clip(us10y_dir / 0.060, 0.0, None)
        + np.clip(sp500_ret / 0.020, 0.0, None)
    )

    bias = np.zeros(len(frame), dtype=int)
    long_condition = (long_pressure >= (short_pressure * 1.2)) & (long_pressure >= 1.0)
    short_condition = (short_pressure >= (long_pressure * 1.2)) & (short_pressure >= 1.0)
    bias[long_condition.to_numpy(dtype=bool)] = 1
    bias[short_condition.to_numpy(dtype=bool)] = -1
    return pd.Series(bias, index=frame.index, dtype=int)


def add_exogenous_shock_features(frame: pd.DataFrame, shock_threshold: float = 0.55) -> pd.DataFrame:
    enriched = frame.copy()
    if enriched.empty:
        enriched["news_shock_score"] = 0.0
        enriched["macro_shock_score"] = 0.0
        enriched["cross_market_shock_score"] = 0.0
        enriched["exogenous_shock_score"] = 0.0
        enriched["exogenous_shock_flag"] = 0
        enriched["exogenous_gold_bias"] = 0
        enriched["exogenous_risk_multiplier"] = 1.0
        enriched["exogenous_threshold_premium"] = 0.0
        return enriched

    shock_threshold = float(np.clip(shock_threshold, 0.0, 1.0))
    news_score = _compute_news_shock_score(enriched)
    macro_score, dxy, vix, us10y = _compute_macro_shock_score(enriched)
    cross_market_score = _compute_cross_market_shock_score(enriched)

    exogenous_score = ((0.40 * news_score) + (0.35 * macro_score) + (0.25 * cross_market_score)).clip(0.0, 1.0)
    exogenous_flag = (exogenous_score >= shock_threshold).astype(int)
    gold_bias = _compute_gold_bias(enriched, dxy=dxy, vix=vix, us10y=us10y)

    risk_multiplier = (1.0 - (0.50 * exogenous_score)).clip(0.45, 1.0)
    threshold_premium = np.where(
        exogenous_flag.to_numpy(dtype=int) == 1,
        np.clip((exogenous_score - shock_threshold) * 0.25 + 0.05, 0.05, 0.15),
        0.0,
    )

    enriched["news_shock_score"] = news_score
    enriched["macro_shock_score"] = macro_score
    enriched["cross_market_shock_score"] = cross_market_score
    enriched["exogenous_shock_score"] = exogenous_score
    enriched["exogenous_shock_flag"] = exogenous_flag
    enriched["exogenous_gold_bias"] = gold_bias
    enriched["exogenous_risk_multiplier"] = risk_multiplier
    enriched["exogenous_threshold_premium"] = threshold_premium
    return enriched


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate exogenous shock features for XAUUSD.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--shock-threshold", type=float, default=0.55)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = pd.read_csv(args.input)
    if "time" in frame.columns:
        frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
        frame = frame.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    enriched = add_exogenous_shock_features(frame, shock_threshold=args.shock_threshold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(args.output, index=False)

    shock_rate = float(enriched["exogenous_shock_flag"].mean()) if len(enriched) else 0.0
    print(f"✅ Exogenous flags salvos em {args.output}")
    print(f"   Linhas: {len(enriched)} | Shock rate: {shock_rate:.4f}")


if __name__ == "__main__":
    main()
