import asyncio
import sys
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

from paths import ENV_PATH

async def main():
    cfg = dotenv_values(ENV_PATH)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    account_id = (cfg.get("METAAPI_ACCOUNT_ID") or "").strip()

    if not token:
        print(
            "ERRO: METAAPI_TOKEN vazio ou em falta no .env.\n"
            "  Correr: ./scripts/maria_exchange.sh env-set METAAPI_TOKEN 'token_da_consola_MetaAPI'\n"
            f"  Ficheiro: {ENV_PATH}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not account_id:
        print(
            "ERRO: METAAPI_ACCOUNT_ID vazio ou em falta no .env.\n"
            "  Correr: ./scripts/maria_exchange.sh env-set METAAPI_ACCOUNT_ID 'id_da_conta'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"Account ID: {account_id[:8]}...")

    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    await account.wait_connected()
    print(f"✅ Conectado: {account.name}")

asyncio.run(main())
