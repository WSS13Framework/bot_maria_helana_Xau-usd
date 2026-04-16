import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path("/root/maria-helena/data")
OUTPUT_FILE = DATA_DIR / "features_snapshot.json"


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _safe_last(candles: list[dict]) -> dict | None:
    if not candles:
        return None
    return candles[-1]


def _extract_latest_relevant_news(news_payload: list[dict] | dict) -> list[dict]:
    if isinstance(news_payload, list):
        items = news_payload
    elif isinstance(news_payload, dict):
        items = news_payload.get("data") or news_payload.get("news") or []
    else:
        items = []

    # Keep only compact fields needed by modeling and audit.
    compact = []
    for item in items:
        compact.append(
            {
                "title": item.get("title") or item.get("headline"),
                "time": item.get("created") or item.get("updated") or item.get("date"),
                "matched_keywords": item.get("matched_keywords", []),
            }
        )
    return compact[:20]


def build_feature_snapshot() -> dict:
    m5_path = DATA_DIR / "xauusd_m5.json"
    h1_path = DATA_DIR / "xauusd_h1.json"
    d1_path = DATA_DIR / "xauusd_d1.json"
    macro_path = DATA_DIR / "macro_snapshot.json"
    news_path = DATA_DIR / "benzinga_relevant_news.json"

    m5 = _read_json(m5_path) if m5_path.exists() else []
    h1 = _read_json(h1_path) if h1_path.exists() else []
    d1 = _read_json(d1_path) if d1_path.exists() else []
    macro = _read_json(macro_path) if macro_path.exists() else {}
    news = _read_json(news_path) if news_path.exists() else []

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_state": {
            "m5_last": _safe_last(m5),
            "h1_last": _safe_last(h1),
            "d1_last": _safe_last(d1),
        },
        "macro_state": {
            "dxy_yahoo": macro.get("dxy_yahoo"),
            "vix_yahoo": macro.get("vix_yahoo"),
            "us10y_fred": macro.get("us10y_fred"),
            "dxy_fred_proxy": macro.get("dxy_fred_proxy"),
        },
        "news_state": {
            "relevant_news_count": len(news) if isinstance(news, list) else 0,
            "latest_relevant_news": _extract_latest_relevant_news(news),
        },
    }
    return snapshot


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = build_feature_snapshot()
    with OUTPUT_FILE.open("w", encoding="utf-8") as fp:
        json.dump(snapshot, fp, ensure_ascii=False)
    print(f"✅ Features snapshot salvo em {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
