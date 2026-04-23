# Maria Helena — XAU/USD Intelligence System

Sistema de inteligência para trading de ouro XAU/USD.

## Assinaturas das APIs (o que contratar e onde)

Passo a passo para **criar conta / plano** e obter chaves. Depois grave no `.env` com `python3 set_env.py set NOME valor` (não edite o `.env` com `nano` se preferir o script).

| Ordem | Serviço | O que precisa no `.env` | Onde assinar / obter chaves |
|:-----:|---------|-------------------------|-----------------------------|
| — | **MetaAPI** | `METAAPI_TOKEN`, `METAAPI_ACCOUNT_ID` | [metaapi.cloud](https://app.metaapi.cloud/) → token na conta; ID da conta MT5 ligada |
| A | **Trading Economics** | `TRADINGECONOMICS_API_KEY` = `client:secret` **ou** `TRADINGECONOMICS_CLIENT` + `TRADINGECONOMICS_SECRET` | [API pricing](https://tradingeconomics.com/api/pricing.aspx) → painel **API**. Não grave texto de exemplo do README (ex. `COLA_AQUI…`) — use os valores hex/strings do site. Calendário REST: `c=client:secret` |
| B | **Twelve Data** | `TWELVEDATA_API_KEY` | [Conta / API keys](https://twelvedata.com/account/api-keys) — há plano gratuito limitado; DXY/VIX estáveis costumam exigir [Prime](https://twelvedata.com/prime) ou [Business](https://twelvedata.com/pricing-business) conforme símbolos |
| C | **Benzinga Pro** | `BENZINGA_API_KEY`, `BENZINGA_USERNAME` | [Benzinga Pro](https://pro.benzinga.com/pricing/) → API key + username do produto API |

Validação rápida após preencher o `.env`:

```bash
make test-metaapi && make test-te-calendar && make test-twelvedata && make test-benzinga
```

Ou num só comando: `make test-apis`.

**Problemas frequentes na VPS**

- `make: *** No rule to make target 'test-apis'` — o clone está **desactualizado**. Na pasta do repo: `./servidor_atualizar.sh main` ou `make pull`, depois `make help` e confirme que aparece `test-apis`.
- Trading Economics **401** — muitas vezes é **chave errada**: confirmou que não colou `COLA_AQUI…` do README? Use `python3 set_env.py set TRADINGECONOMICS_API_KEY 'CLIENT_REAL:SECRET_REAL'`. Depois do `git pull`, o pedido já usa `c=client:secret`. Se ainda 401, plano inactivo ou par incorrecto no painel TE.
- Twelve Data **apikey incorrect** com HTTP 200 — a chave no `.env` está errada ou truncada; confira em [API keys](https://twelvedata.com/account/api-keys). Diagnóstico: o teste imprime comprimento e o primeiro carácter Unicode (BOM `U+FEFF` indica ficheiro/cópia estragada).
- Trading Economics: `TE_DIAG=1 make test-te-calendar` imprime o URL final com `c` oculto (confirma que o pedido leva o parâmetro `c`).

## Ordem das fontes macro e mercado (assinatura / prioridade)

Ordem **exacta** para monitorização e features (surpresas de calendário antes de cross‑market estável; notícias por cima como camada adicional):

| Prioridade | Fonte | Objectivo | Preços / docs |
|:-----------:|--------|-----------|----------------|
| **A (1.º)** | **Trading Economics** | Calendário: CPI, NFP, FOMC, *actual* vs *forecast* (surpresa) | [Preços API](https://tradingeconomics.com/api/pricing.aspx) · [Calendário API](https://tradingeconomics.com/api/calendar.aspx) |
| **B (2.º)** | **Twelve Data Pro** | DXY, VIX, rates, cross‑market com API estável | [Prime (individual)](https://twelvedata.com/prime) · [Business](https://twelvedata.com/pricing-business) |
| **C (3.º)** | **Benzinga Pro** | Headlines / fluxo de notícias (já em uso) | [Benzinga Pro pricing](https://pro.benzinga.com/pricing/) |

Testes de ligação (`.env` com chaves correspondentes):

```bash
make test-te-calendar    # Trading Economics
make test-twelvedata     # Twelve Data (opcional: TWELVEDATA_TEST_SYMBOL=DX-Y.NYB python3 …)
make test-benzinga
```

## Contexto no código (hoje)

| Camada | Ferramenta | Scripts |
|--------|------------|---------|
| Dados MT5 / XAUUSD | MetaAPI (candles, símbolos) | `coletar_candles.py`, `listar_simbolos.py`, `test_conexao.py` |
| Macro A | Trading Economics | `test_tradingeconomics_calendar.py` |
| Mercado B | Twelve Data | `test_twelvedata_quote.py` |
| Notícias C | Benzinga API | `test_benzinga.py` |
| Outro mercado (teste) | Binance Futures (USDT) | `executor_direto.py` — não é XAUUSD no broker MT5 |

O README mencionava PyTorch; **ainda não há modelo ML no repositório** — só integrações de dados e testes de ligação.

## Fluxo padrão (não repetir setup à mão)

Na **raiz do clone** (PC ou VPS):

```bash
make help              # lista comandos
make setup             # primeiro uso: venv + pip (detecta ./venv ou ./.venv e requirements.txt / requirements-ml.txt)
make env-init          # .env a partir do exemplo, se ainda não existir
source .venv/bin/activate   # ou: source venv/bin/activate
make test-metaapi
```

Atualizar código (Git): `make pull BRANCH=main` ou `make pull BRANCH=cursor/exogenous-shock-flags-a713`.  
Ou usar `./servidor_atualizar.sh <branch>` na VPS.

Variáveis de ambiente: `python3 set_env.py …` (ver `set_env.py --help`).

Criar conta MT5 **demo** via API MetaAPI: `python3 criar_conta_demo_mt5.py --help` — exige `--telefone` (ex. `+351…`) e `--tipo-conta` (valor exacto do MT5 do broker), conforme a [documentação MetaAPI](https://metaapi.cloud/docs/provisioning/api/generateAccount/createMT5DemoAccount/).

## Setup (manual, equivalente ao make)
```bash
cd /caminho/para/bot_maria_helana_Xau-usd
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Credenciais ficam em `.env` na **raiz deste projeto** (`paths.py`). Os dados históricos gravam-se em `data/xauusd_m5.json` (pasta criada automaticamente).
