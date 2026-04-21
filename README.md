# Maria Helena — XAU/USD Intelligence System

Sistema de inteligencia para trading de ouro XAU/USD.

## Stack
- MetaAPI: candles em tempo real
- Benzinga Pro: sentiment e macro
- Binance Futures API: execução e consulta de conta

## Setup

1. Crie e ative um ambiente virtual Python:
   - `python3 -m venv .venv`
   - se o comando acima falhar por ausência de `ensurepip`, use: `python3 -m virtualenv .venv`
   - `source .venv/bin/activate`
2. Instale dependências:
   - `pip install -r requirements.txt`
3. Crie o arquivo de configuração:
   - `cp .env.example .env`
4. Preencha chaves reais no `.env` para testar integrações externas.

## Executando os scripts

- `python test_conexao.py` - valida conexão com MetaAPI.
- `python listar_simbolos.py` - lista símbolos de ouro disponíveis na conta.
- `python coletar_candles.py` - coleta candles e salva em `data/xauusd_m5.json`.
- `python test_benzinga.py` - testa consulta de notícias no Benzinga.
- `python executor_direto.py` - testa consulta de conta de futuros na Binance.

> Observação: com valores placeholder no `.env`, os scripts vão interromper com mensagens claras pedindo credenciais válidas.
