import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

BATCH_LIMIT = 200
SLEEP_BETWEEN_BATCHES_SECONDS = 0.3
OUTPUT_DIR = Path("/root/maria-helena/data")
SYMBOL = "XAUUSD"


@dataclass(frozen=True)
class TimeframeCollectionConfig:
    timeframe: str
    target_candles: int
    output_filename: str


TIMEFRAME_CONFIGS = (
    TimeframeCollectionConfig(timeframe="5m", target_candles=10_000, output_filename="xauusd_m5.json"),
    TimeframeCollectionConfig(timeframe="1h", target_candles=5_000, output_filename="xauusd_h1.json"),
    TimeframeCollectionConfig(timeframe="1d", target_candles=2_000, output_filename="xauusd_d1.json"),
)


def _serialize_candle(candle: dict) -> dict:
    return {
        "time": candle["time"].isoformat(),
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["tickVolume"],
    }


def _dedupe_and_sort(raw_candles: list[dict]) -> list[dict]:
    deduped_by_time = {candle["time"]: candle for candle in raw_candles}
    sorted_candles = sorted(deduped_by_time.values(), key=lambda c: c["time"])
    return [_serialize_candle(candle) for candle in sorted_candles]


async def collect_timeframe_candles(
    account,
    symbol: str,
    timeframe: str,
    target_candles: int,
) -> list[dict]:
    candles: list[dict] = []
    end_time = datetime.now(timezone.utc)

    print(f"\nColetando {symbol} {timeframe} (meta: {target_candles})...")
    while len(candles) < target_candles:
        batch = await account.get_historical_candles(
            symbol,
            timeframe,
            start_time=end_time,
            limit=BATCH_LIMIT,
        )
        if not batch:
            print("  Sem novos candles retornados pela corretora.")
            break

        candles.extend(batch)
        oldest = min(batch, key=lambda candle: candle["time"])["time"]
        end_time = oldest - timedelta(milliseconds=1)
        print(
            f"  +{len(batch)} | bruto={len(candles)} | "
            f"até={oldest.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        await asyncio.sleep(SLEEP_BETWEEN_BATCHES_SECONDS)

    normalized = _dedupe_and_sort(candles)
    if len(normalized) > target_candles:
        normalized = normalized[-target_candles:]
    return normalized


def save_candles(filepath: Path, candles: list[dict]) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as output_file:
        json.dump(candles, output_file)


async def main():
    cfg = dotenv_values("/root/maria-helena/.env")
    api = MetaApi(cfg["METAAPI_TOKEN"].strip())
    account = await api.metatrader_account_api.get_account(cfg["METAAPI_ACCOUNT_ID"].strip())
    await account.wait_connected()

    summary: dict[str, dict] = {}
    for timeframe_config in TIMEFRAME_CONFIGS:
        candles = await collect_timeframe_candles(
            account=account,
            symbol=SYMBOL,
            timeframe=timeframe_config.timeframe,
            target_candles=timeframe_config.target_candles,
        )
        output_path = OUTPUT_DIR / timeframe_config.output_filename
        save_candles(output_path, candles)

        timeframe_key = timeframe_config.timeframe.upper()
        summary[timeframe_key] = {
            "count": len(candles),
            "output": str(output_path),
            "start": candles[0]["time"] if candles else None,
            "end": candles[-1]["time"] if candles else None,
        }
        print(f"✅ {timeframe_key}: {len(candles)} candles salvos em {output_path}")

    summary_path = OUTPUT_DIR / "xauusd_candles_summary.json"
    save_candles(summary_path, [summary])
    print("\nResumo da coleta:")
    for timeframe, values in summary.items():
        print(f"  {timeframe}: {values['count']} | {values['start']} -> {values['end']}")
    print(f"\n✅ Resumo salvo em {summary_path}")


asyncio.run(main())
