# Inventário MonetaBot-Pro (VPS Tubarão) — checklist para a equipa

Este ficheiro **não substitui** o SSH ao servidor: é um **modelo** para preencher no Tubarão (ou wiki interna privada). **Não** colar `.env`, tokens nem passwords aqui.

**Contexto:** no servidor `ubuntu-tubarao-trader`, o projecto vive tipicamente em `/root/MonetaBot-Pro`. O repo **Maria Helena** (`bot_maria_helana_Xau-usd`) pode correr **em paralelo** noutro path (ver [deploy_maria_tubarao_vps.md](deploy_maria_tubarao_vps.md)).

---

## 1. Estrutura já observada (abril 2026)

Pastas / ficheiros relevantes (para cruzar com o vosso `find` actual):

| Caminho / artefacto | Notas |
|---------------------|--------|
| `/root/MonetaBot-Pro/bot/agents/` | Agentes Python do *bot* |
| `/root/MonetaBot-Pro/context_api/` | API de contexto (app, workers, providers) |
| `/root/MonetaBot-Pro/orchestrator.py` | Orquestração |
| `/root/MonetaBot-Pro/signal_engine.py`, `signal_bridge.py` | Sinais / ponte |
| `/root/MonetaBot-Pro/moneta_executor.py` | Execução |
| `/root/MonetaBot-Pro/coletar_xauusd.py`, `coletar_dados*.py`, `coletar_dados_agentes.sh` | Recolha de dados |
| `/root/MonetaBot-Pro/train_xauusd_*.py`, `treinar_com_agentes.sh` | Treino |
| `/root/MonetaBot-Pro/data/agentes/` | Dados relacionados com agentes |
| `/root/MonetaBot-Pro/.env` | **Só no servidor** — não versionar |

**Maria Helena neste servidor:** `/root/maria-helena/agents` pode **não existir** até clonarem o repo Maria noutro directório.

---

## 2. Comandos úteis no Tubarão (copiar output para o inventário)

```bash
cd /root/MonetaBot-Pro

# Entrypoints e scripts de arranque
ls -la main.py orchestrator.py start_all.sh coletar_dados_agentes.sh treinar_com_agentes.sh 2>/dev/null

# Agentes
ls -la bot/agents/

# Sinais e execução
ls -la signal_engine.py signal_bridge.py moneta_executor.py 2>/dev/null

# Context API (porta / rotas — preencher após inspeção)
grep -R "uvicorn\|gunicorn\|port\|8000" context_api/ app.py 2>/dev/null | head -40

# Onde escrevem logs / dados (ajustar grep conforme repo)
ls -la data/ logs/ 2>/dev/null
```

---

## 3. Entrypoints — tabela a preencher

| Ficheiro | Quem invoca (*cron*, *systemd*, manual) | Função resumida | Saídas (paths) |
|----------|-------------------------------------------|-----------------|----------------|
| `main.py` | | | |
| `orchestrator.py` | | | |
| `start_all.sh` | | | |
| `coletar_dados_agentes.sh` | | | |
| `treinar_com_agentes.sh` | | | |

---

## 4. `bot/agents/` — módulos

| Ficheiro `.py` | Chamado por | Entrada | Saída |
|----------------|-------------|---------|--------|
| *(preencher)* | | | |

---

## 5. `signal_engine` / `signal_bridge`

| Pergunta | Resposta |
|----------|----------|
| Ficheiros de entrada (JSON, DB, fila)? | |
| Ficheiros / tópicos de saída? | |
| Dependência de `context_api`? | |

---

## 6. `context_api` (HTTP)

| URL base (ex.) | Auth | Endpoints úteis para “contexto mercado” |
|----------------|------|----------------------------------------|
| | | |

---

## 7. Equivalência MonetaBot-Pro ↔ Maria Helena (GitHub)

| Função | MonetaBot-Pro (local típico) | Maria Helena (repo) |
|--------|-------------------------------|------------------------|
| Cotações / *cross-market* (Twelve) | *(procurar em `context_api`, scanners, etc.)* | [`agents/snapshot_mercado.py`](../agents/snapshot_mercado.py) |
| Notícias ouro (Benzinga) | `test_benzinga_demo.py`, integrações no *bot* | `snapshot_mercado.py` |
| Macro TE (indicadores) | *(conforme vosso código)* | `snapshot_mercado.py` |
| Candles XAU M5 | `coletar_xauusd.py` (e afins) | [`coletar_candles.py`](../coletar_candles.py) na raiz |
| Features gap / imbalance | *(treinos / features internos)* | [`agents/features_gaps.py`](../agents/features_gaps.py) |
| Regime / viés por regras | `signal_engine.py`, `unified_logic.py`, `calibrar_regime.py`, … | [`agents/regime_sugerido.py`](../agents/regime_sugerido.py) |
| Execução MT5 | `moneta_executor.py` | [`agents/execucao_demo.py`](../agents/execucao_demo.py) (demo + DRY) |
| Handoff JSON | *(definir leitor no Moneta)* | [`docs/contrato_handoff_regime.md`](contrato_handoff_regime.md), [`agents/regime_handoff_reader.py`](../agents/regime_handoff_reader.py) |

Células “*(procurar…)*” devem ser fechadas pela equipa no inventário real.

---

## 8. Riscos operacionais (checklist)

- [ ] Dois `.env` (Moneta + Maria) — documentar quais chaves são partilhadas e como se rodam.
- [ ] `cron` Moneta vs Maria — horários diferentes (ver [agents/README.md](../agents/README.md) secção Tubarão).
- [ ] Reinícios / updates Ubuntu — janela antes de depender de *cron* novo.
- [ ] IPs e acessos **root** — não publicar em repositórios ou chats abertos.

---

## Entregável da Fase 0

Inventário preenchido (este doc ou cópia na wiki) + decisão: **humano no loop** vs **leitor automático** para [`regime_sugerido.json`](contrato_handoff_regime.md).
