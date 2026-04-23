# Maria Helena — comandos padronizados (PC ou VPS, na raiz do repo)
# Ver tudo: make help
#
# Deteção automática:
#   - venv: pasta ./venv (VPS) se existir; senão ./.venv
#   - requisitos: requirements.txt ou, em falta, requirements-ml.txt

PYTHON ?= python3
BRANCH  ?= main

# Preferir venv/ na VPS; no PC típico usa-se .venv após primeiro setup
VENV ?= $(shell if [ -d venv ]; then echo venv; else echo .venv; fi)

PIP := $(VENV)/bin/pip
PY  := $(VENV)/bin/python3

# Primeiro ficheiro que existir (ordem: leve → completo)
REQFILE := $(firstword $(wildcard requirements.txt requirements-ml.txt))

.PHONY: help setup install env-init env-list test-metaapi test-benzinga test-te-calendar test-twelvedata test-apis test-apis-sem-te-calendario snapshot-mercado features-gaps regime-sugerido execucao-demo pull git-status check

help:
	@echo "=== Maria Helena — make (na raiz do repositório) ==="
	@echo ""
	@echo "  VENV detectado:    $(VENV)  (forçar: make X VENV=venv)"
	@echo "  Requisitos:       $(REQFILE) (ou vazio se não houver ficheiro)"
	@echo ""
	@echo "  make setup          Cria venv (se faltar) + pip install -r <requisitos>"
	@echo "  make install        Só pip install"
	@echo "  make env-init       .env a partir de .env.example se não existir"
	@echo "  make env-list       set_env.py list"
	@echo "  make test-metaapi       test_conexao.py"
	@echo "  make test-te-calendar   Trading Economics (calendário)"
	@echo "  make test-twelvedata    Twelve Data (cotação)"
	@echo "  make test-benzinga      Benzinga (notícias)"
	@echo "  make test-apis          MetaAPI + TE calendário + Twelve Data + Benzinga"
	@echo "  make test-apis-sem-te-calendario   só MetaAPI + Twelve Data + Benzinga (plano TE sem API de calendário)"
	@echo "  make snapshot-mercado   grava data/market_snapshot.json (Twelve Data + Benzinga + TE indicadores)"
	@echo "  make features-gaps      features gap/imbalance sobre data/xauusd_m5.json"
	@echo "  make regime-sugerido    agrega snapshot + features → data/regime_sugerido.json (regras)"
	@echo "  make execucao-demo      agente ordem demo (MARIA_EXECUCAO_DEMO=1; DRY por defeito)"
	@echo "  make pull           git pull --ff-only origin BRANCH=$(BRANCH)"
	@echo "  make git-status     git status -sb"
	@echo "  make check          import metaapi + dotenv + pandas"
	@echo ""
	@echo "  make pull BRANCH=cursor/exogenous-shock-flags-a713   # exemplo branch bot"
	@echo ""

setup:
	@test -d "$(VENV)" || $(PYTHON) -m venv "$(VENV)"
	$(PIP) install -U pip
	@if [ -n "$(REQFILE)" ]; then \
	  echo "pip install -r $(REQFILE)"; \
	  $(PIP) install -r "$(REQFILE)"; \
	else \
	  echo "AVISO: sem requirements.txt nem requirements-ml.txt — venv pronto, pacotes do projeto não instalados."; \
	fi
	@echo "OK. Ative: source $(VENV)/bin/activate"

install:
	@if [ -z "$(REQFILE)" ]; then echo "Sem ficheiro de requisitos." >&2; exit 1; fi
	$(PIP) install -r "$(REQFILE)"

env-init:
	@if [ ! -f .env ]; then cp .env.example .env && chmod 600 .env && echo "Criado .env — use: $(PY) set_env.py set CHAVE valor"; else echo ".env já existe (não sobrescrito)"; fi

env-list:
	@$(PY) set_env.py list

test-metaapi:
	@$(PY) test_conexao.py

test-benzinga:
	@$(PY) test_benzinga.py

test-te-calendar:
	@$(PY) test_tradingeconomics_calendar.py

test-twelvedata:
	@$(PY) test_twelvedata_quote.py

test-apis: test-metaapi test-te-calendar test-twelvedata test-benzinga
	@echo "OK — todas as verificações de API concluídas."

# Plano TE sem Economic Calendar na API → 403 em test-te-calendar; use este alvo no dia-a-dia.
test-apis-sem-te-calendario: test-metaapi test-twelvedata test-benzinga
	@echo "OK — APIs sem teste de calendário TE (MetaAPI + Twelve Data + Benzinga)."

snapshot-mercado:
	@$(PY) agents/snapshot_mercado.py

features-gaps:
	@$(PY) agents/features_gaps.py

regime-sugerido:
	@$(PY) agents/regime_sugerido.py

execucao-demo:
	@$(PY) agents/execucao_demo.py

pull:
	git fetch origin
	git pull --ff-only origin "$(BRANCH)"

git-status:
	@git status -sb

check:
	@$(PY) -c "import metaapi_cloud_sdk, dotenv, pandas; print('deps OK')"
