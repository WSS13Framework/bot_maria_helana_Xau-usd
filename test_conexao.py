import asyncio
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


async def main():
    cfg = dotenv_values(ENV_PATH)
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()
    if not token or token == "seu_token_aqui":
        raise RuntimeError(f"METAAPI_TOKEN ausente/invalido em {ENV_PATH}")
    if not account_id or account_id == "seu_account_id_aqui":
        raise RuntimeError(f"METAAPI_ACCOUNT_ID ausente/invalido em {ENV_PATH}")

    print(f"Account ID: {account_id[:8]}...")
    
    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    await account.wait_connected()
    print(f"✅ Conectado: {account.name}")

asyncio.run(main())
