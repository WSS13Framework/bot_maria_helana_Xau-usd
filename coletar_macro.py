import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
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


def _extract_value_time(record: Any) -> tuple[float | None, str | None]:
    if isinstance(record, (int, float)):
        return float(record), None
    if isinstance(record, str):
        return _to_float(record), None
    if not isinstance(record, dict):
        return None, None
    value = None
    for key in ("value", "price", "last", "close", "mid"):
        if key in record:
            value = _to_float(record.get(key))
            if value is not None:
                break
    raw_time = None
    for key in ("time", "timestamp", "datetime", "date"):
        if key in record:
            raw_time = record.get(key)
            break
    ts = pd.to_datetime(raw_time, utc=True, errors="coerce")
    time_iso = ts.isoformat() if pd.notna(ts) else None
    return value, time_iso


def _iter_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "items", "quotes"):
            section = payload.get(key)
            if isinstance(section, list):
                return [item for item in section if isinstance(item, dict)]
    return []


def _find_symbol_record(payload: Any, symbol: str) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        for direct_key in (symbol, symbol.lower(), symbol.upper()):
            if direct_key in payload:
                candidate = payload.get(direct_key)
                if isinstance(candidate, dict):
                    return candidate
                return {"value": candidate}

    records = _iter_records(payload)
    symbol_norm = symbol.strip().upper()
    for item in records:
        item_symbol = (
            str(item.get("symbol") or item.get("ticker") or item.get("code") or item.get("id") or "")
            .strip()
            .upper()
        )
        if item_symbol == symbol_norm:
            return item
    return None


def fetch_premium_macro(cfg: dict[str, Any]) -> dict[str, Any]:
    enabled = str(cfg.get("PREMIUM_MACRO_ENABLED") or "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    url = str(cfg.get("PREMIUM_MACRO_URL") or "").strip()
    api_key = str(cfg.get("PREMIUM_MACRO_API_KEY") or "").strip()
    api_key_header = str(cfg.get("PREMIUM_MACRO_API_KEY_HEADER") or "X-API-Key").strip()
    api_key_param = str(cfg.get("PREMIUM_MACRO_API_KEY_PARAM") or "").strip()
    timeout = int(_to_float(cfg.get("PREMIUM_MACRO_TIMEOUT")) or DEFAULT_TIMEOUT)

    output = {
        "enabled": enabled,
        "provider": str(cfg.get("PREMIUM_MACRO_PROVIDER") or "custom_http"),
        "dxy_premium": {"source": "premium", "symbol": str(cfg.get("PREMIUM_MACRO_DXY_SYMBOL") or "DXY"), "time": None, "value": None},
        "vix_premium": {"source": "premium", "symbol": str(cfg.get("PREMIUM_MACRO_VIX_SYMBOL") or "VIX"), "time": None, "value": None},
        "us10y_premium": {"source": "premium", "symbol": str(cfg.get("PREMIUM_MACRO_US10Y_SYMBOL") or "US10Y"), "time": None, "value": None},
        "error": "",
    }
    if not enabled:
        output["error"] = "premium_macro_disabled"
        return output
    if not url:
        output["error"] = "premium_macro_url_missing"
        return output

    headers = {"Accept": "application/json", **DEFAULT_YAHOO_HEADERS}
    if api_key:
        headers[api_key_header or "X-API-Key"] = api_key
    params: dict[str, Any] = {}
    if api_key and api_key_param:
        params[api_key_param] = api_key

    try:
        response = requests.get(url, headers=headers, params=params, timeout=max(5, timeout))
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        output["error"] = str(exc)
        return output

    symbol_config = {
        "dxy_premium": str(cfg.get("PREMIUM_MACRO_DXY_SYMBOL") or "DXY"),
        "vix_premium": str(cfg.get("PREMIUM_MACRO_VIX_SYMBOL") or "VIX"),
        "us10y_premium": str(cfg.get("PREMIUM_MACRO_US10Y_SYMBOL") or "US10Y"),
    }
    for field, symbol in symbol_config.items():
        record = _find_symbol_record(payload, symbol=symbol)
        value, time_iso = _extract_value_time(record)
        if value is not None:
            output[field]["value"] = value
            output[field]["time"] = time_iso
        else:
            output[field]["error"] = f"symbol_not_found_or_invalid:{symbol}"

    return output


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
        "time": pd.to_datetime(latest.get("date"), utc=True, errors="coerce").isoformat()
        if latest.get("date")
        else None,
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
            "time": None,
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


def _pick_primary(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    if _to_float(preferred.get("value")) is not None:
        return preferred
    return fallback


def collect_macro_snapshot(fred_api_key: str | None = None, env_cfg: dict[str, Any] | None = None) -> dict:
    cfg = env_cfg or {}
    now = datetime.now(timezone.utc).isoformat()
    dxy_yahoo = fetch_yahoo_chart("DX-Y.NYB")
    vix_yahoo = fetch_yahoo_chart("^VIX")
    us10y_fred = fetch_fred_series_safe("DGS10", fred_api_key)
    dxy_fred_proxy = fetch_fred_series_safe("DTWEXBGS", fred_api_key)
    premium = fetch_premium_macro(cfg)

    dxy_selected = _pick_primary(premium.get("dxy_premium", {}), dxy_yahoo)
    vix_selected = _pick_primary(premium.get("vix_premium", {}), vix_yahoo)
    us10y_selected = _pick_primary(premium.get("us10y_premium", {}), us10y_fred)

    snapshot = {
        "collected_at": now,
        "premium_macro_status": {
            "enabled": premium.get("enabled"),
            "provider": premium.get("provider"),
            "error": premium.get("error"),
        },
        "dxy_selected": dxy_selected,
        "vix_selected": vix_selected,
        "us10y_selected": us10y_selected,
        "dxy_premium": premium.get("dxy_premium"),
        "vix_premium": premium.get("vix_premium"),
        "us10y_premium": premium.get("us10y_premium"),
        "dxy_yahoo": dxy_yahoo,
        "vix_yahoo": vix_yahoo,
        "us10y_fred": us10y_fred,
        "dxy_fred_proxy": dxy_fred_proxy,
    }
    return snapshot


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    env_values = dotenv_values("/root/maria-helena/.env")
    fred_key = (env_values.get("FRED_API_KEY") or "").strip() or None
    snapshot = collect_macro_snapshot(fred_api_key=fred_key, env_cfg=env_values)
    output_file = OUTPUT_DIR / "macro_snapshot.json"
    with output_file.open("w", encoding="utf-8") as fp:
        json.dump(snapshot, fp, ensure_ascii=False)
    print(f"✅ Macro snapshot salvo em {output_file}")
    print(
        "Valores selecionados: "
        f"DXY={snapshot['dxy_selected']['value']} | "
        f"VIX={snapshot['vix_selected']['value']} | "
        f"US10Y={snapshot['us10y_selected']['value']}"
    )


if __name__ == "__main__":
    main()
