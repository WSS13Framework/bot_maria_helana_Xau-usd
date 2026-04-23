#!/usr/bin/env python3
"""
Cria uma conta MetaTrader 5 **demo** via API de provisioning da MetaAPI
(sem usar o assistente web para este passo).

Requisitos:
  - METAAPI_TOKEN no .env tem de ser um **JWT** (token de API da MetaAPI), não outro formato.
  - Perfil de provisioning em https://app.metaapi.cloud/ (por defeito: `default`).

Documentação:
  https://metaapi.cloud/docs/provisioning/api/generateAccount/createMT5DemoAccount/

Depois de criar, no painel MetaAPI: **Add account** com login/servidor/senha devolvidos
para obter o METAAPI_ACCOUNT_ID (UUID) para test_conexao.py / coletar_candles.py.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

from paths import ENV_PATH


async def run(args: argparse.Namespace) -> int:
    cfg = dotenv_values(ENV_PATH)
    token = (cfg.get("METAAPI_TOKEN") or "").strip()
    if not token:
        print(f"Defina METAAPI_TOKEN em {ENV_PATH}", file=sys.stderr)
        return 1

    body: dict = {
        "serverName": args.servidor,
        "email": args.email,
        "balance": float(args.saldo),
        "leverage": float(args.alavancagem),
        "name": args.nome,
        "keywords": list(args.keywords),
    }
    if args.tipo_conta:
        body["accountType"] = args.tipo_conta

    api = MetaApi(token)
    try:
        creds = await api.metatrader_account_generator_api.create_mt5_demo_account(
            body, profile_id=args.profile or None
        )
    except Exception as e:
        print(f"Erro da API: {e}", file=sys.stderr)
        return 1

    print("Conta MT5 demo criada (broker via MetaAPI):\n")
    print(f"  Login:     {creds.login}")
    print(f"  Servidor:  {creds.server_name}")
    print(f"  Senha:     {creds.password}")
    print(f"  Investidor:{creds.investor_password}")
    print(
        "\nGuarde estas senhas em local seguro. No painel MetaAPI, adicione esta conta MT5"
        "\npara receber o UUID (METAAPI_ACCOUNT_ID) dos scripts Python."
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Cria MT5 demo via MetaAPI (terminal).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--servidor",
        default="InfinoxLimited-MT5Demo",
        help="Nome exacto do servidor MT5 demo no broker",
    )
    p.add_argument("--email", required=True, help="Email do titular (pedido pela API)")
    p.add_argument("--nome", default="Demo CLI", help="Nome do titular")
    p.add_argument("--saldo", type=float, default=100_000.0, help="Saldo inicial demo")
    p.add_argument(
        "--alavancagem",
        type=float,
        default=100.0,
        help="Alavancagem como número MetaAPI (100 = 1:100). Use 1 para 1:1",
    )
    p.add_argument(
        "--keywords",
        nargs="+",
        default=["Infinox"],
        help="Palavras-chave para localizar o broker (recomendado incluir o nome da corretora)",
    )
    p.add_argument(
        "--profile",
        default="",
        help="ID do provisioning profile; vazio = 'default'",
    )
    p.add_argument(
        "--tipo-conta",
        default="",
        help="Opcional: accountType do broker (ver tipos no MT5 do broker)",
    )
    args = p.parse_args()
    if not args.profile:
        args.profile = None
    if not args.tipo_conta:
        args.tipo_conta = None

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
