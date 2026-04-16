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

## Bootstrap de ambiente (reproduzível)
```bash
bash scripts/bootstrap_env.sh
```

## Pipeline institucional
```bash
python3 test_benzinga.py
python3 coletar_macro.py
python3 coletar_candles.py
python3 build_dataset.py
python3 label_triple_barrier.py
python3 train_baseline.py
python3 backtest_walkforward.py
python3 risk_execution.py
```

## Robustez e validação institucional
```bash
python3 purged_walkforward.py
python3 robustness_grid.py
python3 holdout_evaluation.py
python3 gate_report.py
```

Esse script de bootstrap cria/usa o venv em `/root/maria-helena/venv`,
instala as dependencias de ML e valida imports criticos.
