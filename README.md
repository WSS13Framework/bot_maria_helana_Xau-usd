# Maria Helena — XAU/USD Intelligence System

Sistema de inteligencia para trading de ouro XAU/USD.

## Stack
- MetaAPI: candles em tempo real
- Benzinga Pro: sentiment e macro
- PyTorch: modelo de ML

## Setup
```bash
cp .env.example .env
```

## Bootstrap (Cloud/Servidor)
```bash
bash scripts/bootstrap_env.sh
```

Esse script cria/usa o venv em `/root/maria-helena/venv`, instala as dependencias
de ML e valida imports criticos.
