#!/usr/bin/env python3
"""Aggregate executor JSONL logs into hourly summary lines (JSONL).

Reads lines from demo_monitor.jsonl (or --input), buckets by UTC hour,
writes one summary record per completed hour to --output.

Usage (extension host):
  source venv/bin/activate
  python3 scripts/summarize_executor_onnx_hourly.py \\
    --input /root/maria-helena/logs/demo_monitor.jsonl \\
    --output /root/maria-helena/logs/executor_onnx_hourly.jsonl
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_ts(obj: dict[str, Any]) -> datetime | None:
    raw = obj.get("ts")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def hour_key(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:00:00+00:00")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("/root/maria-helena/logs/demo_monitor.jsonl"),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("/root/maria-helena/logs/executor_onnx_hourly.jsonl"),
    )
    ap.add_argument(
        "--state",
        type=Path,
        default=Path("/root/maria-helena/logs/executor_onnx_hourly.state.json"),
        help="Tracks last fully summarized UTC hour.",
    )
    args = ap.parse_args()

    if not args.input.exists():
        print(json.dumps({"ok": False, "error": "input_missing", "path": str(args.input)}))
        return

    state: dict[str, Any] = {}
    if args.state.exists():
        try:
            state = json.loads(args.state.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    last_done = state.get("last_summarized_hour")

    # Bucket all lines (file is append-only; for large files use tail -n in cron instead)
    buckets: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "n_predictions": 0,
            "n_signals": 0,
            "n_order_candidates": 0,
            "n_errors": 0,
            "n_alerts": 0,
            "prob_sum": 0.0,
            "prob_min": None,
            "prob_max": None,
        }
    )

    with args.input.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            dt = parse_ts(obj)
            if dt is None:
                continue
            hk = hour_key(dt)
            b = buckets[hk]
            if "probability" in obj and "error" not in obj:
                p = float(obj["probability"])
                b["n_predictions"] += 1
                b["prob_sum"] += p
                b["prob_min"] = p if b["prob_min"] is None else min(b["prob_min"], p)
                b["prob_max"] = p if b["prob_max"] is None else max(b["prob_max"], p)
                if obj.get("signal"):
                    b["n_signals"] += 1
            if obj.get("event") == "order_candidate":
                b["n_order_candidates"] += 1
            if "error" in obj:
                b["n_errors"] += 1
            if "alert" in obj:
                b["n_alerts"] += 1

    if not buckets:
        print(json.dumps({"ok": True, "message": "no_buckets"}))
        return

    # Current UTC hour is incomplete; summarize only strictly past hours
    now_hour = hour_key(datetime.now(timezone.utc))
    completed_hours = sorted(h for h in buckets.keys() if h < now_hour)
    if not completed_hours:
        print(json.dumps({"ok": True, "message": "no_completed_hours_yet", "now_hour": now_hour}))
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)

    wrote = 0
    for hk in completed_hours:
        if last_done and hk <= last_done:
            continue
        b = buckets[hk]
        n = b["n_predictions"]
        summary = {
            "type": "hourly_summary",
            "hour_utc": hk,
            "n_predictions": n,
            "n_signals": b["n_signals"],
            "n_order_candidates": b["n_order_candidates"],
            "n_errors": b["n_errors"],
            "n_alerts": b["n_alerts"],
            "prob_mean": (b["prob_sum"] / n) if n else None,
            "prob_min": b["prob_min"],
            "prob_max": b["prob_max"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        with args.output.open("a", encoding="utf-8") as out:
            out.write(json.dumps(summary, ensure_ascii=True) + "\n")
        state["last_summarized_hour"] = hk
        wrote += 1

    if wrote:
        args.state.parent.mkdir(parents=True, exist_ok=True)
        args.state.write_text(json.dumps(state, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "summaries_written": wrote, "last_summarized_hour": state.get("last_summarized_hour")}))


if __name__ == "__main__":
    main()
