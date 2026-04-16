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
python3 coletar_contexto_global.py
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

## Execução DEMO (segura/autônoma)
```bash
# Dry run seguro (não envia ordem)
python3 executor_demo_autonomo.py --symbol XAUUSD

# Enviar ordem na DEMO (somente se gate aprovado)
python3 executor_demo_autonomo.py --symbol XAUUSD --execute
```

## Executor seguro DEMO (MetaApi)
```bash
# Simulação (não envia ordem)
python3 executor_demo_seguro.py --side buy --volume 0.01 --sl-points 300 --tp-points 450

# Envio real para DEMO (somente se passar no dry-run)
python3 executor_demo_seguro.py --side buy --volume 0.01 --sl-points 300 --tp-points 450 --execute
```

Por segurança, o executor bloqueia conta LIVE por padrão. Para usar conta específica:
```bash
python3 executor_demo_seguro.py --account-id 862eb0f6-f6b7-4ab0-afdf-0dec095f6c86 --side buy --volume 0.01
```

Esse script de bootstrap cria/usa o venv em `/root/maria-helena/venv`,
instala as dependencias de ML e valida imports criticos.
