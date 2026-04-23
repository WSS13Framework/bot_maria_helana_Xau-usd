"""
Agente de execução — apenas conta MT5 **demo**, com confirmações explícitas no .env.

  MARIA_EXECUCAO_DEMO=1     — obrigatório para correr
  MARIA_EXECUCAO_DRY=1      — por defeito: só liga e regista intenção (sem ordem real)
  MARIA_EXECUCAO_DRY=0      — envia ordem a mercado (volume mínimo) se a conta for aceite como demo

Segurança: se o nome da conta contém \"live\" (ex.: \"Infinox Live\") e não contém \"demo\",
o script **aborta**, salvo `METAAPI_CONFIRMO_EXECUCAO_EM_CONTA_LIVE=1` no `.env` (valor exacto).

Não substitui validação humana nem política de risco.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from dotenv import dotenv_values  # noqa: E402
from metaapi_cloud_sdk import MetaApi  # noqa: E402
from metaapi_cloud_sdk.clients.metaapi.trade_exception import TradeException  # noqa: E402

from paths import DATA_DIR, ENV_PATH  # noqa: E402


def _truthy(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _account_accepted_as_demo(name: str) -> tuple[bool, str]:
    n = name.lower()
    if "demo" in n:
        return True, "nome contém 'demo'"
    if "live" in n and "demo" not in n:
        if os.environ.get("METAAPI_CONFIRMO_EXECUCAO_EM_CONTA_LIVE", "").strip() == "1":
            return True, "METAAPI_CONFIRMO_EXECUCAO_EM_CONTA_LIVE=1 (conta com 'live' no nome — risco)"
        return False, "nome sugere conta LIVE; defina conta demo ou METAAPI_CONFIRMO_EXECUCAO_EM_CONTA_LIVE=1"
    return True, "nome sem 'live' explícito — aceite como candidata a demo (verifique no MetaAPI)"


async def _run() -> int:
    cfg = dotenv_values(ENV_PATH)
    if not _truthy(cfg.get("MARIA_EXECUCAO_DEMO")):
        print(
            "Defina MARIA_EXECUCAO_DEMO=1 no .env para activar este script.",
            file=sys.stderr,
        )
        return 1

    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    acc_id = (cfg.get("METAAPI_ACCOUNT_ID") or "").strip()
    if not token or not acc_id:
        print("METAAPI_TOKEN e METAAPI_ACCOUNT_ID são obrigatórios.", file=sys.stderr)
        return 1

    dry = _truthy(cfg.get("MARIA_EXECUCAO_DRY", "1"))
    symbol = (cfg.get("MARIA_DEMO_SYMBOL") or "XAUUSD+").strip()
    volume = float((cfg.get("MARIA_DEMO_VOLUME") or "0.01").strip())

    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(acc_id)
    await account.wait_connected()

    ok, reason = _account_accepted_as_demo(account.name)
    if not ok:
        print(f"ABORTADO: {reason} | conta={account.name!r}", file=sys.stderr)
        return 1

    conn = account.get_rpc_connection()
    await conn.connect()
    await conn.wait_synchronized()

    log_line = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "account": account.name,
        "symbol": symbol,
        "volume": volume,
        "dry_run": dry,
        "reason_demo": reason,
    }

    if dry:
        log_line["action"] = "DRY_RUN — nenhuma ordem enviada"
        print(json.dumps(log_line, ensure_ascii=False))
    else:
        side = (cfg.get("MARIA_DEMO_SIDE") or "buy").strip().lower()
        try:
            if side == "sell":
                res = await conn.create_market_sell_order(symbol, volume)
            else:
                res = await conn.create_market_buy_order(symbol, volume)
            log_line["action"] = "ORDER_SENT"
            log_line["response"] = str(res)[:500]
            print(json.dumps(log_line, ensure_ascii=False))
        except TradeException as e:
            log_line["action"] = "ORDER_FAILED"
            log_line["error"] = str(e)[:500]
            print(json.dumps(log_line, ensure_ascii=False), file=sys.stderr)
            await conn.close()
            return 1

    await conn.close()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_path = DATA_DIR / "execucao_demo_log.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_line, ensure_ascii=False) + "\n")
    print(f"Log → {log_path}")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
