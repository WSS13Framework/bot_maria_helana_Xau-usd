"""
Valida `data/regime_sugerido.json` (contrato v1) e imprime um resumo — sem ordens, sem rede.

Uso no Tubarão ou no MonetaBot-Pro (copiar o script ou invocar o mesmo repo Maria):
  make regime-handoff-read
  REGIME_HANDOFF_INPUT=/caminho/regime_sugerido.json make regime-handoff-read

Saída: linha JSON em stdout (para log agregador); código 0 = válido, 1 = inválido.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from paths import DATA_DIR  # noqa: E402

_COVERAGE_KEYS = ("twelve_data", "benzinga_gold", "trading_economics_us")
_REGIME_LABELS = frozenset(
    {"contexto_muito_fino", "contexto_fino", "contexto_parcial", "contexto_completo"}
)
_TONALIDADE = frozenset({"neutro", "supportivo_ouro", "pressao_ouro"})


def validate_regime_payload(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for k in (
        "generated_at_utc",
        "data_coverage",
        "regime_sugerido",
        "noticias",
        "macro",
        "viés_consolidado",
        "razoes",
    ):
        if k not in data:
            errs.append(f"falta campo obrigatório: {k}")

    cov = data.get("data_coverage")
    if not isinstance(cov, dict):
        errs.append("data_coverage deve ser objecto")
    else:
        for ck in _COVERAGE_KEYS:
            if ck not in cov:
                errs.append(f"data_coverage falta: {ck}")

    rg = data.get("regime_sugerido")
    if rg not in _REGIME_LABELS:
        errs.append(f"regime_sugerido inválido: {rg!r}")

    news = data.get("noticias")
    if not isinstance(news, dict):
        errs.append("noticias deve ser objecto")
    else:
        if not isinstance(news.get("headline_count"), int):
            errs.append("noticias.headline_count deve ser inteiro")
        if news.get("tonalidade") not in _TONALIDADE:
            errs.append(f"noticias.tonalidade inválida: {news.get('tonalidade')!r}")
        sc = news.get("scores")
        if not isinstance(sc, dict):
            errs.append("noticias.scores deve ser objecto")
        else:
            for sk in ("bull_hits", "bear_hits"):
                if not isinstance(sc.get(sk), int):
                    errs.append(f"noticias.scores.{sk} deve ser inteiro")

    macro = data.get("macro")
    if not isinstance(macro, dict):
        errs.append("macro deve ser objecto")
    else:
        if not isinstance(macro.get("indicadores_disponiveis"), bool):
            errs.append("macro.indicadores_disponiveis deve ser booleano")
        if not isinstance(macro.get("nota"), str):
            errs.append("macro.nota deve ser string")

    if not isinstance(data.get("viés_consolidado"), str) or not data.get("viés_consolidado"):
        errs.append("viés_consolidado deve ser string não vazia")

    rz = data.get("razoes")
    if not isinstance(rz, list) or not all(isinstance(x, str) for x in rz):
        errs.append("razoes deve ser lista de strings")

    micro = data.get("micro_xau_m5")
    if micro is not None and not isinstance(micro, dict):
        errs.append("micro_xau_m5 deve ser objecto ou null")

    return errs


def main() -> int:
    path = Path(os.environ.get("REGIME_HANDOFF_INPUT", str(DATA_DIR / "regime_sugerido.json")))
    if not path.is_file():
        print(json.dumps({"ok": False, "error": "ficheiro_em_falta", "path": str(path)}, ensure_ascii=False))
        return 1
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(json.dumps({"ok": False, "error": "json_invalido", "detail": str(e)}, ensure_ascii=False))
        return 1
    if not isinstance(raw, dict):
        print(json.dumps({"ok": False, "error": "raiz_deve_ser_objecto"}, ensure_ascii=False))
        return 1

    errs = validate_regime_payload(raw)
    summary = {
        "ok": len(errs) == 0,
        "path": str(path),
        "regime_sugerido": raw.get("regime_sugerido"),
        "viés_consolidado": raw.get("viés_consolidado"),
        "data_coverage": raw.get("data_coverage"),
        "headline_count": (raw.get("noticias") or {}).get("headline_count"),
        "validation_errors": errs,
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
