import asyncio
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi


def load_env():
    local_env = Path(__file__).resolve().parent / ".env"
    if local_env.exists():
        return dotenv_values(local_env)
    return dotenv_values("/root/maria-helena/.env")


async def main():
    cfg = load_env()
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()
    if not token or not account_id:
        raise RuntimeError("Missing METAAPI_TOKEN or METAAPI_ACCOUNT_ID in .env")

    print(f"Account ID: {account_id[:8]}...")
    
    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    await account.wait_connected()
    print(f"✅ Conectado: {account.name}")

asyncio.run(main())
