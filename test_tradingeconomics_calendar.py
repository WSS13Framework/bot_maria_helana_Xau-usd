"""
Teste de ligação — Trading Economics (prioridade A: calendário macro).

Documentação: https://docs.tradingeconomics.com/economic_calendar/
Preços / chaves: https://tradingeconomics.com/api/pricing.aspx

Credenciais no .env (uma das opções):

- **TRADINGECONOMICS_API_KEY** = `client:secret` numa só linha (igual a `te.login()` no pacote oficial), ou
- **TRADINGECONOMICS_CLIENT** + **TRADINGECONOMICS_SECRET** (partes antes/depois do `:`).

A API REST usa **c=client:secret** na query (não Basic Auth).
Ver: https://docs.tradingeconomics.com/economic_calendar/country/
"""
from __future__ import annotations

import json
import os
import re
import sys
from urllib.parse import quote

import requests
from dotenv import dotenv_values

from paths import ENV_PATH
from te_env_markers import te_value_looks_like_placeholder


def _clean_cred(raw: str) -> str:
    s = (raw or "").strip().lstrip("\ufeff")
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s.strip()


def _is_doc_placeholder(user: str, secret: str) -> bool:
    """Detecta texto copiado de tutoriais (chat/README) em vez das chaves do painel TE."""
    return te_value_looks_like_placeholder(user) or te_value_looks_like_placeholder(secret)


def _load_te_credentials(cfg: dict) -> tuple[str, str]:
    """Client + secret a partir de API_KEY única (client:secret) ou par de variáveis."""
    combined = _clean_cred(
        cfg.get("TRADINGECONOMICS_API_KEY")
        or cfg.get("TRADINGECONOMICS_LOGIN")
        or ""
    )
    if ":" in combined:
        left, right = combined.split(":", 1)
        return _clean_cred(left), _clean_cred(right)
    return (
        _clean_cred(cfg.get("TRADINGECONOMICS_CLIENT") or ""),
        _clean_cred(cfg.get("TRADINGECONOMICS_SECRET") or ""),
    )


def main() -> int:
    cfg = dotenv_values(ENV_PATH)
    user, secret = _load_te_credentials(cfg)
    if not user or not secret:
        print(
            "Defina TRADINGECONOMICS_API_KEY=client:secret (recomendado) ou "
            "TRADINGECONOMICS_CLIENT + TRADINGECONOMICS_SECRET no .env "
            "(painel Trading Economics → API).",
            file=sys.stderr,
        )
        return 1
    if _is_doc_placeholder(user, secret):
        print(
            "ERRO: O .env contém texto de TUTORIAL (README/chat), não as chaves do site Trading Economics.\n"
            "Não copie frases explicativas (PRIMEIRA_STRING…, CLIENT_DO_SITE…, etc.).\n"
            "Abra tradingeconomics.com no browser → login → API / developer → selecione e copie "
            "os dois valores que o painel mostra (Client e Secret).\n"
            "No terminal SSH, cole esses valores dentro das aspas do set_env — só caracteres "
            "que vieram do site, sem palavras em português/inglês de exemplo.",
            file=sys.stderr,
        )
        return 1

    # TE: autenticação via query `c=client:secret` (documentação oficial)
    country = "united states"
    url = f"https://api.tradingeconomics.com/calendar/country/{quote(country, safe='')}"
    c_param = f"{user}:{secret}"
    try:
        r = requests.get(
            url,
            params={"c": c_param, "f": "json"},
            timeout=45,
        )
    except requests.RequestException as e:
        print(f"Erro de rede: {e}", file=sys.stderr)
        return 1

    if os.environ.get("TE_DIAG"):
        prep = requests.Request("GET", url, params={"c": c_param, "f": "json"}).prepare()
        redacted = re.sub(r"([&?])c=[^&]*", r"\1c=***", prep.url)
        print(f"TE_DIAG URL (credencial oculta): {redacted}", file=sys.stderr)

    print(f"Status: {r.status_code}")
    raw = (r.text or "").strip()
    if r.status_code != 200:
        print(raw[:800])
        if r.status_code == 401:
            print(
                "\nDica: (1) git pull / servidor_atualizar.sh se o código for antigo. "
                "(2) Confirme no painel TE o par real (não placeholders do README). "
                "(3) Opcional: TRADINGECONOMICS_API_KEY='client:secret' numa variável só.",
                file=sys.stderr,
            )
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
