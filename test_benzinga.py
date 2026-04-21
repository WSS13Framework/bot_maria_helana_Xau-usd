import requests
from pathlib import Path
from dotenv import dotenv_values

project_root = Path(__file__).resolve().parent
env_path = project_root / ".env"
if not env_path.exists():
    print(f"⚠️ Arquivo .env não encontrado em {env_path}")
    raise SystemExit(0)

cfg = dotenv_values(env_path)
key = cfg.get("BENZINGA_API_KEY", "").strip()
if not key:
    print("⚠️ BENZINGA_API_KEY ausente no .env")
    raise SystemExit(0)

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
