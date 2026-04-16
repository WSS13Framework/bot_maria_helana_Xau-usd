import requests
from dotenv import dotenv_values

from benzinga_filter import filter_relevant_news, parse_benzinga_xml_news
import json

cfg = dotenv_values("/root/maria-helena/.env")
key = cfg.get("BENZINGA_API_KEY", "").strip()
output_path = "/root/maria-helena/data/benzinga_relevant_news.json"

url = "https://api.benzinga.com/api/v2/news"
params = {
    "token": key,
    "pageSize": 25,
    "displayOutput": "headline",
}

r = requests.get(url, params=params, timeout=20)
print(f"Status: {r.status_code}")

if r.status_code == 200:
    content_type = r.headers.get("content-type", "").lower()
    payload: list[dict] | dict
    if "xml" in content_type:
        payload = parse_benzinga_xml_news(r.text)
    else:
        payload = r.json()

    news = payload if isinstance(payload, list) else payload.get("data", [])
    filtered = filter_relevant_news(payload, min_keyword_hits=1)
    print(f"Notícias recebidas: {len(news)}")
    print(f"Notícias relevantes para XAU/USD: {len(filtered)}")
    with open(output_path, "w", encoding="utf-8") as fp:
        json.dump(filtered, fp, ensure_ascii=False)
    print(f"✅ Notícias relevantes salvas em {output_path}")
    for n in filtered[:5]:
        title = n.get("title") or n.get("headline") or "sem título"
        keywords = ", ".join(n.get("matched_keywords", []))
        print(f"  → {title}")
        print(f"     keywords: {keywords}")
else:
    print(f"Erro: {r.text[:200]}")
