"""
Agrega `market_snapshot.json` + `features_gaps_m5.json` num único JSON de regime (só regras).

Entradas (env opcional):
  REGIME_SNAPSHOT_INPUT   — default data/market_snapshot.json
  REGIME_FEATURES_INPUT   — default data/features_gaps_m5.json (se em falta: micro vazio)
Saída:
  REGIME_OUTPUT           — default data/regime_sugerido.json

Não envia ordens. Serve de ponte para `execucao_demo.py` quando a equipa fechar a lógica de sinal.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from paths import DATA_DIR  # noqa: E402

# Palavras‑chave simples nos títulos Benzinga (tópico ouro); heurística v1.
_BULL = (
    "gain",
    "gains",
    "rise",
    "rises",
    "rally",
    "surge",
    "higher",
    "jump",
    "soar",
    "record high",
    "up sharply",
    "climb",
)
_BEAR = (
    "fall",
    "falls",
    "drop",
    "drops",
    "slip",
    "tumble",
    "decline",
    "lower",
    "plunge",
    "down sharply",
    "retreat",
)


def _twelve_status(block: Any) -> str:
    if not isinstance(block, dict):
        return "error"
    if block.get("skipped"):
        return "skipped"
    sym = block.get("symbols") or {}
    err = block.get("errors") or []
    if isinstance(sym, dict) and sym and not err:
        return "ok"
    if isinstance(sym, dict) and sym and err:
        return "partial"
    if err and not sym:
        return "error"
    return "skipped"


def _benzinga_status(block: Any) -> str:
    if not isinstance(block, dict):
        return "error"
    if block.get("skipped"):
        return "skipped"
    if block.get("http") == 200 and isinstance(block.get("headlines"), list):
        return "ok"
    return "error"


def _te_status(block: Any) -> str:
    if not isinstance(block, dict):
        return "error"
    if block.get("skipped"):
        return "skipped"
    if block.get("http") == 200:
        return "ok"
    return "error"


def _headline_titles(snapshot: dict[str, Any]) -> list[str]:
    bz = snapshot.get("benzinga_gold")
    if not isinstance(bz, dict) or bz.get("skipped"):
        return []
    raw = bz.get("headlines") or []
    out: list[str] = []
    for h in raw if isinstance(raw, list) else []:
        if isinstance(h, dict) and h.get("title"):
            out.append(str(h["title"]))
    return out


def _score_headlines(titles: list[str]) -> dict[str, Any]:
    bull = bear = 0
    for t in titles:
        low = t.lower()
        bull += sum(1 for w in _BULL if w in low)
        bear += sum(1 for w in _BEAR if w in low)
    if bull > bear:
        tonalidade = "supportivo_ouro"
    elif bear > bull:
        tonalidade = "pressao_ouro"
    else:
        tonalidade = "neutro"
    return {"bull_hits": bull, "bear_hits": bear, "tonalidade": tonalidade}


def _load_features(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    last = meta.get("last_bar") if isinstance(meta.get("last_bar"), dict) else {}
    return {
        "gap_sessao_flag": bool(last.get("gap_sessao_flag")),
        "gap_sessao_pct": last.get("gap_sessao_pct"),
        "imbalance_bull_3": bool(last.get("imbalance_bull_3")),
        "imbalance_bear_3": bool(last.get("imbalance_bear_3")),
        "time": last.get("time"),
        "close": last.get("close"),
    }


def _consolidated_bias(
    news: dict[str, Any], micro: dict[str, Any] | None
) -> tuple[str, list[str]]:
    razoes: list[str] = []
    tonal = news.get("tonalidade") or "neutro"

    if micro is None:
        razoes.append("Sem features M5 (correr make features-gaps após coletar_candles).")
        if tonal == "supportivo_ouro":
            return "neutro_noticias_só", razoes + ["Notícias ligeiramente positivas para o ouro; falta microestrutura M5."]
        if tonal == "pressao_ouro":
            return "neutro_noticias_só", razoes + ["Notícias ligeiramente negativas para o ouro; falta microestrutura M5."]
        return "neutro", razoes

    bull = micro.get("imbalance_bull_3")
    bear = micro.get("imbalance_bear_3")
    gap = micro.get("gap_sessao_flag")

    if gap:
        razoes.append("Última vela M5 com gap de sessão acima do limiar.")

    if bull and not bear:
        razoes.append("Desequilíbrio comprador (3 velas) na última barra.")
        if tonal == "pressao_ouro":
            return "neutro_conflito", razoes + ["Conflito: notícias fracas vs micro comprador."]
        if tonal == "supportivo_ouro":
            return "cautelosamente_comprador", razoes + ["Alinhamento leve: notícias + micro comprador."]
        return "micro_comprador", razoes

    if bear and not bull:
        razoes.append("Desequilíbrio vendedor (3 velas) na última barra.")
        if tonal == "supportivo_ouro":
            return "neutro_conflito", razoes + ["Conflito: notícias positivas vs micro vendedor."]
        if tonal == "pressao_ouro":
            return "cautelosamente_vendedor", razoes + ["Alinhamento leve: notícias + micro vendedor."]
        return "micro_vendedor", razoes

    if tonal == "supportivo_ouro":
        return "neutro_tendencia_noticias", razoes + ["Fluxo de títulos ligeiramente favorável ao ouro; sem imbalance claro."]
    if tonal == "pressao_ouro":
        return "neutro_tendencia_noticias", razoes + ["Fluxo de títulos ligeiramente desfavorável ao ouro; sem imbalance claro."]

    return "neutro", razoes


def _regime_label(coverage: dict[str, str]) -> str:
    ok_n = sum(1 for v in coverage.values() if v == "ok")
    if ok_n == 0:
        return "contexto_muito_fino"
    if ok_n == 1:
        return "contexto_fino"
    if ok_n == 2:
        return "contexto_parcial"
    return "contexto_completo"


def main() -> int:
    snap_path = Path(os.environ.get("REGIME_SNAPSHOT_INPUT", str(DATA_DIR / "market_snapshot.json")))
    feat_path = Path(os.environ.get("REGIME_FEATURES_INPUT", str(DATA_DIR / "features_gaps_m5.json")))
    out_path = Path(os.environ.get("REGIME_OUTPUT", str(DATA_DIR / "regime_sugerido.json")))

    if not snap_path.is_file():
        print(f"Falta snapshot: {snap_path}\nCorra: make snapshot-mercado", file=sys.stderr)
        return 1

    try:
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"Erro a ler JSON do snapshot: {e}", file=sys.stderr)
        return 1
    if not isinstance(snapshot, dict):
        print("market_snapshot.json inválido (esperado objecto JSON).", file=sys.stderr)
        return 1

    twelve = snapshot.get("twelve_data")
    bz = snapshot.get("benzinga_gold")
    te = snapshot.get("trading_economics_indicators_us")
    coverage = {
        "twelve_data": _twelve_status(twelve),
        "benzinga_gold": _benzinga_status(bz),
        "trading_economics_us": _te_status(te),
    }

    titles = _headline_titles(snapshot)
    news_scores = _score_headlines(titles)

    te_ok = coverage["trading_economics_us"] == "ok"
    macro_note = "Indicadores TE disponíveis." if te_ok else "Indicadores TE ausentes, em erro ou plano sem endpoint."

    micro = _load_features(feat_path)
    bias, razoes = _consolidated_bias(news_scores, micro)

    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "generated_at_utc": now,
        "snapshot_generated_at_utc": snapshot.get("generated_at_utc"),
        "inputs": {
            "snapshot": str(snap_path),
            "features_gaps": str(feat_path) if feat_path.is_file() else None,
        },
        "data_coverage": coverage,
        "regime_sugerido": _regime_label(coverage),
        "noticias": {
            "headline_count": len(titles),
            "tonalidade": news_scores["tonalidade"],
            "scores": {"bull_hits": news_scores["bull_hits"], "bear_hits": news_scores["bear_hits"]},
        },
        "macro": {"indicadores_disponiveis": te_ok, "nota": macro_note},
        "micro_xau_m5": micro,
        "viés_consolidado": bias,
        "razoes": razoes,
        "nota": "Saída heurística v1 (regras). Não é recomendação de investimento.",
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK → {out_path} | regime={payload['regime_sugerido']} | viés={bias}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
