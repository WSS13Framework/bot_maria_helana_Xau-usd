#!/usr/bin/env python3
"""
Cria uma conta MetaTrader 5 **demo** via API de provisioning da MetaAPI
(sem usar o assistente web para este passo).

Requisitos (API oficial):
  - METAAPI_TOKEN no .env: **JWT** da MetaAPI.
  - Campos obrigatórios no POST: accountType, balance, email, leverage, name,
    phone (internacional, ex. +351912345678), serverName.
  - keywords: recomendado (lista).

O valor de **accountType** tem de coincidir com o que o MT5 / app móvel do broker
mostra para contas demo. Nem todos os brokers permitem criação via API.

Documentação:
  https://metaapi.cloud/docs/provisioning/api/generateAccount/createMT5DemoAccount/

Exemplo mínimo:
  python3 criar_conta_demo_mt5.py \\
    --email 'user@example.com' \\
    --telefone '+351912345678' \\
    --tipo-conta 'Standard' \\
    --servidor InfinoxLimited-MT5Demo \\
    --alavancagem 1 \\
    --keywords Infinox

Depois de criar, no painel MetaAPI: **Add account** com login/servidor/senha devolvidos
para obter o METAAPI_ACCOUNT_ID (UUID) para test_conexao.py / coletar_candles.py.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi
from metaapi_cloud_sdk.clients.error_handler import ValidationException

# Mesmo repo com ou sem paths.py (ex.: VPS /root/maria-helena)
ENV_PATH = Path(__file__).resolve().parent / ".env"

def _validar_cli(args: argparse.Namespace) -> int | None:
    """Devolve código de saída se inválido; None se OK."""
    email = args.email.strip().lower()
    if "@gemail.com" in email:
        print(
            "Erro: o domínio do email parece typo de gmail.com — use @gmail.com (ou o domínio correcto).",
            file=sys.stderr,
        )
        return 2

    tipo = args.tipo_conta.strip()
    if not tipo:
        print("--tipo-conta não pode estar vazio.", file=sys.stderr)
        return 2
    norm = tipo.upper().replace(" ", "_").replace("-", "_")
    if norm in (
        "VALOR_EXACTO_MT5",
        "VALOR_EXACTO",
        "SEU_TIPO_AQUI",
        "TIPO_CONTA",
        "ACCOUNT_TYPE",
    ) or ("VALOR" in norm and "EXACTO" in norm):
        print(
            "Erro: --tipo-conta não pode ser um placeholder da documentação.\n"
            "  No MT5 Infinox: Ficheiro → Abrir uma conta → Demo → copie o nome exacto do tipo\n"
            "  de conta da lista (cada broker usa strings diferentes).\n"
            "  Já tem conta demo (ex. login 100112613)? Não use este script: no MetaAPI Cloud use\n"
            "  Add account com login, servidor InfinoxLimited-MT5Demo e senhas do broker.",
            file=sys.stderr,
        )
        return 2

    return None


def _print_validation_details(exc: ValidationException) -> None:
    details = exc.details
    if details:
        print(json.dumps(details, indent=2, ensure_ascii=False), file=sys.stderr)
    else:
        print("(sem error.details)", file=sys.stderr)


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
        "phone": args.telefone.strip(),
        "accountType": args.tipo_conta.strip(),
        "keywords": list(args.keywords),
    }

    api = MetaApi(token)
    try:
        creds = await api.metatrader_account_generator_api.create_mt5_demo_account(
            body, profile_id=args.profile or None
        )
    except ValidationException as e:
        print(f"Erro da API (validação): {e}", file=sys.stderr)
        _print_validation_details(e)
        return 1
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
    p.add_argument(
        "--telefone",
        required=True,
        help="Telefone internacional obrigatório da API (ex: +351912345678)",
    )
    p.add_argument(
        "--tipo-conta",
        required=True,
        help="accountType exacto como no MT5 / app do broker (obrigatório na API)",
    )
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
    args = p.parse_args()
    if not args.profile:
        args.profile = None

    bad = _validar_cli(args)
    if bad is not None:
        return bad

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
