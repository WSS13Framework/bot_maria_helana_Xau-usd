#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/maria-helena}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
LOG_DIR="${LOG_DIR:-$PROJECT_DIR/data}"
DATA_DIR="${DATA_DIR:-$PROJECT_DIR/data}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="${ENV_FILE:-$PROJECT_DIR/.env}"

DECISION_THRESHOLD="${DECISION_THRESHOLD:-0.65}"
SPREAD_BPS="${SPREAD_BPS:-5}"
SLIPPAGE_BPS="${SLIPPAGE_BPS:-5}"
EXOGENOUS_SHOCK_THRESHOLD="${EXOGENOUS_SHOCK_THRESHOLD:-0.55}"

RUN_EXECUTOR_DRY="${RUN_EXECUTOR_DRY:-1}"
RUN_EXECUTOR_LIVE="${RUN_EXECUTOR_LIVE:-0}"
EXECUTOR_SYMBOL="${EXECUTOR_SYMBOL:-XAUUSD}"
DEMO_RAG_ENABLED="${DEMO_RAG_ENABLED:-1}"
DEMO_RAG_TOP_K="${DEMO_RAG_TOP_K:-3}"
DEMO_RAG_PREFER="${DEMO_RAG_PREFER:-pinecone}"
DEMO_ENFORCE_SESSION_WINDOW="${DEMO_ENFORCE_SESSION_WINDOW:-1}"
DEMO_SESSION_WINDOWS="${DEMO_SESSION_WINDOWS:-06:00-09:00,12:00-16:30}"
DEMO_FRIDAY_CLOSE_HOUR_UTC="${DEMO_FRIDAY_CLOSE_HOUR_UTC:-21.0}"
DEMO_SUNDAY_OPEN_HOUR_UTC="${DEMO_SUNDAY_OPEN_HOUR_UTC:-22.0}"
DEMO_ALLOW_ROLLOVER_WINDOW="${DEMO_ALLOW_ROLLOVER_WINDOW:-0}"
DEMO_ENFORCE_VOLATILITY_GUARD="${DEMO_ENFORCE_VOLATILITY_GUARD:-1}"
DEMO_VOLATILITY_WARNING_RATIO="${DEMO_VOLATILITY_WARNING_RATIO:-1.6}"
DEMO_VOLATILITY_MAX_RATIO="${DEMO_VOLATILITY_MAX_RATIO:-2.4}"
DEMO_VOLATILITY_THRESHOLD_ADD="${DEMO_VOLATILITY_THRESHOLD_ADD:-0.03}"
DEMO_VOLATILITY_RISK_MULT="${DEMO_VOLATILITY_RISK_MULT:-0.70}"
DEMO_MIN_VOLATILITY_RISK_MULT="${DEMO_MIN_VOLATILITY_RISK_MULT:-0.40}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF'
Uso:
  scripts/run_daily_shadow.sh

Variaveis de ambiente suportadas:
  PROJECT_DIR (default: /root/maria-helena)
  VENV_DIR (default: $PROJECT_DIR/venv)
  LOG_DIR (default: $PROJECT_DIR/data)
  DATA_DIR (default: $PROJECT_DIR/data)
  ENV_FILE (default: $PROJECT_DIR/.env)
  DECISION_THRESHOLD (default: 0.65)
  SPREAD_BPS (default: 5)
  SLIPPAGE_BPS (default: 5)
  EXOGENOUS_SHOCK_THRESHOLD (default: 0.55)
  RUN_EXECUTOR_DRY (default: 1)
  RUN_EXECUTOR_LIVE (default: 0)
  EXECUTOR_SYMBOL (default: XAUUSD)
  DEMO_RAG_ENABLED (default: 1)
  DEMO_RAG_TOP_K (default: 3)
  DEMO_RAG_PREFER (default: pinecone)
  DEMO_ENFORCE_SESSION_WINDOW (default: 1)
  DEMO_SESSION_WINDOWS (default: 06:00-09:00,12:00-16:30)
  DEMO_FRIDAY_CLOSE_HOUR_UTC (default: 21.0)
  DEMO_SUNDAY_OPEN_HOUR_UTC (default: 22.0)
  DEMO_ALLOW_ROLLOVER_WINDOW (default: 0)
  DEMO_ENFORCE_VOLATILITY_GUARD (default: 1)
  DEMO_VOLATILITY_WARNING_RATIO (default: 1.6)
  DEMO_VOLATILITY_MAX_RATIO (default: 2.4)
  DEMO_VOLATILITY_THRESHOLD_ADD (default: 0.03)
  DEMO_VOLATILITY_RISK_MULT (default: 0.70)
  DEMO_MIN_VOLATILITY_RISK_MULT (default: 0.40)

Exemplo:
  PROJECT_DIR=/workspace RUN_EXECUTOR_DRY=1 RUN_EXECUTOR_LIVE=0 scripts/run_daily_shadow.sh
