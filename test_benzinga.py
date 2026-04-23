import json
import sys

import requests
from dotenv import dotenv_values

from paths import ENV_PATH


def main() -> int:
    cfg = dotenv_values(ENV_PATH)
    key = (cfg.get("BENZINGA_API_KEY") or "").strip()
    if not key:
        print("Defina BENZINGA_API_KEY no .env", file=sys.stderr)
        return 1

    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": key,
        "topics": "gold",
        "pageSize": 5,
        "displayOutput": "headline",
    }
    headers = {"Accept": "application/json"}

    try:
        r = requests.get(url, params=params, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"Erro de rede: {e}", file=sys.stderr)
        return 1

    print(f"Status: {r.status_code}")
    raw = (r.text or "").strip()

    if r.status_code != 200:
        print(f"Erro HTTP: {raw[:500]}")
        return 1

    if not raw:
        print(
            "Resposta 200 mas corpo vazio. Possíveis causas: token inválido/expirado, "
            "limite de plano, ou endpoint a devolver HTML em branco. Confirme a chave no painel Benzinga."
        )
        return 1

    try:
        news = json.loads(raw)
    except json.JSONDecodeError:
        print("Resposta não é JSON. Início do corpo:", file=sys.stderr)
        print(raw[:800], file=sys.stderr)
        return 1

    if isinstance(news, dict):
        items = news.get("data") or news.get("items") or news.get("news") or []
        if not items and "title" not in news:
            print(f"JSON inesperado (chaves): {list(news.keys())[:20]}")
            return 1
        if isinstance(items, list):
            news = items
        else:
            news = [news]

    if not isinstance(news, list):
        print(f"Formato inesperado: {type(news).__name__}")
        return 1

    print(f"Notícias recebidas: {len(news)}")
    for n in news[:3]:
        if isinstance(n, dict):
            print(f"  → {n.get('title', 'sem título')}")
        else:
            print(f"  → {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
