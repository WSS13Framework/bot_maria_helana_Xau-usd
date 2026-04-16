import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "baseline_predictions.csv"
DEFAULT_LABELED_INPUT = DATA_DIR / "xauusd_labeled_dataset.csv"
DEFAULT_TRADES_OUTPUT = DATA_DIR / "walkforward_trades.csv"
DEFAULT_METRICS_OUTPUT = DATA_DIR / "walkforward_backtest_metrics.json"


def _load_and_align(predictions_path: Path, labeled_path: Path) -> pd.DataFrame:
    predictions = pd.read_csv(predictions_path)
    labeled = pd.read_csv(labeled_path)

    predictions["time"] = pd.to_datetime(predictions["time"], utc=True, errors="coerce")
    labeled["time"] = pd.to_datetime(labeled["time"], utc=True, errors="coerce")
    predictions = predictions.dropna(subset=["time"]).sort_values("time")
    labeled = labeled.dropna(subset=["time"]).sort_values("time")

    required = {"m5_close", "atr", "tb_label", "tb_hit_bars"}
    missing = required.difference(labeled.columns)
    if missing:
        raise ValueError(f"Missing required columns in labeled dataset: {sorted(missing)}")

    merged = pd.merge(
        predictions,
        labeled[["time", "m5_close", "atr", "tb_label", "tb_hit_bars"]],
        on="time",
        how="inner",
    ).sort_values("time")
    return merged.reset_index(drop=True)


def run_backtest(
    frame: pd.DataFrame,
    confidence_threshold: float,
    risk_per_trade_usd: float,
    atr_sl_mult: float,
    tp_rr: float,
    spread_bps: float,
    slippage_bps: float,
) -> tuple[pd.DataFrame, dict]:
    trades = frame[frame["y_prob"] >= confidence_threshold].copy()
    trades = trades[trades["tb_label"] != 0].copy()

    if trades.empty:
        metrics = {
            "trades": 0,
            "win_rate": 0.0,
            "profit_factor": None,
            "avg_trade_pnl_usd": 0.0,
            "net_pnl_usd": 0.0,
            "max_drawdown_usd": 0.0,
            "expectancy_usd": 0.0,
        }
        return trades, metrics

    total_cost_bps = spread_bps + slippage_bps
    cost_fraction = total_cost_bps / 10_000.0

    stop_distance = trades["atr"] * atr_sl_mult
    stop_distance = stop_distance.replace(0, np.nan)
    stop_distance = stop_distance.fillna(trades["m5_close"] * 0.001)
    position_size_oz = risk_per_trade_usd / stop_distance

    gross_pnl = np.where(
        trades["tb_label"] > 0,
        risk_per_trade_usd * tp_rr,
        -risk_per_trade_usd,
    )
    notional = trades["m5_close"] * position_size_oz
    trade_cost = notional * cost_fraction
    net_pnl = gross_pnl - trade_cost

    trades["risk_per_trade_usd"] = risk_per_trade_usd
    trades["tp_rr"] = tp_rr
    trades["position_size_oz"] = position_size_oz
    trades["gross_pnl_usd"] = gross_pnl
    trades["trade_cost_usd"] = trade_cost
    trades["net_pnl_usd"] = net_pnl
    trades["is_win"] = (trades["net_pnl_usd"] > 0).astype(int)
    trades["equity_curve_usd"] = trades["net_pnl_usd"].cumsum()
    trades["equity_peak_usd"] = trades["equity_curve_usd"].cummax()
    trades["drawdown_usd"] = trades["equity_curve_usd"] - trades["equity_peak_usd"]

    gross_profit = trades.loc[trades["net_pnl_usd"] > 0, "net_pnl_usd"].sum()
    gross_loss = -trades.loc[trades["net_pnl_usd"] < 0, "net_pnl_usd"].sum()
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else None

    metrics = {
        "trades": int(len(trades)),
        "confidence_threshold": confidence_threshold,
        "risk_per_trade_usd": risk_per_trade_usd,
        "tp_rr": tp_rr,
        "spread_bps": spread_bps,
        "slippage_bps": slippage_bps,
        "win_rate": float(trades["is_win"].mean()),
        "profit_factor": profit_factor,
        "avg_trade_pnl_usd": float(trades["net_pnl_usd"].mean()),
        "expectancy_usd": float(trades["net_pnl_usd"].mean()),
        "net_pnl_usd": float(trades["net_pnl_usd"].sum()),
        "max_drawdown_usd": float(trades["drawdown_usd"].min()),
    }
    return trades, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run walk-forward backtest with trading costs.")
    parser.add_argument("--predictions-input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--labeled-input", type=Path, default=DEFAULT_LABELED_INPUT)
    parser.add_argument("--trades-output", type=Path, default=DEFAULT_TRADES_OUTPUT)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--confidence-threshold", type=float, default=0.60)
    parser.add_argument("--risk-per-trade-usd", type=float, default=100.0)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--tp-rr", type=float, default=1.5)
    parser.add_argument("--spread-bps", type=float, default=3.0)
    parser.add_argument("--slippage-bps", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    aligned = _load_and_align(args.predictions_input, args.labeled_input)
    trades, metrics = run_backtest(
        frame=aligned,
        confidence_threshold=args.confidence_threshold,
        risk_per_trade_usd=args.risk_per_trade_usd,
        atr_sl_mult=args.atr_sl_mult,
        tp_rr=args.tp_rr,
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
    )

    args.trades_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.trades_output, index=False)
    with args.metrics_output.open("w", encoding="utf-8") as fp:
        json.dump(metrics, fp, ensure_ascii=False)

    print(f"✅ Trades walk-forward salvos em {args.trades_output}")
    print(
        f"   Trades={metrics['trades']} | WinRate={metrics['win_rate']:.4f} | "
        f"PF={metrics['profit_factor']} | NetPnL={metrics['net_pnl_usd']:.2f} USD"
    )
    print(f"✅ Métricas de backtest salvas em {args.metrics_output}")


if __name__ == "__main__":
    main()
