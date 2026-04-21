import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
DATA_PATH = ROOT / "data" / "xauusd_m5.json"


def load_required_env() -> tuple[str, str]:
    cfg = dotenv_values(ENV_PATH)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    account_id = (cfg.get("METAAPI_ACCOUNT_ID") or "").strip()
    if not token or token == "seu_token_aqui":
        raise RuntimeError(f"METAAPI_TOKEN ausente/invalido em {ENV_PATH}")
    if not account_id or account_id == "seu_account_id_aqui":
        raise RuntimeError(f"METAAPI_ACCOUNT_ID ausente/invalido em {ENV_PATH}")
    return token, account_id


async def main():
    token, account_id = load_required_env()
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

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(dados, f)

    print(f"\n✅ Salvo: {len(dados)} candles")
    print(f"Período: {dados[0]['time']} → {dados[-1]['time']}")

asyncio.run(main())
