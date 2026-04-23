"""
Calcula features de *gap* de sessão e desequilíbrio simples (3 velas) sobre candles XAU M5.

Entrada por defeito: data/xauusd_m5.json (gerado por coletar_candles.py).
Saída: data/features_gaps_m5.json

Regras (v1, documentadas em docs/gaps_oportunidade_xau.md):
  - gap_sessao_pct: (open - close_prev) / close_prev * 100
  - gap_sessao_flag: |gap_sessao_pct| >= limiar (env GAP_MIN_ABS_PCT, default 0.02 = 0,02 %)
  - imbalance_bull: low[i] > high[i-2]
  - imbalance_bear: high[i] < low[i-2]
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


def _f(x: Any) -> float:
    return float(x)


def compute_rows(rows: list[dict[str, Any]], gap_min_abs_pct: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    n = len(rows)
    for i in range(n):
        r = rows[i]
        o, h, lo, c = _f(r["open"]), _f(r["high"]), _f(r["low"]), _f(r["close"])
        if i == 0:
            gap_pct, gap_flag = 0.0, False
        else:
            prev_c = _f(rows[i - 1]["close"])
            gap_pct = ((o - prev_c) / prev_c * 100.0) if prev_c else 0.0
            gap_flag = abs(gap_pct) >= gap_min_abs_pct
        bull = lo > _f(rows[i - 2]["high"]) if i >= 2 else False
        bear = h < _f(rows[i - 2]["low"]) if i >= 2 else False
        out.append(
            {
                "time": r.get("time"),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "gap_sessao_pct": round(gap_pct, 6),
                "gap_sessao_flag": bool(gap_flag),
                "imbalance_bull_3": bool(bull),
                "imbalance_bear_3": bool(bear),
            }
        )
    last = out[-1] if out else {}
    stats = {
        "rows": n,
        "gap_sessao_count": sum(1 for x in out if x["gap_sessao_flag"]),
        "imbalance_bull_count": sum(1 for x in out if x["imbalance_bull_3"]),
        "imbalance_bear_count": sum(1 for x in out if x["imbalance_bear_3"]),
    }
    return out, {"stats": stats, "last_bar": last}


def main() -> int:
    gap_min = float(os.environ.get("GAP_MIN_ABS_PCT", "0.02"))
    inp = Path(os.environ.get("FEATURES_GAPS_INPUT", str(DATA_DIR / "xauusd_m5.json")))
    outp = Path(os.environ.get("FEATURES_GAPS_OUTPUT", str(DATA_DIR / "features_gaps_m5.json")))
    tail = int(os.environ.get("FEATURES_GAPS_TAIL", "80"))

    if not inp.is_file():
        print(
            f"Ficheiro em falta: {inp}\nCorra antes: python3 coletar_candles.py (na raiz do repo, com MetaAPI).",
            file=sys.stderr,
        )
        return 1

    raw = json.loads(inp.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        print("JSON vazio ou formato inesperado (esperada lista de velas).", file=sys.stderr)
        return 1

    rows, meta = compute_rows(raw, gap_min_abs_pct=gap_min)
    tail_rows = rows[-tail:] if len(rows) > tail else rows

    payload = {
        "source": str(inp),
        "gap_min_abs_pct": gap_min,
        "meta": meta,
        "tail": tail_rows,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK → {outp} | velas={meta['stats']['rows']} | gaps_sessao={meta['stats']['gap_sessao_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
