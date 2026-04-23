#!/usr/bin/env bash
# Trocas rápidas na VPS ou no PC — sem nano, menos erro humano (cd / venv).
# Uso (sempre na raiz do repo ou com path absoluto ao script):
#   chmod +x scripts/maria_exchange.sh
#   ./scripts/maria_exchange.sh doctor
#   ./scripts/maria_exchange.sh pull
#   ./scripts/maria_exchange.sh refresh-context
#   ./scripts/maria_exchange.sh env-set TWELVEDATA_API_KEY '...'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
  cat >&2 <<'EOF'
maria_exchange.sh — trocas rápidas sem nano (usa Makefile + set_env.py).

Comandos:
  doctor              Verifica repo, .env, venv e make.
  pull [branch]       git fetch + checkout + pull --ff-only (default: main).
  install             pip install -r requisitos (via make install).
  test-apis           make test-apis-sem-te-calendario
  snapshot            make snapshot-mercado
  features            make features-gaps (precisa data/xauusd_m5.json)
  regime              make regime-sugerido
  handoff             make regime-handoff-read
  refresh-context     snapshot → regime → handoff (sem candles)
  refresh-bars        features → refresh-context
  env-set KEY VAL     python3 set_env.py set KEY VAL (sem editor)
  env-list            python3 set_env.py list
EOF
  exit "${1:-0}"
}

cmd="${1:-}"
shift || true

case "$cmd" in
  ""|-h|--help|help) usage 0 ;;
  doctor)
    echo "ROOT=$ROOT"
    if [[ ! -f .env ]]; then echo "AVISO: .env em falta — make env-init ou copiar de .env.example" >&2; else echo "OK: .env presente"; fi
    if [[ -x venv/bin/python3 ]]; then echo "OK: venv/bin/python3"; elif [[ -x .venv/bin/python3 ]]; then echo "OK: .venv/bin/python3"; else echo "AVISO: sem ./venv nem ./.venv — correr make setup" >&2; fi
    if make -C "$ROOT" -n snapshot-mercado >/dev/null 2>&1; then echo "OK: Makefile (alvo snapshot-mercado)"; else echo "AVISO: make não resolve snapshot-mercado" >&2; fi
    ;;
  pull)
    BRANCH="${1:-main}"
    exec bash "$ROOT/servidor_atualizar.sh" "$BRANCH"
    ;;
  install)
    make -C "$ROOT" install
    ;;
  test-apis)
    make -C "$ROOT" test-apis-sem-te-calendario
    ;;
  snapshot)
    make -C "$ROOT" snapshot-mercado
    ;;
  features)
    make -C "$ROOT" features-gaps
    ;;
  regime)
    make -C "$ROOT" regime-sugerido
    ;;
  handoff)
    make -C "$ROOT" regime-handoff-read
    ;;
  refresh-context)
    make -C "$ROOT" snapshot-mercado
    make -C "$ROOT" regime-sugerido
    make -C "$ROOT" regime-handoff-read
    ;;
  refresh-bars)
    make -C "$ROOT" features-gaps
    make -C "$ROOT" snapshot-mercado
    make -C "$ROOT" regime-sugerido
    make -C "$ROOT" regime-handoff-read
    ;;
  env-set)
    if [[ $# -lt 2 ]]; then echo "Uso: env-set CHAVE valor" >&2; exit 1; fi
    if [[ -x .venv/bin/python3 ]]; then PY=(.venv/bin/python3); elif [[ -x venv/bin/python3 ]]; then PY=(venv/bin/python3); else PY=(python3); fi
    exec "${PY[0]}" "$ROOT/set_env.py" set "$@"
    ;;
  env-list)
    if [[ -x .venv/bin/python3 ]]; then PY=(.venv/bin/python3); elif [[ -x venv/bin/python3 ]]; then PY=(venv/bin/python3); else PY=(python3); fi
    exec "${PY[0]}" "$ROOT/set_env.py" list
    ;;
  *)
    echo "Comando desconhecido: $cmd" >&2
    usage 1
    ;;
esac
