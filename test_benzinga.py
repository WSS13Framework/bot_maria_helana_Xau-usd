import requests
from pathlib import Path
from dotenv import dotenv_values

ENV_PATH = Path(__file__).resolve().parent / ".env"
cfg = dotenv_values(ENV_PATH)
key = cfg.get("BENZINGA_API_KEY", "").strip()

if not key or key == "sua_key_aqui":
    raise RuntimeError(f"BENZINGA_API_KEY ausente/invalido em {ENV_PATH}")

url = "https://api.benzinga.com/api/v2/news"
params = {
    "token": key,
    "topics": "gold",
    "pageSize": 5,
    "displayOutput": "headline"
}

r = requests.get(url, params=params)
print(f"Status: {r.status_code}")

if r.status_code == 200:
    news = r.json()
    print(f"Notícias recebidas: {len(news)}")
    for n in news[:3]:
        print(f"  → {n.get('title', 'sem título')}")
else:
    print(f"Erro: {r.text[:200]}")
