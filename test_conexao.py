import asyncio
from pathlib import Path
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

def invalid_env_value(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized.startswith("seu_")
        or normalized.startswith("sua_")
        or normalized.endswith("_aqui")
    )

async def main():
    project_root = Path(__file__).resolve().parent
    env_path = project_root / ".env"
    if not env_path.exists():
        print(f"⚠️ Arquivo .env não encontrado em {env_path}")
        return

    cfg = dotenv_values(env_path)
    token = cfg.get("METAAPI_TOKEN", "").strip()
    account_id = cfg.get("METAAPI_ACCOUNT_ID", "").strip()
    if invalid_env_value(token) or invalid_env_value(account_id):
        print("⚠️ METAAPI_TOKEN ou METAAPI_ACCOUNT_ID ausente/inválido no .env")
        return

    print(f"Account ID: {account_id[:8]}...")

    try:
        api = MetaApi(token)
        account = await api.metatrader_account_api.get_account(account_id)
        await account.wait_connected()
        print(f"✅ Conectado: {account.name}")
    except Exception as exc:
        print(f"❌ Falha ao conectar na MetaAPI: {exc}")

asyncio.run(main())
