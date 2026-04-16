#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/root/maria-helena}"
VENV_DIR="${VENV_DIR:-$PROJECT_DIR/venv}"
REQUIREMENTS_FILE="${REQUIREMENTS_FILE:-$PROJECT_DIR/requirements-ml.txt}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "[bootstrap] Project dir: $PROJECT_DIR"
echo "[bootstrap] Venv dir: $VENV_DIR"
echo "[bootstrap] Requirements: $REQUIREMENTS_FILE"

if [[ ! -d "$PROJECT_DIR" ]]; then
  echo "[bootstrap][erro] Diretorio nao encontrado: $PROJECT_DIR"
  exit 1
fi

if [[ ! -f "$REQUIREMENTS_FILE" ]]; then
  echo "[bootstrap][erro] Arquivo de requirements nao encontrado: $REQUIREMENTS_FILE"
  exit 1
fi

if [[ ! -d "$VENV_DIR" ]]; then
  echo "[bootstrap] Criando virtualenv..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1090
source "$VENV_DIR/bin/activate"

python -m pip install --upgrade pip setuptools wheel
python -m pip install -r "$REQUIREMENTS_FILE"

python - <<'PY'
import importlib
import sys

required = [
    "pandas",
    "numpy",
    "sklearn",
    "catboost",
    "streamlit",
    "plotly",
    "requests",
    "dotenv",
    "metaapi_cloud_sdk",
    "pinecone",
    "sentence_transformers",
]

missing = []
for module in required:
    try:
        importlib.import_module(module)
    except Exception:
        missing.append(module)

if missing:
    print(f"[bootstrap][erro] Modulos faltando: {missing}")
    sys.exit(1)

print("[bootstrap] Validacao de imports OK.")
PY

echo "[bootstrap] Ambiente pronto."
