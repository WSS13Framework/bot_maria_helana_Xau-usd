import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_EVENTS_OUTPUT = DATA_DIR / "feedback_events.csv"
DEFAULT_LABELS_FILE = DATA_DIR / "feedback_labels.jsonl"
DEFAULT_TRAINING_OUTPUT = DATA_DIR / "training_feedback.csv"


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payloads: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
    return payloads


def _event_id(source_file: str, event: dict[str, Any]) -> str:
    key_parts = [
        source_file,
        str(event.get("timestamp") or ""),
        str(event.get("event") or ""),
        str(event.get("account_id") or ""),
        str(event.get("symbol") or ""),
        str(event.get("side") or ""),
        str(event.get("position_id") or ""),
    ]
    raw_key = "|".join(key_parts)
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()


def _event_to_row(source_file: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(payload.get("event") or "")
    if not event_type:
        return None

    ts = pd.to_datetime(payload.get("timestamp"), utc=True, errors="coerce")
    event_timestamp = ts.isoformat() if pd.notna(ts) else None
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}

    row = {
        "event_id": _event_id(source_file, payload),
        "source_file": source_file,
        "event_type": event_type,
        "timestamp": event_timestamp,
        "account_id": payload.get("account_id"),
        "account_name": payload.get("account_name"),
        "account_kind": payload.get("account_kind"),
        "symbol": payload.get("symbol"),
        "side": payload.get("side"),
        "position_id": payload.get("position_id"),
        "volume": _safe_float(payload.get("volume")),
        "entry_price": _safe_float(payload.get("entry_price")),
        "stop_loss": _safe_float(payload.get("stop_loss")),
        "take_profit": _safe_float(payload.get("take_profit")),
        "profit": _safe_float(payload.get("profit")),
        "p_long": _safe_float(payload.get("p_long")),
        "p_short": _safe_float(payload.get("p_short")),
        "threshold": _safe_float(payload.get("threshold")),
        "edge_margin": _safe_float(payload.get("edge_margin")),
        "feature_time": payload.get("feature_time"),
        "dry_run": bool(payload.get("dry_run")) if "dry_run" in payload else None,
        "result_string_code": result.get("stringCode"),
        "result_numeric_code": result.get("numericCode"),
        "result_order_id": result.get("orderId"),
        "result_position_id": result.get("positionId"),
        "raw_event": json.dumps(payload, ensure_ascii=False, default=str),
    }

    if event_type == "no_trade_signal":
        row["execution_status"] = "no_trade"
    elif event_type == "order_executed":
        string_code = str(result.get("stringCode") or "")
        row["execution_status"] = "executed" if "DONE" in string_code else "execution_unknown"
    elif event_type == "order_plan":
        row["execution_status"] = "planned"
    elif event_type == "position_modified":
        row["execution_status"] = "position_modified"
    elif event_type == "position_status":
        row["execution_status"] = "position_status"
    else:
        row["execution_status"] = "other"
    return row


def discover_log_files(data_dir: Path) -> list[Path]:
    known = sorted(data_dir.glob("*_log.jsonl"))
    return [path for path in known if path.is_file()]


def sync_events(data_dir: Path, output_csv: Path) -> dict[str, int]:
    log_files = discover_log_files(data_dir)
    rows: list[dict[str, Any]] = []
    for log_file in log_files:
        events = _parse_jsonl(log_file)
        for event in events:
            row = _event_to_row(log_file.name, event)
            if row:
                rows.append(row)

    if not rows:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame().to_csv(output_csv, index=False)
        return {"log_files": len(log_files), "new_rows": 0, "total_rows": 0}

    frame = pd.DataFrame(rows).drop_duplicates(subset=["event_id"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.sort_values("timestamp").reset_index(drop=True)

    if output_csv.exists():
        existing = pd.read_csv(output_csv)
        if not existing.empty and "event_id" in existing.columns:
            frame = pd.concat([existing, frame], ignore_index=True)
            frame = frame.drop_duplicates(subset=["event_id"]).reset_index(drop=True)
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
            frame = frame.sort_values("timestamp").reset_index(drop=True)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_csv, index=False)
    return {"log_files": len(log_files), "new_rows": len(rows), "total_rows": len(frame)}


def append_label(
    labels_file: Path,
    event_id: str,
    label: str,
    operator: str,
    note: str,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": event_id,
        "label": label,
        "operator": operator,
        "note": note,
    }
    labels_file.parent.mkdir(parents=True, exist_ok=True)
    with labels_file.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_training_feedback(events_csv: Path, labels_file: Path, output_csv: Path) -> dict[str, Any]:
    if not events_csv.exists():
        raise ValueError(f"Arquivo de eventos não encontrado: {events_csv}")
    events = pd.read_csv(events_csv)
    if events.empty:
        output_csv.parent.mkdir(parents=True, exist_ok=True)
        events.to_csv(output_csv, index=False)
        return {"rows": 0, "labeled_rows": 0}

    labels_payload = _parse_jsonl(labels_file)
    labels = pd.DataFrame(labels_payload) if labels_payload else pd.DataFrame(columns=["event_id", "label", "operator", "note", "timestamp"])
    if not labels.empty:
        labels["timestamp"] = pd.to_datetime(labels["timestamp"], utc=True, errors="coerce")
        labels = labels.sort_values("timestamp").drop_duplicates(subset=["event_id"], keep="last")
        labels = labels.rename(columns={"timestamp": "label_timestamp"})

    merged = events.merge(labels[["event_id", "label", "operator", "note", "label_timestamp"]], on="event_id", how="left")
    merged["is_actionable_event"] = merged["event_type"].isin(["order_executed", "no_trade_signal"])
    merged["has_label"] = merged["label"].notna()
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], utc=True, errors="coerce")
    merged = merged.sort_values("timestamp").reset_index(drop=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_csv, index=False)
    return {"rows": int(len(merged)), "labeled_rows": int(merged["has_label"].sum())}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Logger de feedback operacional para retraining institucional.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--events-output", type=Path, default=DEFAULT_EVENTS_OUTPUT)
    parser.add_argument("--labels-file", type=Path, default=DEFAULT_LABELS_FILE)
    parser.add_argument("--training-output", type=Path, default=DEFAULT_TRAINING_OUTPUT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("sync", help="Sincroniza eventos de logs para CSV normalizado.")

    label_parser = subparsers.add_parser("label", help="Adiciona rótulo manual para um evento.")
    label_parser.add_argument("--event-id", type=str, required=True)
    label_parser.add_argument("--label", type=str, required=True)
    label_parser.add_argument("--operator", type=str, default="human")
    label_parser.add_argument("--note", type=str, default="")

    subparsers.add_parser("build", help="Constrói dataset de feedback para retreinamento.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "sync":
        result = sync_events(args.data_dir, args.events_output)
        print("✅ Feedback events sincronizados.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.command == "label":
        append_label(
            labels_file=args.labels_file,
            event_id=args.event_id,
            label=args.label,
            operator=args.operator,
            note=args.note,
        )
        print("✅ Label registrado.")
        return

    if args.command == "build":
        result = build_training_feedback(
            events_csv=args.events_output,
            labels_file=args.labels_file,
            output_csv=args.training_output,
        )
        print("✅ Training feedback gerado.")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
