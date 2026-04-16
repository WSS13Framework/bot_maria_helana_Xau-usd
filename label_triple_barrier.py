import argparse
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "xauusd_feature_table.csv"
DEFAULT_OUTPUT = DATA_DIR / "xauusd_labeled_dataset.csv"


def compute_atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    high = frame["m5_high"]
    low = frame["m5_low"]
    close = frame["m5_close"]
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.rolling(period, min_periods=period).mean()
    return atr


def apply_triple_barrier(
    frame: pd.DataFrame,
    atr_period: int,
    horizon_bars: int,
    tp_atr_mult: float,
    sl_atr_mult: float,
    min_rr: float,
) -> pd.DataFrame:
    labeled = frame.copy()
    labeled["atr"] = compute_atr(labeled, period=atr_period)
    labeled["tb_label"] = 0
    labeled["tb_hit_bars"] = np.nan
    labeled["future_up_atr"] = np.nan
    labeled["future_down_atr"] = np.nan
    labeled["rr_observed"] = np.nan
    labeled["rr_viable"] = 0
    labeled["trade_label"] = 0

    high_values = labeled["m5_high"].to_numpy(dtype=float)
    low_values = labeled["m5_low"].to_numpy(dtype=float)
    close_values = labeled["m5_close"].to_numpy(dtype=float)
    atr_values = labeled["atr"].to_numpy(dtype=float)
    total_rows = len(labeled)

    for idx in range(total_rows):
        atr_value = atr_values[idx]
        if np.isnan(atr_value) or atr_value <= 0:
            continue

        close_price = close_values[idx]
        upper_barrier = close_price + (tp_atr_mult * atr_value)
        lower_barrier = close_price - (sl_atr_mult * atr_value)
        final_idx = min(total_rows - 1, idx + horizon_bars)
        if final_idx <= idx:
            continue

        future_high = high_values[idx + 1 : final_idx + 1]
        future_low = low_values[idx + 1 : final_idx + 1]
        if future_high.size == 0:
            continue

        max_upside_atr = (future_high.max() - close_price) / atr_value
        max_downside_atr = (close_price - future_low.min()) / atr_value
        rr_observed = max_upside_atr / max(max_downside_atr, 1e-9)

        labeled.at[idx, "future_up_atr"] = max_upside_atr
        labeled.at[idx, "future_down_atr"] = max_downside_atr
        labeled.at[idx, "rr_observed"] = rr_observed

        first_up_hit = None
        first_down_hit = None
        for step, (h_val, l_val) in enumerate(zip(future_high, future_low), start=1):
            if first_up_hit is None and h_val >= upper_barrier:
                first_up_hit = step
            if first_down_hit is None and l_val <= lower_barrier:
                first_down_hit = step
            if first_up_hit is not None and first_down_hit is not None:
                break

        label = 0
        hit_bars = np.nan
        if first_up_hit is not None and first_down_hit is not None:
            if first_up_hit < first_down_hit:
                label = 1
                hit_bars = first_up_hit
            elif first_down_hit < first_up_hit:
                label = -1
                hit_bars = first_down_hit
        elif first_up_hit is not None:
            label = 1
            hit_bars = first_up_hit
        elif first_down_hit is not None:
            label = -1
            hit_bars = first_down_hit

        rr_viable = int(
            max_upside_atr >= tp_atr_mult
            and max_downside_atr <= sl_atr_mult * 1.5
            and rr_observed >= min_rr
        )
        trade_label = int(label == 1 and rr_viable == 1)

        labeled.at[idx, "tb_label"] = label
        labeled.at[idx, "tb_hit_bars"] = hit_bars
        labeled.at[idx, "rr_viable"] = rr_viable
        labeled.at[idx, "trade_label"] = trade_label

    return labeled


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create triple-barrier labels with RR viability.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--atr-period", type=int, default=14)
    parser.add_argument("--horizon-bars", type=int, default=48)
    parser.add_argument("--tp-atr-mult", type=float, default=1.5)
    parser.add_argument("--sl-atr-mult", type=float, default=1.0)
    parser.add_argument("--min-rr", type=float, default=1.3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = pd.read_csv(args.input)
    dataset["time"] = pd.to_datetime(dataset["time"], utc=True, errors="coerce")
    dataset = dataset.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    labeled = apply_triple_barrier(
        frame=dataset,
        atr_period=args.atr_period,
        horizon_bars=args.horizon_bars,
        tp_atr_mult=args.tp_atr_mult,
        sl_atr_mult=args.sl_atr_mult,
        min_rr=args.min_rr,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_csv(args.output, index=False)

    trade_ratio = float(labeled["trade_label"].mean()) if len(labeled) else 0.0
    print(f"✅ Dataset rotulado salvo em {args.output}")
    print(f"   Linhas: {len(labeled)} | Trade label ratio: {trade_ratio:.4f}")


if __name__ == "__main__":
    main()
