"""
Teste de ligação — Twelve Data (prioridade B: cotações DXY/VIX/rates conforme plano).

Documentação: https://twelvedata.com/docs#quote
Preços: https://twelvedata.com/prime (individual) / business

Símbolo teste configurável (DXY costuma ser DX-Y.NYB ou símbolo da conta Twelve Data).
"""
from __future__ import annotations

import json
import os
import sys

import requests
from dotenv import dotenv_values

from paths import ENV_PATH


def _clean_api_key(raw: str) -> str:
    k = (raw or "").strip().lstrip("\ufeff")
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "'\"":
        k = k[1:-1].strip()
    return k.strip()


def main() -> int:
    cfg = dotenv_values(ENV_PATH)
    key = _clean_api_key(
        cfg.get("TWELVEDATA_API_KEY") or cfg.get("TWELVEDATA_KEY") or ""
    )
    if not key:
        print("Defina TWELVEDATA_API_KEY no .env.", file=sys.stderr)
        return 1

    symbol = (os.environ.get("TWELVEDATA_TEST_SYMBOL") or "EUR/USD").strip()

    url = "https://api.twelvedata.com/quote"
    params = {"symbol": symbol, "apikey": key}
    try:
        r = requests.get(url, params=params, timeout=30)
    except requests.RequestException as e:
        print(f"Erro de rede: {e}", file=sys.stderr)
        return 1

    print(f"Status: {r.status_code} | símbolo={symbol!r}")
    raw = (r.text or "").strip()
    if not raw:
        print("Resposta vazia.")
        return 1

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(raw[:600], file=sys.stderr)
        return 1

    if isinstance(data, dict) and data.get("status") == "error":
        print(f"Erro Twelve Data: {data.get('message', data)}", file=sys.stderr)
        hint = (
            "Verifique TWELVEDATA_API_KEY no .env (sem aspas extra, sem espaços). "
            "Chave no dashboard: https://twelvedata.com/account/api-keys"
        )
        print(hint, file=sys.stderr)
        if key:
            u0 = ord(key[0])
            print(
                f"   Diagnóstico: apikey com {len(key)} caracteres; "
                f"primeiro código U+{u0:04X} (FEFF=BOM).",
                file=sys.stderr,
            )
        return 1

    if not isinstance(data, dict):
        print(f"Formato inesperado: {type(data).__name__}")
        return 1

    name = data.get("name") or data.get("symbol")
    price = data.get("close") or data.get("price")
    day = data.get("datetime") or data.get("is_market_open")
    print(f"  → {name} | último/preço={price!r} | {day!r}")
    print("\nPara DXY/VIX use símbolos suportados pelo teu plano (ex.: TWELVEDATA_TEST_SYMBOL=DX-Y.NYB).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
