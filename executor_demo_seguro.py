import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

DATA_DIR = Path("/root/maria-helena/data")
DEFAULT_ENV_PATH = Path("/root/maria-helena/.env")
DEFAULT_LOG_PATH = DATA_DIR / "demo_executor_log.jsonl"


def _append_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _classify_account(name: str) -> str:
    lower_name = name.lower()
    if "demo" in lower_name:
        return "demo"
    if "live" in lower_name or "real" in lower_name:
        return "live"
    return "unknown"


async def run_executor(args: argparse.Namespace) -> None:
    cfg = dotenv_values(args.env_file)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    account_id = (args.account_id or cfg.get("METAAPI_DEMO_ACCOUNT_ID") or "").strip()
    if not token:
        raise ValueError("METAAPI_TOKEN não encontrado no .env")
    if not account_id:
        raise ValueError("account_id ausente. Use --account-id ou METAAPI_DEMO_ACCOUNT_ID no .env")

    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(account_id)
    account_name = account.name or ""
    account_kind = _classify_account(account_name)

    if account_kind == "live" and not args.allow_live:
        raise ValueError(
            f"Conta LIVE detectada ({account_name}). "
            "Use --allow-live explicitamente se realmente quiser operar live."
        )
    if account_kind == "unknown" and not args.allow_unknown_account:
        raise ValueError(
            f"Não foi possível classificar conta '{account_name}'. "
            "Use --allow-unknown-account para continuar."
        )

    await account.wait_connected()
    connection = account.get_rpc_connection()
    await connection.connect()
    await connection.wait_synchronized()

    positions = await connection.get_positions()
    symbol_positions = [position for position in positions if (position.get("symbol") or "").upper() == args.symbol.upper()]
    if len(symbol_positions) >= args.max_open_positions:
        print(
            f"⚠️ Execução bloqueada: já existem {len(symbol_positions)} posições em {args.symbol} "
            f"(limite={args.max_open_positions})."
        )
        return

    terminal_state = connection.terminal_state
    symbol_price = terminal_state.price(symbol=args.symbol)
    if not symbol_price:
        raise ValueError(f"Preço indisponível para {args.symbol}")

    specification = terminal_state.specification(symbol=args.symbol) or {}
    point = specification.get("point") or 0.01
    ask = float(symbol_price.get("ask"))
    bid = float(symbol_price.get("bid"))
    entry_price = ask if args.side == "buy" else bid

    stop_loss = None
    take_profit = None
    if args.sl_points > 0:
        stop_loss = entry_price - (args.sl_points * point) if args.side == "buy" else entry_price + (args.sl_points * point)
    if args.tp_points > 0:
        take_profit = entry_price + (args.tp_points * point) if args.side == "buy" else entry_price - (args.tp_points * point)

    order_plan = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "account_id": account_id,
        "account_name": account_name,
        "account_kind": account_kind,
        "symbol": args.symbol.upper(),
        "side": args.side,
        "volume": args.volume,
        "entry_price": entry_price,
        "sl_points": args.sl_points,
        "tp_points": args.tp_points,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "dry_run": not args.execute,
    }
    _append_log(args.log_path, {"event": "order_plan", **order_plan})

    print("Plano de ordem:")
    print(json.dumps(order_plan, indent=2, ensure_ascii=False))

    if not args.execute:
        print("✅ DRY RUN concluído (nenhuma ordem enviada). Use --execute para enviar.")
        return

    options = {"comment": args.comment}
    if args.side == "buy":
        result = await connection.create_market_buy_order(
            args.symbol.upper(), args.volume, stop_loss, take_profit, options
        )
    else:
        result = await connection.create_market_sell_order(
            args.symbol.upper(), args.volume, stop_loss, take_profit, options
        )

    execution_log = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "order_executed",
        "account_id": account_id,
        "symbol": args.symbol.upper(),
        "side": args.side,
        "volume": args.volume,
        "result": result,
    }
    _append_log(args.log_path, execution_log)
    print("✅ Ordem enviada com sucesso.")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Executor seguro para conta DEMO via MetaApi.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    parser.add_argument("--account-id", type=str, default="")
    parser.add_argument("--symbol", type=str, default="XAUUSD")
    parser.add_argument("--side", type=str, choices=("buy", "sell"), required=True)
    parser.add_argument("--volume", type=float, default=0.01)
    parser.add_argument("--sl-points", type=float, default=0.0)
    parser.add_argument("--tp-points", type=float, default=0.0)
    parser.add_argument("--comment", type=str, default="MariaHelena-Demo")
    parser.add_argument("--max-open-positions", type=int, default=1)
    parser.add_argument("--allow-live", action="store_true")
    parser.add_argument("--allow-unknown-account", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_executor(args))


if __name__ == "__main__":
    main()
