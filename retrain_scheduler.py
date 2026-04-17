import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_STATE_PATH = DATA_DIR / "retrain_state.json"
DEFAULT_FEEDBACK_PATH = DATA_DIR / "feedback_events.jsonl"
DEFAULT_OUTPUT_PATH = DATA_DIR / "retrain_scheduler_result.json"


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False)


def _count_feedback(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            if line.strip():
                count += 1
    return count


def _hours_since(ts_iso: str | None) -> float | None:
    if not ts_iso:
        return None
    ts = pd.to_datetime(ts_iso, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    now = datetime.now(timezone.utc)
    delta = now - ts.to_pydatetime()
    return delta.total_seconds() / 3600.0


def _run_pipeline(threshold: float, spread_bps: float, slippage_bps: float) -> list[dict[str, Any]]:
    commands = [
        ["python3", "build_dataset.py"],
        ["python3", "label_triple_barrier.py"],
        ["python3", "train_baseline.py", "--decision-threshold", str(threshold)],
        [
            "python3",
            "backtest_walkforward.py",
            "--confidence-threshold",
            str(threshold),
            "--spread-bps",
            str(spread_bps),
            "--slippage-bps",
            str(slippage_bps),
        ],
        ["python3", "risk_execution.py"],
        ["python3", "purged_walkforward.py", "--embargo-bars", "48"],
        [
            "python3",
            "holdout_evaluation.py",
            "--decision-threshold",
            str(threshold),
            "--spread-bps",
            str(spread_bps),
            "--slippage-bps",
            str(slippage_bps),
        ],
        ["python3", "gate_report.py"],
    ]
    reports: list[dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(command, capture_output=True, text=True)
        reports.append(
            {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "stdout": completed.stdout[-5000:],
                "stderr": completed.stderr[-5000:],
            }
        )
        if completed.returncode != 0:
            break
    return reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retrain batch scheduler com gatilhos institucionais (feedback + tempo)."
    )
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--feedback-path", type=Path, default=DEFAULT_FEEDBACK_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--decision-threshold", type=float, default=0.65)
    parser.add_argument("--spread-bps", type=float, default=5.0)
    parser.add_argument("--slippage-bps", type=float, default=5.0)
    parser.add_argument("--min-new-feedback", type=int, default=25)
    parser.add_argument("--min-hours-between", type=float, default=6.0)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = _read_state(args.state_path)
    total_feedback = _count_feedback(args.feedback_path)
    last_feedback_count = int(state.get("last_feedback_count", 0))
    new_feedback = max(0, total_feedback - last_feedback_count)

    last_retrain_at = state.get("last_retrain_at")
    elapsed_hours = _hours_since(last_retrain_at)
    enough_feedback = new_feedback >= args.min_new_feedback
    enough_time = elapsed_hours is None or elapsed_hours >= args.min_hours_between
    should_retrain = args.force or (enough_feedback and enough_time)

    result: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "feedback_total": total_feedback,
        "feedback_new": new_feedback,
        "last_retrain_at": last_retrain_at,
        "hours_since_last_retrain": elapsed_hours,
        "should_retrain": should_retrain,
        "reason": "force" if args.force else "feedback+time gate",
        "runs": [],
    }

    if should_retrain:
        reports = _run_pipeline(
            threshold=args.decision_threshold,
            spread_bps=args.spread_bps,
            slippage_bps=args.slippage_bps,
        )
        result["runs"] = reports
        success = all(item["returncode"] == 0 for item in reports)
        result["retrain_success"] = success
        if success:
            state["last_retrain_at"] = datetime.now(timezone.utc).isoformat()
            state["last_feedback_count"] = total_feedback
            state["last_result"] = "success"
        else:
            state["last_result"] = "failed"
    else:
        result["retrain_success"] = None
        result["message"] = "Retrain gate not met. Skipping batch retrain."

    _write_state(args.state_path, state)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fp:
        json.dump(result, fp, ensure_ascii=False)

    print(f"✅ Retrain scheduler resultado salvo em {args.output}")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
