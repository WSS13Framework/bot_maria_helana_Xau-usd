# Maria Helena — comandos padronizados (PC ou VPS, na raiz do repo)
# Ver tudo: make help

PYTHON       ?= python3
VENV         ?= .venv
PIP          := $(VENV)/bin/pip
PY           := $(VENV)/bin/python3
BRANCH       ?= main

.PHONY: help setup install env-init env-list test-metaapi test-benzinga pull git-status check

help:
	@echo "=== Maria Helena — make (sempre na pasta do repositório) ==="
	@echo ""
	@echo "  make setup          Cria $(VENV), instala requirements.txt"
	@echo "  make install        Só pip install (venv já existe)"
	@echo "  make env-init       Copia .env.example -> .env se .env não existir"
	@echo "  make env-list       Lista chaves do .env (mascarado) via set_env.py"
	@echo "  make test-metaapi   test_conexao.py"
	@echo "  make test-benzinga  test_benzinga.py"
	@echo "  make pull           git pull --ff-only origin BRANCH=$(BRANCH)"
	@echo "  make git-status     git status -sb"
	@echo "  make check          Importa deps principais no venv"
	@echo ""
	@echo "Na VPS o venv costuma chamar-se venv/:  make setup VENV=venv"
	@echo "Branch do bot (exemplo):               make pull BRANCH=cursor/exogenous-shock-flags-a713"
	@echo ""

setup:
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	$(PIP) install -U pip
	$(PIP) install -r requirements.txt
	@echo "OK. Ative: source $(VENV)/bin/activate"

install:
	$(PIP) install -r requirements.txt

env-init:
	@if [ ! -f .env ]; then cp .env.example .env && chmod 600 .env && echo "Criado .env — use: $(PY) set_env.py set CHAVE valor"; else echo ".env já existe (não sobrescrito)"; fi

env-list:
	@$(PY) set_env.py list

test-metaapi:
	@$(PY) test_conexao.py

test-benzinga:
	@$(PY) test_benzinga.py

pull:
	git fetch origin
	git pull --ff-only origin "$(BRANCH)"

git-status:
	@git status -sb

check:
	@$(PY) -c "import metaapi_cloud_sdk, dotenv, pandas; print('deps OK')"
