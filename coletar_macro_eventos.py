import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_OUTPUT = DATA_DIR / "macro_events_snapshot.json"
DEFAULT_TIMEOUT = 20

IMPORTANT_EVENTS = {
    "CPI": "cpi",
    "NFP": "nfp",
    "FOMC": "fomc",
}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text or text.lower() in {"none", "nan", "null"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _standard_empty_event(label: str, reason: str) -> dict[str, Any]:
    return {
        "label": label,
        "event_time": None,
        "actual": None,
        "forecast": None,
        "previous": None,
        "surprise": None,
        "surprise_abs": None,
        "impact": None,
        "country": None,
        "source": "premium_calendar",
        "error": reason,
    }


def _extract_event_value(item: dict[str, Any], candidates: list[str]) -> Any:
    for key in candidates:
        if key in item and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _normalize_event(item: dict[str, Any], label: str) -> dict[str, Any]:
    event_time_raw = _extract_event_value(item, ["date", "eventTime", "datetime", "time"])
    event_time = datetime.now(timezone.utc).isoformat()
    if event_time_raw is not None:
        parsed = datetime.fromisoformat(str(event_time_raw).replace("Z", "+00:00"))
        event_time = parsed.astimezone(timezone.utc).isoformat()

    actual = _to_float(_extract_event_value(item, ["actual", "actualValue"]))
    forecast = _to_float(_extract_event_value(item, ["forecast", "consensus"]))
    previous = _to_float(_extract_event_value(item, ["previous", "prior"]))
    surprise = actual - forecast if (actual is not None and forecast is not None) else None
    surprise_abs = abs(surprise) if surprise is not None else None

    return {
        "label": label,
        "event_time": event_time,
        "actual": actual,
        "forecast": forecast,
        "previous": previous,
        "surprise": surprise,
        "surprise_abs": surprise_abs,
        "impact": str(_extract_event_value(item, ["importance", "impact"]) or ""),
        "country": str(_extract_event_value(item, ["country", "region"]) or ""),
        "source": "premium_calendar",
    }


def _fetch_premium_calendar_events(
    api_url: str,
    api_key: str,
    timeout: int,
) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "MariaHelena/1.0",
    }
    response = requests.get(api_url, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()

    if isinstance(payload, dict):
        for key in ("events", "data", "results", "items"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return candidate
    if isinstance(payload, list):
        return payload
    raise ValueError("Payload de eventos macro inválido.")


def collect_macro_events_snapshot(
    api_url: str,
    api_key: str,
    timeout: int,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    snapshot: dict[str, Any] = {
        "collected_at": now,
        "provider": "premium_calendar",
        "events": {},
    }
    if not api_url:
        for label in IMPORTANT_EVENTS:
            snapshot["events"][label.lower()] = _standard_empty_event(
                label=label,
                reason="PREMIUM_MACRO_CALENDAR_URL ausente",
            )
        return snapshot
    if not api_key:
        for label in IMPORTANT_EVENTS:
            snapshot["events"][label.lower()] = _standard_empty_event(
                label=label,
                reason="PREMIUM_MACRO_CALENDAR_KEY ausente",
            )
        return snapshot

    try:
        rows = _fetch_premium_calendar_events(api_url=api_url, api_key=api_key, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        for label in IMPORTANT_EVENTS:
            snapshot["events"][label.lower()] = _standard_empty_event(label=label, reason=str(exc))
        return snapshot

    rows_by_label: dict[str, list[dict[str, Any]]] = {name: [] for name in IMPORTANT_EVENTS}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(_extract_event_value(row, ["event", "name", "title"]) or "").upper()
        for label in IMPORTANT_EVENTS:
            if label in title:
                rows_by_label[label].append(row)

    for label, key in IMPORTANT_EVENTS.items():
        candidates = rows_by_label.get(label, [])
        if not candidates:
            snapshot["events"][key] = _standard_empty_event(
                label=label,
                reason="evento não encontrado no payload",
            )
            continue
        latest = candidates[-1]
        try:
            snapshot["events"][key] = _normalize_event(latest, label=label)
        except Exception as exc:  # noqa: BLE001
            snapshot["events"][key] = _standard_empty_event(label=label, reason=str(exc))
    return snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta snapshot premium de eventos macro (CPI/NFP/FOMC) com surprise."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env = dotenv_values("/root/maria-helena/.env")
    api_url = str(env.get("PREMIUM_MACRO_CALENDAR_URL") or "").strip()
    api_key = str(env.get("PREMIUM_MACRO_CALENDAR_KEY") or "").strip()

    snapshot = collect_macro_events_snapshot(
        api_url=api_url,
        api_key=api_key,
        timeout=max(5, int(args.timeout)),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as fp:
        json.dump(snapshot, fp, ensure_ascii=False)

    print(f"✅ Macro events snapshot salvo em {args.output}")
    cpi = snapshot["events"].get("cpi", {})
    nfp = snapshot["events"].get("nfp", {})
    fomc = snapshot["events"].get("fomc", {})
    print(
        "Eventos premium: "
        f"CPI surprise={cpi.get('surprise')} | "
        f"NFP surprise={nfp.get('surprise')} | "
        f"FOMC surprise={fomc.get('surprise')}"
    )


if __name__ == "__main__":
    main()
