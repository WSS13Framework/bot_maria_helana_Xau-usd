from pathlib import Path
import requests
from dotenv import dotenv_values

local_env = Path(__file__).resolve().parent / ".env"
if local_env.exists():
    cfg = dotenv_values(local_env)
else:
    cfg = dotenv_values("/root/maria-helena/.env")
key = cfg.get("BENZINGA_API_KEY", "").strip()
if not key:
    raise RuntimeError("Missing BENZINGA_API_KEY in .env")

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
