import asyncio
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"


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
