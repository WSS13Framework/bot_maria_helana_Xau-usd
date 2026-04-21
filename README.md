# Maria Helena — XAU/USD Intelligence System

Sistema de inteligencia para trading de ouro XAU/USD.

## Stack
- MetaAPI: candles em tempo real
- Benzinga Pro: sentiment e macro
- PyTorch: modelo de ML

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Se `python3 -m venv` falhar em Ubuntu minimal, instale:
```bash
sudo apt-get update
sudo apt-get install -y python3.12-venv
```

Preencha o arquivo `.env` com suas chaves reais:
- `METAAPI_TOKEN`
- `METAAPI_ACCOUNT_ID`
- `BENZINGA_API_KEY`
- `BINANCE_API_KEY`
- `BINANCE_SECRET_KEY`

## Run
Scripts de verificação de ambiente:

```bash
python test_conexao.py
python test_benzinga.py
python executor_direto.py
python listar_simbolos.py
python coletar_candles.py
```
