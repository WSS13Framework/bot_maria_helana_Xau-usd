import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import dotenv_values

OUTPUT_DIR = Path("/root/maria-helena/data")
DEFAULT_TIMEOUT = 20
DEFAULT_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_fred_series(series_id: str, api_key: str | None = None) -> dict:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 1,
    }
    if api_key:
        params["api_key"] = api_key

    response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    observations = payload.get("observations", [])
    latest = observations[0] if observations else {}

    return {
        "source": "FRED",
        "series_id": series_id,
        "date": latest.get("date"),
        "value": _to_float(latest.get("value")),
        "raw_value": latest.get("value"),
    }


def fetch_fred_series_safe(series_id: str, api_key: str | None = None) -> dict:
    try:
        return fetch_fred_series(series_id, api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        return {
            "source": "FRED",
            "series_id": series_id,
            "date": None,
            "value": None,
            "raw_value": None,
            "error": str(exc),
        }


def fetch_yahoo_chart(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "5d", "interval": "1d"}
    last_exc: Exception | None = None
    payload: dict | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                url,
                params=params,
                headers=DEFAULT_YAHOO_HEADERS,
                timeout=DEFAULT_TIMEOUT,
            )
            if response.status_code == 429:
                time.sleep(2**attempt)
                continue
            response.raise_for_status()
            candidate = response.json()
            if not isinstance(candidate, dict):
                raise ValueError("Yahoo payload inválido (não é objeto JSON).")
            if "chart" not in candidate:
                preview = (response.text or "")[:220].replace("\n", " ").strip()
                raise ValueError(f"Yahoo payload sem campo chart. Preview: {preview}")
            payload = candidate
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            time.sleep(2**attempt)
            payload = None
    if payload is None:
        return {
            "source": "Yahoo",
            "symbol": symbol,
            "time": None,
            "value": None,
            "error": str(last_exc) if last_exc else "unknown_error",
        }

    result = payload.get("chart", {}).get("result", [])
    if not result:
        chart_error = payload.get("chart", {}).get("error")
        return {
            "source": "Yahoo",
            "symbol": symbol,
            "value": None,
            "time": None,
            "error": str(chart_error) if chart_error else None,
        }

    first = result[0]
    timestamps = first.get("timestamp", [])
    quote = first.get("indicators", {}).get("quote", [{}])[0]
    closes = quote.get("close", [])

    value = None
    time_iso = None
    if timestamps and closes:
        for timestamp, close in zip(reversed(timestamps), reversed(closes)):
            if close is None:
                continue
            value = float(close)
            time_iso = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
            break

    return {
        "source": "Yahoo",
        "symbol": symbol,
        "time": time_iso,
        "value": value,
    }


def collect_macro_snapshot(fred_api_key: str | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "collected_at": now,
        "dxy_yahoo": fetch_yahoo_chart("DX-Y.NYB"),
        "vix_yahoo": fetch_yahoo_chart("^VIX"),
        "us10y_fred": fetch_fred_series_safe("DGS10", fred_api_key),
        "dxy_fred_proxy": fetch_fred_series_safe("DTWEXBGS", fred_api_key),
    }
    return snapshot


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    env_values = dotenv_values("/root/maria-helena/.env")
    fred_key = (env_values.get("FRED_API_KEY") or "").strip() or None
    snapshot = collect_macro_snapshot(fred_api_key=fred_key)
    output_file = OUTPUT_DIR / "macro_snapshot.json"
    with output_file.open("w", encoding="utf-8") as fp:
        json.dump(snapshot, fp, ensure_ascii=False)
    print(f"✅ Macro snapshot salvo em {output_file}")
    print(
        "Valores: "
        f"DXY(Yahoo)={snapshot['dxy_yahoo']['value']} | "
        f"VIX={snapshot['vix_yahoo']['value']} | "
        f"US10Y={snapshot['us10y_fred']['value']}"
    )


if __name__ == "__main__":
    main()
