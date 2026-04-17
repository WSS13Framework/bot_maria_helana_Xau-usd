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

## RAG com Pinecone (memória vetorial)
```bash
# 1) indexar contexto local (notícias relevantes + métricas)
python3 rag_pinecone.py index

# 2) consultar contexto por pergunta
python3 rag_pinecone.py query --text "geopolitical risk and gold direction"
```

## RAG com fallback automático (Pinecone -> FAISS/SQLite)
```bash
# Indexação automática (usa Pinecone se chave disponível; senão usa local)
python3 rag_retriever.py index --backend auto

# Consulta automática
python3 rag_retriever.py query --backend auto --text "gold fed inflation risk regime" --top-k 10
```

## Knowledge Graph com Neo4j
```bash
# sincronizar dados locais no grafo
python3 kg_neo4j.py sync

# consultar eventos de maior risco recente
python3 kg_neo4j.py query --cypher "MATCH (e:MarketEvent) RETURN e.source, e.eventTime, e.riskFlag ORDER BY e.eventTime DESC LIMIT 10"
```

## Contexto global (EUA + Europa + Asia + minerais + estrutura produtiva)
```bash
python3 coletar_contexto_global.py --fred-api-key SUA_FRED_API_KEY
```

Para habilitar no dataset:
```bash
python3 build_dataset.py
```

## Execução DEMO (segura/autônoma)
```bash
# Dry run seguro (não envia ordem)
python3 executor_demo_autonomo.py --symbol XAUUSD

# Enviar ordem na DEMO (somente se gate aprovado)
python3 executor_demo_autonomo.py --symbol XAUUSD --execute
```

Dica de protecao institucional: limitar lote maximo:
```bash
python3 executor_demo_autonomo.py --symbol XAUUSD --max-volume-cap 0.05
```

## Painel SaaS (sem linha de comando)
```bash
streamlit run dashboard_saas.py --server.port 8501 --server.address 0.0.0.0
```

O painel mostra:
- saldo/equity e informacoes de conta
- posicoes abertas por simbolo
- grafico de candles recentes (espelho de mercado)
- status do gate institucional
- sinal atual (`p_long`, `p_short`) e lote sugerido por risco
- botoes para dry-run e execucao do robo autonomo

## Gestão institucional de posição aberta
```bash
# Apenas diagnostico (sem modificar posição)
python3 gerenciar_posicao_autonomo.py --account-id SEU_ACCOUNT_ID --symbol XAUUSD

# Breakeven e trailing em dry-run
python3 gerenciar_posicao_autonomo.py --account-id SEU_ACCOUNT_ID --symbol XAUUSD --enable-breakeven --enable-trailing

# Aplicar ajuste real de SL (somente quando validado)
python3 gerenciar_posicao_autonomo.py --account-id SEU_ACCOUNT_ID --symbol XAUUSD --enable-breakeven --enable-trailing --execute
```

## Feedback contínuo + retrain em lote (institucional)
```bash
# Registrar feedback manual (override / observações)
python3 feedback_logger.py log --event-type manual_feedback --account-id SUA_CONTA --symbol XAUUSD --status approved --note "contexto macro favorável"

# Rodar scheduler de retrain (só treina se houver dados novos + cooldown vencido)
python3 retrain_scheduler.py run --feedback-file /root/maria-helena/data/trade_feedback.jsonl --min-new-events 25 --min-hours-between-runs 12
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
