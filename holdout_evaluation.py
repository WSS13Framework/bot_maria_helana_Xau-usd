import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from backtest_walkforward import run_backtest
from risk_execution import apply_risk_controls

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "xauusd_labeled_dataset.csv"
DEFAULT_PREDICTIONS_OUTPUT = DATA_DIR / "holdout_predictions.csv"
DEFAULT_BACKTEST_TRADES_OUTPUT = DATA_DIR / "holdout_backtest_trades.csv"
DEFAULT_RISK_TRADES_OUTPUT = DATA_DIR / "holdout_risk_trades.csv"
DEFAULT_METRICS_OUTPUT = DATA_DIR / "holdout_metrics.json"


def _prepare_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return frame


def _feature_columns(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "time",
        "tb_label",
        "tb_hit_bars",
        "future_up_atr",
        "future_down_atr",
        "rr_observed",
        "rr_viable",
        "trade_label",
    }
    numeric = frame.select_dtypes(include=[np.number]).columns
    return [column for column in numeric if column not in excluded]


def _split_by_time(frame: pd.DataFrame, holdout_ratio: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not (0.05 <= holdout_ratio <= 0.5):
        raise ValueError("holdout_ratio must be between 0.05 and 0.50")
    split_idx = int(len(frame) * (1.0 - holdout_ratio))
    split_idx = min(max(split_idx, 1), len(frame) - 1)
    train = frame.iloc[:split_idx].copy()
    holdout = frame.iloc[split_idx:].copy()
    return train, holdout


def evaluate_holdout(
    frame: pd.DataFrame,
    holdout_ratio: float,
    decision_threshold: float,
    risk_per_trade_usd: float,
    atr_sl_mult: float,
    tp_rr: float,
    spread_bps: float,
    slippage_bps: float,
    max_daily_loss_usd: float,
    max_trades_per_day: int,
    max_open_risk_usd: float,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    features = _feature_columns(frame)
    if not features:
        raise ValueError("No numeric feature columns available for holdout evaluation.")

    train, holdout = _split_by_time(frame, holdout_ratio=holdout_ratio)
    x_train = train[features].copy().ffill().bfill().fillna(0.0)
    y_train = train["trade_label"].astype(int)
    x_holdout = holdout[features].copy().ffill().bfill().fillna(0.0)
    y_holdout = holdout["trade_label"].astype(int)

    model = CatBoostClassifier(
        loss_function="Logloss",
        eval_metric="AUC",
        iterations=500,
        learning_rate=0.03,
        depth=6,
        l2_leaf_reg=5.0,
        random_strength=0.5,
        subsample=0.8,
        bootstrap_type="Bernoulli",
        random_state=42,
        verbose=False,
    )
    model.fit(x_train, y_train)
    y_prob = model.predict_proba(x_holdout)[:, 1]

    predictions = holdout[["time", "tb_label", "tb_hit_bars", "m5_close", "atr"]].copy()
    predictions["y_true"] = y_holdout.to_numpy()
    predictions["y_prob"] = y_prob
    predictions["y_pred"] = (y_prob >= decision_threshold).astype(int)

    backtest_input = predictions[["time", "y_prob", "y_pred", "y_true", "tb_label", "tb_hit_bars", "m5_close", "atr"]]
    backtest_trades, backtest_metrics = run_backtest(
        frame=backtest_input,
        confidence_threshold=decision_threshold,
        risk_per_trade_usd=risk_per_trade_usd,
        atr_sl_mult=atr_sl_mult,
        tp_rr=tp_rr,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
    )
    risk_trades, risk_metrics = apply_risk_controls(
        trades=backtest_trades,
        max_daily_loss_usd=max_daily_loss_usd,
        max_trades_per_day=max_trades_per_day,
        max_open_risk_usd=max_open_risk_usd,
        risk_per_trade_usd=risk_per_trade_usd,
    )

    unique_targets = np.unique(y_holdout)
    holdout_auc = float(roc_auc_score(y_holdout, y_prob)) if unique_targets.size > 1 else None
    holdout_metrics = {
        "rows_total": int(len(frame)),
        "rows_train": int(len(train)),
        "rows_holdout": int(len(holdout)),
        "time_train_start": train["time"].iloc[0].isoformat(),
        "time_train_end": train["time"].iloc[-1].isoformat(),
        "time_holdout_start": holdout["time"].iloc[0].isoformat(),
        "time_holdout_end": holdout["time"].iloc[-1].isoformat(),
        "holdout_positive_rate": float(y_holdout.mean()),
        "holdout_average_precision": float(average_precision_score(y_holdout, y_prob)),
        "holdout_roc_auc": holdout_auc,
        "holdout_brier": float(brier_score_loss(y_holdout, y_prob)),
        "decision_threshold": decision_threshold,
        "costs_bps": {"spread_bps": spread_bps, "slippage_bps": slippage_bps},
        "backtest_metrics": backtest_metrics,
        "risk_metrics": risk_metrics,
    }
    return predictions, backtest_trades, risk_trades, holdout_metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate out-of-time holdout with backtest and risk gates.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--predictions-output", type=Path, default=DEFAULT_PREDICTIONS_OUTPUT)
    parser.add_argument("--backtest-trades-output", type=Path, default=DEFAULT_BACKTEST_TRADES_OUTPUT)
    parser.add_argument("--risk-trades-output", type=Path, default=DEFAULT_RISK_TRADES_OUTPUT)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--holdout-ratio", type=float, default=0.20)
    parser.add_argument("--decision-threshold", type=float, default=0.65)
    parser.add_argument("--risk-per-trade-usd", type=float, default=100.0)
    parser.add_argument("--atr-sl-mult", type=float, default=1.0)
    parser.add_argument("--tp-rr", type=float, default=1.5)
    parser.add_argument("--spread-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--max-daily-loss-usd", type=float, default=300.0)
    parser.add_argument("--max-trades-per-day", type=int, default=6)
    parser.add_argument("--max-open-risk-usd", type=float, default=150.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = _prepare_frame(args.input)
    predictions, backtest_trades, risk_trades, metrics = evaluate_holdout(
        frame=frame,
        holdout_ratio=args.holdout_ratio,
        decision_threshold=args.decision_threshold,
        risk_per_trade_usd=args.risk_per_trade_usd,
        atr_sl_mult=args.atr_sl_mult,
        tp_rr=args.tp_rr,
        spread_bps=args.spread_bps,
        slippage_bps=args.slippage_bps,
        max_daily_loss_usd=args.max_daily_loss_usd,
        max_trades_per_day=args.max_trades_per_day,
        max_open_risk_usd=args.max_open_risk_usd,
    )

    args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
    args.backtest_trades_output.parent.mkdir(parents=True, exist_ok=True)
    args.risk_trades_output.parent.mkdir(parents=True, exist_ok=True)
    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)

    predictions.to_csv(args.predictions_output, index=False)
    backtest_trades.to_csv(args.backtest_trades_output, index=False)
    risk_trades.to_csv(args.risk_trades_output, index=False)
    with args.metrics_output.open("w", encoding="utf-8") as fp:
        json.dump(metrics, fp, ensure_ascii=False)

    print(f"✅ Holdout metrics salvas em {args.metrics_output}")
    print(
        f"   AP={metrics['holdout_average_precision']:.4f} | "
        f"AUC={metrics['holdout_roc_auc']} | "
        f"RiskPnL={metrics['risk_metrics'].get('net_pnl_usd')}"
    )


if __name__ == "__main__":
    main()
