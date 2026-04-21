import asyncio
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

PLACEHOLDER_MARKERS = (
    "seu_",
    "sua_",
    "_aqui",
)


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or any(marker in normalized for marker in PLACEHOLDER_MARKERS)


async def main():
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"
    if not env_path.exists():
        print(f"⚠️ Arquivo .env não encontrado em {env_path}")
        return

    cfg = dotenv_values(env_path)
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()
    if _is_placeholder(token) or _is_placeholder(account_id):
        print("⚠️ METAAPI_TOKEN ou METAAPI_ACCOUNT_ID ausente/placeholder no .env")
        return

    try:
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
    except Exception as exc:
        print(f"❌ Falha ao listar símbolos via MetaAPI: {exc}")

asyncio.run(main())
