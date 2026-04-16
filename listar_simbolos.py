import asyncio
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

async def main():
    cfg = dotenv_values("/root/maria-helena/.env")
    api = MetaApi(cfg["METAAPI_TOKEN"].strip())
    account = await api.metatrader_account_api.get_account(
        cfg["METAAPI_ACCOUNT_ID"].strip()
    )
    await account.wait_connected()
    conn = account.get_rpc_connection()
    await conn.connect()
    await conn.wait_synchronized()

    symbols = await conn.get_symbols()
    gold = [s for s in symbols if "XAU" in s.upper() or "GOLD" in s.upper()]
    print("Símbolos de ouro na conta demo:")
    for s in gold:
        print(f"  → {s}")
    await conn.close()

asyncio.run(main())
