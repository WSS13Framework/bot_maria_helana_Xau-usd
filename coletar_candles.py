import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

async def main():
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"
    if not env_path.exists():
        print(f"⚠️ Arquivo .env não encontrado em {env_path}")
        return

    cfg = dotenv_values(env_path)
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        print("⚠️ METAAPI_TOKEN ou METAAPI_ACCOUNT_ID ausente no .env")
        return

    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(
        account_id
    )
    await account.wait_connected()

    todos = []
    end_time = datetime.now(timezone.utc)

    print("Coletando candles XAUUSD+ M5...")
    for i in range(50):
        batch = await account.get_historical_candles(
            "XAUUSD", "5m",
            start_time=end_time,
            limit=200
        )
        if not batch:
            break
        todos.extend(batch)
        mais_antigo = min(batch, key=lambda c: c['time'])
        end_time = mais_antigo['time']
        print(f"  Batch {i+1}: +{len(batch)} | Total: {len(todos)} | Até: {end_time.strftime('%Y-%m-%d')}")
        await asyncio.sleep(0.3)

    todos.sort(key=lambda c: c['time'])
    dados = [{'time': c['time'].isoformat(), 'open': c['open'],
              'high': c['high'], 'low': c['low'],
              'close': c['close'], 'volume': c['tickVolume']} for c in todos]

    data_dir = project_root / "data"
    data_dir.mkdir(exist_ok=True)
    output_path = data_dir / "xauusd_m5.json"

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(dados, f)

    print(f"\n✅ Salvo: {len(dados)} candles")
    print(f"Período: {dados[0]['time']} → {dados[-1]['time']}")

asyncio.run(main())
