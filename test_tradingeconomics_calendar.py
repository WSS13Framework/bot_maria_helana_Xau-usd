"""
Teste de ligação — Trading Economics (prioridade A: calendário macro).

Documentação: https://docs.tradingeconomics.com/economic_calendar/
Preços / chaves: https://tradingeconomics.com/api/pricing.aspx

Credenciais no .env: TRADINGECONOMICS_CLIENT + TRADINGECONOMICS_SECRET (Basic Auth na API REST).
"""
from __future__ import annotations

import json
import sys
import requests
from dotenv import dotenv_values

from paths import ENV_PATH


def main() -> int:
    cfg = dotenv_values(ENV_PATH)
    user = (cfg.get("TRADINGECONOMICS_CLIENT") or "").strip()
    secret = (cfg.get("TRADINGECONOMICS_SECRET") or "").strip()
    if not user or not secret:
        print(
            "Defina TRADINGECONOMICS_CLIENT e TRADINGECONOMICS_SECRET no .env "
            "(painel Trading Economics → API).",
            file=sys.stderr,
        )
        return 1

    # Próximos eventos EUA (CPI/NFP/FOMC vêm neste feed; filtrar por categoria no pipeline)
    country = "united states"
    url = f"https://api.tradingeconomics.com/calendar/country/{country}"
    try:
        r = requests.get(url, auth=(user, secret), timeout=45)
    except requests.RequestException as e:
        print(f"Erro de rede: {e}", file=sys.stderr)
        return 1

    print(f"Status: {r.status_code}")
    raw = (r.text or "").strip()
    if r.status_code != 200:
        print(raw[:800])
        return 1
    if not raw:
        print("Resposta vazia — verifique credenciais e plano.")
        return 1

    try:
        events = json.loads(raw)
    except json.JSONDecodeError:
        print("Resposta não-JSON:", raw[:500], file=sys.stderr)
        return 1

    if not isinstance(events, list):
        print(f"Formato inesperado: {type(events).__name__}")
        return 1

    def importance_ok(e: dict) -> bool:
        imp = e.get("Importance", e.get("importance"))
        s = str(imp).strip().lower()
        return s in ("3", "high")

    high = [e for e in events if isinstance(e, dict) and importance_ok(e)]
    if not high:
        high = [e for e in events if isinstance(e, dict)]

    def ev_date(e: dict) -> str:
        return str(e.get("Date", "") or e.get("date", ""))

    high.sort(key=ev_date)
    slice_events = high[:8]
    print(f"Eventos (amostra até {len(slice_events)} linhas):")
    for e in slice_events[:5]:
        if not isinstance(e, dict):
            continue
        name = e.get("Event") or e.get("event") or "?"
        when = ev_date(e)
        act = e.get("Actual") or e.get("actual")
        fc = e.get("Forecast") or e.get("forecast")
        print(f"  → {when} | {name} | actual={act!r} forecast={fc!r}")

    print(f"\nTotal na resposta: {len(events)} (filtrar CPI/NFP/FOMC no código de produção).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
