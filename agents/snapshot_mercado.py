"""
Grava um snapshot JSON do contexto de mercado (Twelve Data, Benzinga, TE opcional).

Saída: data/market_snapshot.json (não commitado se *.json estiver no .gitignore).

Variáveis de ambiente opcionais:
  TWELVEDATA_SNAPSHOT_SYMBOLS — vírgulas, ex.: "EUR/USD,DX-Y.NYB" (default: EUR/USD)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import requests
from dotenv import dotenv_values

from paths import DATA_DIR, ENV_PATH
from te_env_markers import te_value_looks_like_placeholder


def _clean_td_key(raw: str) -> str:
    k = (raw or "").strip().lstrip("\ufeff")
    if len(k) >= 2 and k[0] == k[-1] and k[0] in "'\"":
        k = k[1:-1].strip()
    return k.strip()


def _clean_cred(raw: str) -> str:
    s = (raw or "").strip().lstrip("\ufeff")
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1].strip()
    return s.strip()


def _te_client_secret(cfg: dict[str, str]) -> tuple[str, str] | None:
    combined = _clean_cred(
        cfg.get("TRADINGECONOMICS_API_KEY") or cfg.get("TRADINGECONOMICS_LOGIN") or ""
    )
    if ":" in combined:
        u, s = combined.split(":", 1)
        u, s = _clean_cred(u), _clean_cred(s)
    else:
        u = _clean_cred(cfg.get("TRADINGECONOMICS_CLIENT") or "")
        s = _clean_cred(cfg.get("TRADINGECONOMICS_SECRET") or "")
    if not u or not s:
        return None
    if te_value_looks_like_placeholder(u) or te_value_looks_like_placeholder(s):
        return None
    return u, s


def _fetch_twelve(symbols: list[str], api_key: str) -> dict[str, Any]:
    out: dict[str, Any] = {"symbols": {}, "errors": []}
    url = "https://api.twelvedata.com/quote"
    for sym in symbols:
        sym = sym.strip()
        if not sym:
            continue
        try:
            r = requests.get(
                url, params={"symbol": sym, "apikey": api_key}, timeout=25
            )
            raw = (r.text or "").strip()
            if r.status_code != 200:
                out["errors"].append({"symbol": sym, "http": r.status_code, "body": raw[:300]})
                continue
            data = json.loads(raw)
            if isinstance(data, dict) and data.get("status") == "error":
                out["errors"].append({"symbol": sym, "message": data.get("message")})
                continue
            out["symbols"][sym] = {
                "close": data.get("close") or data.get("price"),
                "name": data.get("name"),
                "symbol": data.get("symbol"),
                "datetime": data.get("datetime"),
                "currency_base": data.get("currency_base"),
            }
        except (requests.RequestException, json.JSONDecodeError, TypeError, ValueError) as e:
            out["errors"].append({"symbol": sym, "exception": str(e)[:200]})
    return out


def _fetch_benzinga(cfg: dict[str, str]) -> dict[str, Any]:
    key = (cfg.get("BENZINGA_API_KEY") or "").strip()
    if not key:
        return {"skipped": True, "reason": "BENZINGA_API_KEY vazio"}
    url = "https://api.benzinga.com/api/v2/news"
    params = {
        "token": key,
        "topics": "gold",
        "pageSize": 8,
        "displayOutput": "headline",
    }
    try:
        r = requests.get(
            url,
            params=params,
            headers={"Accept": "application/json"},
            timeout=25,
        )
        raw = (r.text or "").strip()
        if r.status_code != 200 or not raw:
            return {"http": r.status_code, "error": raw[:400]}
        news = json.loads(raw)
        if isinstance(news, dict):
            items = news.get("data") or news.get("items") or news.get("news") or []
            if isinstance(items, list):
                news = items
            else:
                news = [news] if news else []
        headlines = []
        for n in news[:8] if isinstance(news, list) else []:
            if isinstance(n, dict):
                headlines.append(
                    {
                        "title": n.get("title"),
                        "created": n.get("created") or n.get("updated"),
                    }
                )
        return {"http": 200, "headlines": headlines, "count": len(headlines)}
    except (requests.RequestException, json.JSONDecodeError, ValueError, TypeError) as e:
        return {"error": str(e)[:300]}


def _fetch_te_indicators(c_param: str) -> dict[str, Any]:
    """Lista curta de indicadores por país (pode 403 se o plano não incluir este endpoint)."""
    country = "united states"
    url = f"https://api.tradingeconomics.com/indicators/country/{quote(country, safe='')}"
    try:
        r = requests.get(url, params={"c": c_param, "f": "json"}, timeout=35)
        raw = (r.text or "").strip()
        if r.status_code != 200:
            return {"http": r.status_code, "body": raw[:500]}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"http": r.status_code, "parse_error": True, "body": raw[:400]}
        if isinstance(data, list):
            slim = []
            for row in data[:12]:
                if isinstance(row, dict):
                    slim.append(
                        {
                            "name": row.get("Name") or row.get("name"),
                            "country": row.get("Country") or row.get("country"),
                            "category": row.get("Category") or row.get("category"),
                            "latest": row.get("LatestValue") or row.get("latestValue"),
                            "unit": row.get("Unit") or row.get("unit"),
                        }
                    )
            return {"http": 200, "count": len(data), "sample": slim}
        return {"http": r.status_code, "format": type(data).__name__, "preview": str(data)[:300]}
    except (requests.RequestException, json.JSONDecodeError, ValueError) as e:
        return {"error": str(e)[:300]}


def main() -> int:
    cfg = dotenv_values(ENV_PATH)
    ts = datetime.now(timezone.utc).isoformat()

    symbols_env = os.environ.get("TWELVEDATA_SNAPSHOT_SYMBOLS") or "EUR/USD"
    symbols = [s.strip() for s in symbols_env.split(",") if s.strip()][:8]

    td_key = _clean_td_key(
        cfg.get("TWELVEDATA_API_KEY") or cfg.get("TWELVEDATA_KEY") or ""
    )
    twelve_block: dict[str, Any]
    if not td_key:
        twelve_block = {"skipped": True, "reason": "TWELVEDATA_API_KEY vazio"}
    else:
        twelve_block = _fetch_twelve(symbols, td_key)

    benzinga_block = _fetch_benzinga(cfg)

    te_pair = _te_client_secret(cfg)
    if te_pair:
        c_param = f"{te_pair[0]}:{te_pair[1]}"
        te_block = _fetch_te_indicators(c_param)
    else:
        te_block = {"skipped": True, "reason": "credenciais TE ausentes ou placeholder"}

    payload = {
        "generated_at_utc": ts,
        "symbols_requested": symbols,
        "twelve_data": twelve_block,
        "benzinga_gold": benzinga_block,
        "trading_economics_indicators_us": te_block,
        "note": "Snapshot para Maria Helena; não envia ordens. Pirâmide: TE indicadores → Twelve Data → Benzinga.",
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / "market_snapshot.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK → {out_path}")
    print(json.dumps({"twelve_data_errors": len(twelve_block.get("errors") or [])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
