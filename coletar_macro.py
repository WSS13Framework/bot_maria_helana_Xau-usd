import json
from datetime import datetime, timezone
from pathlib import Path

import requests

OUTPUT_DIR = Path("/root/maria-helena/data")
DEFAULT_TIMEOUT = 20


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


def fetch_yahoo_chart(symbol: str) -> dict:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "5d", "interval": "1d"}
    response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()

    payload = response.json()
    result = payload.get("chart", {}).get("result", [])
    if not result:
        return {"source": "Yahoo", "symbol": symbol, "value": None, "time": None}

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
        "us10y_fred": fetch_fred_series("DGS10", fred_api_key),
        "dxy_fred_proxy": fetch_fred_series("DTWEXBGS", fred_api_key),
    }
    return snapshot


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = collect_macro_snapshot()
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
