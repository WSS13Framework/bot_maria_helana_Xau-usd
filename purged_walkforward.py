import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_INPUT = DATA_DIR / "xauusd_labeled_dataset.csv"
DEFAULT_OUTPUT = DATA_DIR / "purged_walkforward_metrics.json"


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


def _purged_splits(
    n_rows: int,
    n_splits: int,
    min_train_rows: int,
    embargo_bars: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    if n_rows <= min_train_rows + 10:
        return []

    test_size = max(50, (n_rows - min_train_rows) // n_splits)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    test_start = min_train_rows
    while test_start + test_size <= n_rows:
        test_end = test_start + test_size
        train_end = max(0, test_start - embargo_bars)
        if train_end <= 0:
            break
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
        test_start += test_size
    return splits


def run_purged_walkforward(
    frame: pd.DataFrame,
    n_splits: int,
    min_train_rows: int,
    embargo_bars: int,
) -> dict:
    features = _feature_columns(frame)
    if not features:
        raise ValueError("No numeric feature columns available for purged walk-forward.")

    x = frame[features].copy().ffill().bfill().fillna(0.0)
    y = frame["trade_label"].astype(int)

    splits = _purged_splits(
        n_rows=len(frame),
        n_splits=n_splits,
        min_train_rows=min_train_rows,
        embargo_bars=embargo_bars,
    )
    if not splits:
        raise ValueError("Not enough rows to generate purged walk-forward splits.")

    folds: list[dict] = []
    for fold_id, (train_idx, test_idx) in enumerate(splits, start=1):
        x_train = x.iloc[train_idx]
        y_train = y.iloc[train_idx]
        x_test = x.iloc[test_idx]
        y_test = y.iloc[test_idx]

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
        y_prob = model.predict_proba(x_test)[:, 1]

        fold_metrics = {
            "fold": fold_id,
            "train_rows": int(len(train_idx)),
            "test_rows": int(len(test_idx)),
            "train_end": frame.iloc[train_idx[-1]]["time"].isoformat(),
            "test_start": frame.iloc[test_idx[0]]["time"].isoformat(),
            "test_end": frame.iloc[test_idx[-1]]["time"].isoformat(),
            "average_precision": float(average_precision_score(y_test, y_prob)),
        }
        unique_targets = np.unique(y_test)
        fold_metrics["roc_auc"] = (
            float(roc_auc_score(y_test, y_prob)) if unique_targets.size > 1 else None
        )
        folds.append(fold_metrics)

    folds_df = pd.DataFrame(folds)
    summary = {
        "rows": int(len(frame)),
        "feature_count": len(features),
        "positive_rate": float(y.mean()),
        "n_splits": n_splits,
        "min_train_rows": min_train_rows,
        "embargo_bars": embargo_bars,
        "folds": folds,
        "mean_metrics": {
            "average_precision": float(folds_df["average_precision"].dropna().mean()),
            "roc_auc": float(folds_df["roc_auc"].dropna().mean()) if "roc_auc" in folds_df else None,
        },
    }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run purged walk-forward with embargo bars.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--min-train-rows", type=int, default=2500)
    parser.add_argument("--embargo-bars", type=int, default=48)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = _prepare_frame(args.input)
    summary = run_purged_walkforward(
        frame=frame,
        n_splits=args.n_splits,
        min_train_rows=args.min_train_rows,
        embargo_bars=args.embargo_bars,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False)

    mean_metrics = summary["mean_metrics"]
    print(f"✅ Purged walk-forward salvo em {args.output}")
    print(
        f"   AP={mean_metrics['average_precision']:.4f} | "
        f"AUC={mean_metrics['roc_auc']}"
    )


if __name__ == "__main__":
    main()
