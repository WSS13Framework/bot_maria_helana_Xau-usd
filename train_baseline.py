import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "xauusd_labeled_dataset.csv"
DEFAULT_METRICS_OUTPUT = DATA_DIR / "baseline_metrics.json"
DEFAULT_PREDICTIONS_OUTPUT = DATA_DIR / "baseline_predictions.csv"


def _prepare_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)
    return frame


def _select_feature_columns(frame: pd.DataFrame) -> list[str]:
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
    numeric_columns = frame.select_dtypes(include=[np.number]).columns
    return [column for column in numeric_columns if column not in excluded]


def _walk_forward_splits(n_rows: int, n_splits: int, min_train_rows: int) -> list[tuple[np.ndarray, np.ndarray]]:
    if n_rows <= min_train_rows + 10:
        return []

    test_size = max(50, (n_rows - min_train_rows) // n_splits)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    train_end = min_train_rows
    while train_end + test_size <= n_rows:
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(train_end, train_end + test_size)
        splits.append((train_idx, test_idx))
        train_end += test_size
    return splits


def _compute_metrics(y_true: pd.Series, y_prob: np.ndarray, threshold: float) -> dict:
    y_pred = (y_prob >= threshold).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, y_prob)),
        "brier": float(brier_score_loss(y_true, y_prob)),
    }
    unique_targets = np.unique(y_true)
    if unique_targets.size > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_true, y_prob))
    else:
        metrics["roc_auc"] = None
    return metrics


def run_walk_forward(
    frame: pd.DataFrame,
    n_splits: int,
    min_train_rows: int,
    decision_threshold: float,
) -> tuple[dict, pd.DataFrame]:
    feature_columns = _select_feature_columns(frame)
    if not feature_columns:
        raise ValueError("No numeric feature columns available for training.")

    model_input = frame[feature_columns].copy()
    model_input = model_input.ffill().bfill().fillna(0.0)
    target = frame["trade_label"].astype(int)

    splits = _walk_forward_splits(len(frame), n_splits=n_splits, min_train_rows=min_train_rows)
    if not splits:
        raise ValueError("Not enough rows to generate walk-forward splits.")

    fold_results = []
    predictions = []
    for fold_id, (train_idx, test_idx) in enumerate(splits, start=1):
        x_train = model_input.iloc[train_idx]
        y_train = target.iloc[train_idx]
        x_test = model_input.iloc[test_idx]
        y_test = target.iloc[test_idx]

        base_model = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_depth=6,
            max_iter=250,
            random_state=42,
        )
        calibrated = CalibratedClassifierCV(base_model, method="isotonic", cv=3)
        calibrated.fit(x_train, y_train)
        y_prob = calibrated.predict_proba(x_test)[:, 1]

        fold_metrics = _compute_metrics(y_test, y_prob, threshold=decision_threshold)
        fold_metrics["fold"] = fold_id
        fold_metrics["train_rows"] = int(len(train_idx))
        fold_metrics["test_rows"] = int(len(test_idx))
        fold_results.append(fold_metrics)

        fold_predictions = frame.iloc[test_idx][["time"]].copy()
        fold_predictions["y_true"] = y_test.to_numpy()
        fold_predictions["y_prob"] = y_prob
        fold_predictions["y_pred"] = (y_prob >= decision_threshold).astype(int)
        fold_predictions["fold"] = fold_id
        predictions.append(fold_predictions)

    folds_df = pd.DataFrame(fold_results)
    summary = {
        "rows": int(len(frame)),
        "feature_count": len(feature_columns),
        "positive_rate": float(target.mean()),
        "decision_threshold": decision_threshold,
        "folds": folds_df.to_dict(orient="records"),
        "mean_metrics": {
            metric: float(folds_df[metric].dropna().mean())
            for metric in ("accuracy", "precision", "recall", "f1", "average_precision", "brier", "roc_auc")
            if metric in folds_df
        },
    }
    predictions_df = pd.concat(predictions, ignore_index=True)
    return summary, predictions_df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train baseline trade-label model with walk-forward evaluation.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--metrics-output", type=Path, default=DEFAULT_METRICS_OUTPUT)
    parser.add_argument("--predictions-output", type=Path, default=DEFAULT_PREDICTIONS_OUTPUT)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-train-rows", type=int, default=1000)
    parser.add_argument("--decision-threshold", type=float, default=0.60)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = _prepare_frame(args.input)
    summary, predictions = run_walk_forward(
        frame,
        n_splits=args.n_splits,
        min_train_rows=args.min_train_rows,
        decision_threshold=args.decision_threshold,
    )

    args.metrics_output.parent.mkdir(parents=True, exist_ok=True)
    args.predictions_output.parent.mkdir(parents=True, exist_ok=True)
    with args.metrics_output.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False)
    predictions.to_csv(args.predictions_output, index=False)

    mean_metrics = summary["mean_metrics"]
    print(f"✅ Baseline metrics salvas em {args.metrics_output}")
    print(
        "   Média folds: "
        f"AP={mean_metrics.get('average_precision', 0):.4f} | "
        f"F1={mean_metrics.get('f1', 0):.4f} | "
        f"AUC={mean_metrics.get('roc_auc')}"
    )
    print(f"✅ Predições walk-forward salvas em {args.predictions_output}")


if __name__ == "__main__":
    main()