EOF
  exit 0
fi

mkdir -p "$LOG_DIR"
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_LOG="$LOG_DIR/daily_shadow_${RUN_TS}.log"

log() {
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$RUN_LOG"
}

run_cmd() {
  log "RUN: $*"
  "$@" 2>&1 | tee -a "$RUN_LOG"
}

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "Diretorio do projeto nao encontrado: $PROJECT_DIR" >&2
  exit 1
fi

cd "$PROJECT_DIR"
if [[ -d "$VENV_DIR" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_DIR/bin/activate"
  PYTHON_BIN="python3"
fi

log "Inicio do daily shadow run"
log "Projeto: $PROJECT_DIR"
log "Data dir: $DATA_DIR"
log "Env file: $ENV_FILE"

run_cmd "$PYTHON_BIN" test_benzinga.py
run_cmd "$PYTHON_BIN" coletar_macro.py
run_cmd "$PYTHON_BIN" coletar_macro_eventos.py
run_cmd "$PYTHON_BIN" coletar_contexto_global.py
run_cmd "$PYTHON_BIN" coletar_candles.py
run_cmd "$PYTHON_BIN" build_dataset.py --exogenous-shock-threshold "$EXOGENOUS_SHOCK_THRESHOLD"
run_cmd "$PYTHON_BIN" label_triple_barrier.py
run_cmd "$PYTHON_BIN" train_baseline.py --decision-threshold "$DECISION_THRESHOLD"
run_cmd "$PYTHON_BIN" backtest_walkforward.py --confidence-threshold "$DECISION_THRESHOLD" --spread-bps "$SPREAD_BPS" --slippage-bps "$SLIPPAGE_BPS"
run_cmd "$PYTHON_BIN" risk_execution.py
run_cmd "$PYTHON_BIN" purged_walkforward.py --embargo-bars 48
run_cmd "$PYTHON_BIN" robustness_grid.py
run_cmd "$PYTHON_BIN" holdout_evaluation.py --decision-threshold "$DECISION_THRESHOLD" --spread-bps "$SPREAD_BPS" --slippage-bps "$SLIPPAGE_BPS"
run_cmd "$PYTHON_BIN" gate_report.py
run_cmd "$PYTHON_BIN" rag_retriever.py --env-file "$ENV_FILE" index-local

EXECUTOR_RAG_ARGS=()
if [[ "$DEMO_RAG_ENABLED" == "1" ]]; then
  EXECUTOR_RAG_ARGS+=(--enable-rag-evidence --rag-top-k "$DEMO_RAG_TOP_K" --rag-prefer "$DEMO_RAG_PREFER")
fi

EXECUTOR_SESSION_ARGS=()
if [[ "$DEMO_ENFORCE_SESSION_WINDOW" == "1" ]]; then
  EXECUTOR_SESSION_ARGS+=(--enforce-session-window --session-windows "$DEMO_SESSION_WINDOWS" --friday-close-hour-utc "$DEMO_FRIDAY_CLOSE_HOUR_UTC" --sunday-open-hour-utc "$DEMO_SUNDAY_OPEN_HOUR_UTC")
  if [[ "$DEMO_ALLOW_ROLLOVER_WINDOW" == "1" ]]; then
    EXECUTOR_SESSION_ARGS+=(--allow-rollover-window)
  fi
fi

EXECUTOR_VOL_ARGS=()
if [[ "$DEMO_ENFORCE_VOLATILITY_GUARD" == "1" ]]; then
  EXECUTOR_VOL_ARGS+=(--enforce-volatility-guardrail --volatility-warning-ratio "$DEMO_VOLATILITY_WARNING_RATIO" --volatility-max-ratio "$DEMO_VOLATILITY_MAX_RATIO" --volatility-threshold-add "$DEMO_VOLATILITY_THRESHOLD_ADD" --volatility-risk-mult "$DEMO_VOLATILITY_RISK_MULT" --min-volatility-risk-mult "$DEMO_MIN_VOLATILITY_RISK_MULT")
fi

if [[ "$RUN_EXECUTOR_DRY" == "1" ]]; then
  run_cmd "$PYTHON_BIN" executor_demo_autonomo.py --env-file "$ENV_FILE" --symbol "$EXECUTOR_SYMBOL" "${EXECUTOR_RAG_ARGS[@]}" "${EXECUTOR_SESSION_ARGS[@]}" "${EXECUTOR_VOL_ARGS[@]}"
fi

if [[ "$RUN_EXECUTOR_LIVE" == "1" ]]; then
  run_cmd "$PYTHON_BIN" executor_demo_autonomo.py --env-file "$ENV_FILE" --symbol "$EXECUTOR_SYMBOL" "${EXECUTOR_RAG_ARGS[@]}" "${EXECUTOR_SESSION_ARGS[@]}" "${EXECUTOR_VOL_ARGS[@]}" --execute
fi

log "Daily shadow run concluido com sucesso"
