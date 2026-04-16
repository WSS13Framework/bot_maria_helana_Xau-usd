import argparse
import json
from pathlib import Path

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_PURGED_INPUT = DATA_DIR / "purged_walkforward_metrics.json"
DEFAULT_ROBUSTNESS_INPUT = DATA_DIR / "robustness_grid_summary.json"
DEFAULT_HOLDOUT_INPUT = DATA_DIR / "holdout_metrics.json"
DEFAULT_OUTPUT = DATA_DIR / "gate_report.json"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _check(condition: bool, message: str) -> dict:
    return {"passed": bool(condition), "message": message}


def build_gate_report(
    purged_metrics: dict,
    robustness_summary: dict,
    holdout_metrics: dict,
    min_auc: float,
    min_ap: float,
    min_profit_factor: float,
    max_drawdown_abs: float,
) -> dict:
    purged_mean = purged_metrics.get("mean_metrics", {})
    purged_auc = purged_mean.get("roc_auc")
    purged_ap = purged_mean.get("average_precision")

    best_robustness = robustness_summary.get("best_scenario", {}) or {}
    robustness_risk_pnl = best_robustness.get("risk_net_pnl_usd")

    holdout_ap = holdout_metrics.get("holdout_average_precision")
    holdout_auc = holdout_metrics.get("holdout_roc_auc")
    backtest_metrics = holdout_metrics.get("backtest_metrics", {}) or {}
    risk_metrics = holdout_metrics.get("risk_metrics", {}) or {}
    holdout_profit_factor = backtest_metrics.get("profit_factor")
    holdout_drawdown = risk_metrics.get("max_drawdown_usd")
    holdout_risk_pnl = risk_metrics.get("net_pnl_usd")

    checks = {
        "gate1_model_generalization": [
            _check(purged_auc is not None and purged_auc >= min_auc, f"Purged AUC >= {min_auc}"),
            _check(purged_ap is not None and purged_ap >= min_ap, f"Purged AP >= {min_ap}"),
            _check(holdout_auc is not None and holdout_auc >= min_auc, f"Holdout AUC >= {min_auc}"),
            _check(holdout_ap is not None and holdout_ap >= min_ap, f"Holdout AP >= {min_ap}"),
        ],
        "gate2_trading_viability": [
            _check(
                holdout_profit_factor is not None and holdout_profit_factor >= min_profit_factor,
                f"Holdout PF >= {min_profit_factor}",
            ),
            _check(
                holdout_drawdown is not None and abs(holdout_drawdown) <= max_drawdown_abs,
                f"Holdout abs(max_drawdown) <= {max_drawdown_abs}",
            ),
            _check(holdout_risk_pnl is not None and holdout_risk_pnl > 0, "Holdout risk net pnl > 0"),
        ],
        "gate3_robustness": [
            _check(robustness_risk_pnl is not None and robustness_risk_pnl > 0, "Best robustness scenario risk net pnl > 0"),
        ],
    }

    gate_status = {}
    for gate_name, gate_checks in checks.items():
        gate_status[gate_name] = {
            "passed": all(item["passed"] for item in gate_checks),
            "checks": gate_checks,
        }

    overall_passed = all(gate["passed"] for gate in gate_status.values())
    recommendation = (
        "APPROVED_FOR_SHADOW"
        if overall_passed
        else "NOT_APPROVED_FOR_SHADOW"
    )

    report = {
        "inputs": {
            "purged_auc": purged_auc,
            "purged_ap": purged_ap,
            "holdout_auc": holdout_auc,
            "holdout_ap": holdout_ap,
            "holdout_profit_factor": holdout_profit_factor,
            "holdout_risk_drawdown": holdout_drawdown,
            "holdout_risk_pnl": holdout_risk_pnl,
            "best_robustness_risk_pnl": robustness_risk_pnl,
            "best_robustness_threshold": best_robustness.get("threshold"),
            "best_robustness_cost_bps": best_robustness.get("cost_bps_total"),
        },
        "thresholds": {
            "min_auc": min_auc,
            "min_ap": min_ap,
            "min_profit_factor": min_profit_factor,
            "max_drawdown_abs": max_drawdown_abs,
        },
        "gates": gate_status,
        "overall_passed": overall_passed,
        "recommendation": recommendation,
    }
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate institutional gate report for shadow/production progression.")
    parser.add_argument("--purged-input", type=Path, default=DEFAULT_PURGED_INPUT)
    parser.add_argument("--robustness-input", type=Path, default=DEFAULT_ROBUSTNESS_INPUT)
    parser.add_argument("--holdout-input", type=Path, default=DEFAULT_HOLDOUT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-auc", type=float, default=0.75)
    parser.add_argument("--min-ap", type=float, default=0.35)
    parser.add_argument("--min-profit-factor", type=float, default=1.20)
    parser.add_argument("--max-drawdown-abs", type=float, default=2500.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    purged = _load_json(args.purged_input)
    robustness = _load_json(args.robustness_input)
    holdout = _load_json(args.holdout_input)
    report = build_gate_report(
        purged_metrics=purged,
        robustness_summary=robustness,
        holdout_metrics=holdout,
        min_auc=args.min_auc,
        min_ap=args.min_ap,
        min_profit_factor=args.min_profit_factor,
        max_drawdown_abs=args.max_drawdown_abs,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fp:
        json.dump(report, fp, ensure_ascii=False)

    print(f"✅ Gate report salvo em {args.output}")
    print(f"   Recommendation: {report['recommendation']}")


if __name__ == "__main__":
    main()
