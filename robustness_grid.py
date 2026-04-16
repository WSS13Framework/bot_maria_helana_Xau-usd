import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_METRICS_OUTPUT = DATA_DIR / "robustness_grid_results.csv"
DEFAULT_SUMMARY_OUTPUT = DATA_DIR / "robustness_grid_summary.json"


def _run_command(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def run_robustness_grid(
    labeled_input: Path,
    predictions_input: Path,
    thresholds: list[float],
    cost_scenarios: list[tuple[float, float]],
    risk_per_trade_usd: float,
    atr_sl_mult: float,
    tp_rr: float,
) -> pd.DataFrame:
    rows: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="robustness-grid-") as tmpdir:
        tmp_path = Path(tmpdir)
        for threshold in thresholds:
            for spread_bps, slippage_bps in cost_scenarios:
                trades_path = tmp_path / f"trades_t{threshold}_s{spread_bps}_l{slippage_bps}.csv"
                backtest_metrics_path = tmp_path / f"backtest_t{threshold}_s{spread_bps}_l{slippage_bps}.json"
                risk_trades_path = tmp_path / f"risk_t{threshold}_s{spread_bps}_l{slippage_bps}.csv"
                risk_metrics_path = tmp_path / f"risk_t{threshold}_s{spread_bps}_l{slippage_bps}.json"

                _run_command(
                    [
                        "python3",
                        "backtest_walkforward.py",
                        "--predictions-input",
                        str(predictions_input),
                        "--labeled-input",
                        str(labeled_input),
                        "--trades-output",
                        str(trades_path),
                        "--metrics-output",
                        str(backtest_metrics_path),
                        "--confidence-threshold",
                        str(threshold),
                        "--risk-per-trade-usd",
                        str(risk_per_trade_usd),
                        "--atr-sl-mult",
                        str(atr_sl_mult),
                        "--tp-rr",
                        str(tp_rr),
                        "--spread-bps",
                        str(spread_bps),
                        "--slippage-bps",
                        str(slippage_bps),
                    ]
                )

                _run_command(
                    [
                        "python3",
                        "risk_execution.py",
                        "--input",
                        str(trades_path),
                        "--output",
                        str(risk_trades_path),
                        "--metrics-output",
                        str(risk_metrics_path),
                        "--risk-per-trade-usd",
                        str(risk_per_trade_usd),
                    ]
                )

                backtest_metrics = _load_json(backtest_metrics_path)
                risk_metrics = _load_json(risk_metrics_path)
                rows.append(
                    {
                        "threshold": threshold,
                        "spread_bps": spread_bps,
                        "slippage_bps": slippage_bps,
                        "cost_bps_total": spread_bps + slippage_bps,
                        "backtest_trades": backtest_metrics.get("trades"),
                        "backtest_win_rate": backtest_metrics.get("win_rate"),
                        "backtest_profit_factor": backtest_metrics.get("profit_factor"),
                        "backtest_net_pnl_usd": backtest_metrics.get("net_pnl_usd"),
                        "backtest_max_drawdown_usd": backtest_metrics.get("max_drawdown_usd"),
                        "risk_executed_trades": risk_metrics.get("executed_trades"),
                        "risk_net_pnl_usd": risk_metrics.get("net_pnl_usd"),
                        "risk_max_drawdown_usd": risk_metrics.get("max_drawdown_usd"),
                        "risk_win_rate": risk_metrics.get("win_rate"),
                    }
                )

    result = pd.DataFrame(rows)
    result = result.sort_values(
        by=["risk_net_pnl_usd", "backtest_profit_factor", "risk_executed_trades"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run threshold/cost robustness grid for walk-forward backtest.")
    parser.add_argument("--labeled-input", type=Path, default=DATA_DIR / "xauusd_labeled_dataset.csv")
    parser.add_argument("--predictions-input", type=Path, default=DATA_DIR / "baseline_predictions.csv")
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--thresholds", type=str, default="0.55,0.60,0.65,0.70")
    parser.add_argument("--cost-scenarios", type=str, default="3:2,5:5,8:8")
    parser.add_argument("--risk-per-trade-usd", type=float, default=100.0)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--tp-rr", type=float, default=1.5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    cost_scenarios: list[tuple[float, float]] = []
    for item in args.cost_scenarios.split(","):
        item = item.strip()
        if not item:
            continue
        spread_str, slippage_str = item.split(":", 1)
        cost_scenarios.append((float(spread_str), float(slippage_str)))

    results = run_robustness_grid(
        labeled_input=args.labeled_input,
        predictions_input=args.predictions_input,
        thresholds=thresholds,
        cost_scenarios=cost_scenarios,
        risk_per_trade_usd=args.risk_per_trade_usd,
        atr_sl_mult=args.atr_sl_mult,
        tp_rr=args.tp_rr,
    )
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(args.metrics_output, index=False)

    top_row = results.iloc[0].to_dict() if not results.empty else {}
    summary = {
        "rows": int(len(results)),
        "best_scenario": top_row,
        "thresholds": thresholds,
        "cost_scenarios": [{"spread_bps": s, "slippage_bps": l} for s, l in cost_scenarios],
    }
    with args.summary_output.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False)

    print(f"✅ Robustness grid salvo em {args.metrics_output}")
    print(f"✅ Resumo salvo em {args.summary_output}")
    if top_row:
        print(
            "   Melhor cenário: "
            f"threshold={top_row.get('threshold')} | "
            f"cost={top_row.get('cost_bps_total')} bps | "
            f"risk_net_pnl_usd={top_row.get('risk_net_pnl_usd')}"
        )


if __name__ == "__main__":
    main()
