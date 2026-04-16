import argparse
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "walkforward_trades.csv"
DEFAULT_OUTPUT = DATA_DIR / "risk_adjusted_trades.csv"
DEFAULT_METRICS_OUTPUT = DATA_DIR / "risk_execution_metrics.json"


def apply_risk_controls(
    trades: pd.DataFrame,
    max_daily_loss_usd: float,
    max_trades_per_day: int,
    max_open_risk_usd: float,
    risk_per_trade_usd: float,
) -> tuple[pd.DataFrame, dict]:
    if trades.empty:
        return trades.copy(), {
            "input_trades": 0,
            "executed_trades": 0,
            "blocked_daily_loss": 0,
            "blocked_trade_cap": 0,
            "blocked_risk_cap": 0,
            "net_pnl_usd": 0.0,
            "max_drawdown_usd": 0.0,
        }

    ordered = trades.copy()
    ordered["time"] = pd.to_datetime(ordered["time"], utc=True, errors="coerce")
    ordered = ordered.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    ordered["trade_day"] = ordered["time"].dt.date.astype(str)

    executed_rows = []
    blocked_daily_loss = 0
    blocked_trade_cap = 0
    blocked_risk_cap = 0

    day_stats: dict[str, dict[str, float | int]] = {}
    for _, row in ordered.iterrows():
        day = row["trade_day"]
        stats = day_stats.setdefault(day, {"pnl": 0.0, "count": 0})

        if stats["pnl"] <= -max_daily_loss_usd:
            blocked_daily_loss += 1
            continue
        if stats["count"] >= max_trades_per_day:
            blocked_trade_cap += 1
            continue
        if risk_per_trade_usd > max_open_risk_usd:
            blocked_risk_cap += 1
            continue

        executed_rows.append(row.to_dict())
        stats["pnl"] += float(row["net_pnl_usd"])
        stats["count"] += 1

    executed = pd.DataFrame(executed_rows)
    if executed.empty:
        metrics = {
            "input_trades": int(len(ordered)),
            "executed_trades": 0,
            "blocked_daily_loss": blocked_daily_loss,
            "blocked_trade_cap": blocked_trade_cap,
            "blocked_risk_cap": blocked_risk_cap,
            "net_pnl_usd": 0.0,
            "max_drawdown_usd": 0.0,
        }
        return executed, metrics

    executed["equity_curve_usd"] = executed["net_pnl_usd"].cumsum()
    executed["equity_peak_usd"] = executed["equity_curve_usd"].cummax()
    executed["drawdown_usd"] = executed["equity_curve_usd"] - executed["equity_peak_usd"]

    metrics = {
        "input_trades": int(len(ordered)),
        "executed_trades": int(len(executed)),
        "blocked_daily_loss": blocked_daily_loss,
        "blocked_trade_cap": blocked_trade_cap,
        "blocked_risk_cap": blocked_risk_cap,
        "net_pnl_usd": float(executed["net_pnl_usd"].sum()),
        "max_drawdown_usd": float(executed["drawdown_usd"].min()),
        "win_rate": float((executed["net_pnl_usd"] > 0).mean()),
    }
    return executed, metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply risk and execution controls to walk-forward trades.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--max-daily-loss-usd", type=float, default=300.0)
    parser.add_argument("--max-trades-per-day", type=int, default=6)
    parser.add_argument("--max-open-risk-usd", type=float, default=150.0)
    parser.add_argument("--risk-per-trade-usd", type=float, default=100.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades = pd.read_csv(args.input)
    adjusted, metrics = apply_risk_controls(
        trades=trades,
        max_daily_loss_usd=args.max_daily_loss_usd,
        max_trades_per_day=args.max_trades_per_day,
        max_open_risk_usd=args.max_open_risk_usd,
        risk_per_trade_usd=args.risk_per_trade_usd,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    adjusted.to_csv(args.output, index=False)
    with args.metrics_output.open("w", encoding="utf-8") as fp:
        json.dump(metrics, fp, ensure_ascii=False)

    print(f"✅ Trades ajustados por risco salvos em {args.output}")
    print(
        f"   Executados={metrics['executed_trades']} / {metrics['input_trades']} | "
        f"NetPnL={metrics['net_pnl_usd']:.2f} USD | MaxDD={metrics['max_drawdown_usd']:.2f}"
    )
    print(f"✅ Métricas de execução salvas em {args.metrics_output}")


if __name__ == "__main__":
    main()
