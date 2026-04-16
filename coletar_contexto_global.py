import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_TIMEOUT = 20
DEFAULT_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

GLOBAL_INDEX_SYMBOLS = {
    "us_sp500": "^GSPC",
    "us_nasdaq": "^IXIC",
    "us_dow": "^DJI",
    "eu_dax": "^GDAXI",
    "eu_ftse": "^FTSE",
    "eu_stoxx50": "^STOXX50E",
    "asia_nikkei": "^N225",
    "asia_hsi": "^HSI",
    "asia_shanghai": "000001.SS",
    "asia_kospi": "^KS11",
}

CRITICAL_MINERAL_SYMBOLS = {
    "gold_fut": "GC=F",
    "silver_fut": "SI=F",
    "copper_fut": "HG=F",
    "platinum_fut": "PL=F",
    "palladium_fut": "PA=F",
    "lithium_etf": "LIT",
    "uranium_etf": "URA",
    "rareearth_etf": "REMX",
}

FRED_STRUCTURAL_SERIES = {
    "us_industrial_production": "INDPRO",
    "us_mfg_production": "IPMAN",
    "us_goods_exports": "BOPXGS",
    "us_goods_imports": "BOPMGS",
    "us_capacity_util_mfg": "MCUMFN",
    "us_10y_breakeven": "T10YIE",
}


def _fetch_yahoo_daily(symbol: str, range_period: str = "5y") -> pd.DataFrame:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": range_period, "interval": "1d"}
    response = None
    for attempt in range(4):
        response = requests.get(
            url,
            params=params,
            headers=DEFAULT_YAHOO_HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        if response.status_code != 429:
            break
        sleep_seconds = 2**attempt
        time.sleep(sleep_seconds)
    if response is None:
        return pd.DataFrame(columns=["time", "close"])
    response.raise_for_status()
    payload = response.json()
    result = payload.get("chart", {}).get("result", [])
    if not result:
        return pd.DataFrame(columns=["time", "close"])

    first = result[0]
    timestamps = first.get("timestamp", [])
    close_values = first.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    rows = []
    for ts, close in zip(timestamps, close_values):
        if close is None:
            continue
        rows.append(
            {
                "time": datetime.fromtimestamp(ts, tz=timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
                "close": float(close),
            }
        )
    if not rows:
        return pd.DataFrame(columns=["time", "close"])
    return pd.DataFrame(rows).sort_values("time").drop_duplicates("time")


def _build_market_context_frame(symbol_map: dict[str, str], yahoo_sleep_seconds: float) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for key, symbol in symbol_map.items():
        try:
            frame = _fetch_yahoo_daily(symbol)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Falha ao coletar {key} ({symbol}): {exc}")
            if yahoo_sleep_seconds > 0:
                time.sleep(yahoo_sleep_seconds)
            continue

        if frame.empty:
            continue

        close_col = f"{key}_close"
        ret1_col = f"{key}_ret1d"
        ret5_col = f"{key}_ret5d"
        vol20_col = f"{key}_vol20d"
        enriched = frame.rename(columns={"close": close_col})
        enriched[ret1_col] = enriched[close_col].pct_change(1)
        enriched[ret5_col] = enriched[close_col].pct_change(5)
        enriched[vol20_col] = enriched[ret1_col].rolling(20, min_periods=10).std()

        if merged is None:
            merged = enriched
        else:
            merged = merged.merge(enriched, on="time", how="outer")
        if yahoo_sleep_seconds > 0:
            time.sleep(yahoo_sleep_seconds)

    if merged is None:
        return pd.DataFrame(columns=["time"])
    return merged.sort_values("time").reset_index(drop=True)


def _fetch_fred_series(series_id: str, api_key: str | None = None) -> pd.DataFrame:
    url = "https://api.stlouisfed.org/fred/series/observations"
    if not api_key:
        raise ValueError(
            "FRED API key ausente. Defina FRED_API_KEY no .env ou use --fred-api-key."
        )
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "limit": 100000,
    }

    response = requests.get(url, params=params, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    observations = response.json().get("observations", [])
    rows = []
    for obs in observations:
        value = obs.get("value")
        if value in (None, "."):
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        ts = pd.to_datetime(obs.get("date"), utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        rows.append({"time": ts, "value": numeric_value})

    if not rows:
        return pd.DataFrame(columns=["time", "value"])
    return pd.DataFrame(rows).sort_values("time").drop_duplicates("time")


def _build_structural_frame(api_key: str | None = None) -> pd.DataFrame:
    merged: pd.DataFrame | None = None
    for key, series_id in FRED_STRUCTURAL_SERIES.items():
        try:
            frame = _fetch_fred_series(series_id, api_key=api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"⚠️ Falha FRED {key} ({series_id}): {exc}")
            continue
        if frame.empty:
            continue
        renamed = frame.rename(columns={"value": key})
        if merged is None:
            merged = renamed
        else:
            merged = merged.merge(renamed, on="time", how="outer")

    if merged is None:
        return pd.DataFrame(columns=["time"])
    merged = merged.sort_values("time").reset_index(drop=True)
    merged = merged.ffill()
    return merged


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Coleta contexto global (indices, minerais criticos, estrutura produtiva)."
    )
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--fred-api-key", type=str, default="")
    parser.add_argument("--yahoo-sleep-seconds", type=float, default=0.4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    market_symbols = {**GLOBAL_INDEX_SYMBOLS, **CRITICAL_MINERAL_SYMBOLS}
    market_context = _build_market_context_frame(
        market_symbols, yahoo_sleep_seconds=max(0.0, args.yahoo_sleep_seconds)
    )

    fred_key = args.fred_api_key.strip()
    if not fred_key:
        env_values = dotenv_values("/root/maria-helena/.env")
        fred_key = (env_values.get("FRED_API_KEY") or "").strip()
    structural_context = _build_structural_frame(api_key=fred_key or None)

    market_output = args.output_dir / "global_context_daily.csv"
    structural_output = args.output_dir / "global_structural_fred.csv"
    summary_output = args.output_dir / "global_context_summary.json"

    market_context.to_csv(market_output, index=False)
    structural_context.to_csv(structural_output, index=False)

    market_start = None
    market_end = None
    structural_start = None
    structural_end = None
    if len(market_context):
        market_start = market_context["time"].iloc[0]
        market_end = market_context["time"].iloc[-1]
    if len(structural_context):
        structural_start = structural_context["time"].iloc[0]
        structural_end = structural_context["time"].iloc[-1]

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_rows": int(len(market_context)),
        "structural_rows": int(len(structural_context)),
        "market_start": market_start.isoformat() if market_start is not None else None,
        "market_end": market_end.isoformat() if market_end is not None else None,
        "structural_start": structural_start.isoformat() if structural_start is not None else None,
        "structural_end": structural_end.isoformat() if structural_end is not None else None,
        "tracked_market_series": sorted(list(market_symbols.keys())),
        "tracked_structural_series": sorted(list(FRED_STRUCTURAL_SERIES.keys())),
    }
    with summary_output.open("w", encoding="utf-8") as fp:
        json.dump(summary, fp, ensure_ascii=False)

    print(f"✅ Contexto global salvo em {market_output}")
    print(f"✅ Estrutura produtiva (FRED) salva em {structural_output}")
    print(f"✅ Resumo salvo em {summary_output}")


if __name__ == "__main__":
    main()
