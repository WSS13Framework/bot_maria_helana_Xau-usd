import asyncio
from dotenv import dotenv_values


async def main() -> None:
    from metaapi_cloud_sdk import MetaApi

    cfg = dotenv_values("/root/maria-helena/.env")
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()

    print(f"Account ID: {account_id[:8]}...")
    
    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    await account.wait_connected()
    print(f"✅ Conectado: {account.name}")


if __name__ == "__main__":
    asyncio.run(main())
