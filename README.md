# Maria Helena — XAU/USD Intelligence System

Sistema de inteligência para trading de ouro XAU/USD.

## Contexto no código (hoje)

| Camada | Ferramenta | Scripts |
|--------|------------|---------|
| Dados MT5 / XAUUSD | MetaAPI (candles, símbolos) | `coletar_candles.py`, `listar_simbolos.py`, `test_conexao.py` |
| Notícias / ouro | Benzinga API | `test_benzinga.py` |
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

## Setup (manual, equivalente ao make)
```bash
cd /caminho/para/bot_maria_helana_Xau-usd
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Credenciais ficam em `.env` na **raiz deste projeto** (`paths.py`). Os dados históricos gravam-se em `data/xauusd_m5.json` (pasta criada automaticamente).
