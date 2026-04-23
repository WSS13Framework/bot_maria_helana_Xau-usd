# Agentes Maria Helena — procedimentos (sprint actual)

Teoria mensurável (**gaps**, **zonas de procura**, consistência operacional) para treino com **candles próprios**: ver **`docs/gaps_oportunidade_xau.md`** (sem *scraping* ilegal de terceiros; curadoria + features OHLC).

## O que entra neste sprint

| Fonte | Estado típico | Papel do agente (fase inicial) |
|--------|----------------|--------------------------------|
| **MetaAPI** | Ligado | Contexto de preço XAUUSD / volatilidade (dados já no MT5). |
| **Twelve Data** | Teste OK | Cotações DXY, VIX, *rates* conforme plano. |
| **Benzinga** | Em uso | Texto / *headlines* para event risk. |
| **Trading Economics** | Indicadores + mercado (sem calendário API) | Séries macro com **cache** e limite de pedidos. |

**Twitter / X** — **fora** deste sprint por omissão: exige [API paga e regras próprias](https://developer.x.com/) da X Corp., não está no `Makefile` nem no `.env.example`. Só entra se a equipa decidir produto, orçamento e conformidade (LGPD/GDPR, *rate limits*).

---

## Visão de produto — o que os agentes devem fazer (Maria Helena)

O ouro **não se move só com uma linha de preço**: reage a **camadas de informação** (geopolítica, bancos, índices, inflação, actividade / PIB, *supply chain*, *financial chain*, cruzamento com dólar e *rates*). Os agentes existem para **captar**, **classificar** e **ligar** essas nuances ao XAU — não só texto “linear”.

### Cadência sugerida

| Momento | Objectivo |
|---------|-------------|
| **Semanal (ex.: sábado à meia-noite)** | *Batch*: juntar snapshots da semana (ou o último), histórico de preços MT5, e **actualizar** pesos / regras ou **dataset** para treino de modelos (quando existir ML). Definir **timezone** na VPS (ex. `TZ=America/Sao_Paulo`). |
| **Intraday (opcional)** | `make snapshot-mercado` em intervalo curto só para manter `market_snapshot.json` fresco. |

*Cron exemplo — sábado 00:00 (hora do servidor):*

```cron
0 0 * * 6 cd /root/maria-helena && ./venv/bin/python agents/snapshot_mercado.py >> /tmp/snapshot_semanal.log 2>&1
```

(Ajustar `venv`, caminho do clone e, se necessário, `TZ=` no crontab ou no script.)

### Qualificação de notícias e “regras de negócio”

Além de ingerir manchetes (Benzinga, etc.), a fase seguinte é **etiquetar** cada item: temas (geopolítica, bancos centrais, *earnings*, commodities…), **sentido provável para o ouro** (pressão compradora / vendedora / neutro), e **contexto de operação** (ex.: “alerta de volatilidade”, “não é sinal isolado de entrada”) — sempre como **sugestão**, com **validação humana** e política de **risco** antes de qualquer ordem real.

Conceitos como *time to exit*, *buy/sell*, *trade winner* passam a **scores ou rótulos** + limiares definidos pela equipa — não a cliques automáticos no MT5 até estarem escritos e auditados.

### “Treinar a inteligência”

Significa: guardar **histórico** (`market_snapshot.json` + retornos do XAU via MetaAPI / candles) e, quando a equipa decidir, **recalcular** modelos ou pesos (offline na VPS ou noutro ambiente). O snapshot actual é o **primeiro tijolo** desse arquivo de treino.

### Disciplina operacional — *opening* e execução (regra de negócio humana)

A estratégia pode ser **simples**, sobretudo em **setup de abertura** (*opening*): o operador pode actuar **uma vez por semana** ou **em cada abertura relevante** (sessão). Há aberturas distintas — **Ásia**, **Londres**, **Nova Iorque** — e o relógio no MT5 segue o **servidor do broker** (ex.: Hantec); convém fixar no código/documentação **qual janela** (ex. “às 03:00 no servidor do broker”) corresponde ao vosso *setup*, para não misturar fusos.

**Regra de ouro (execução):** depois de abrir a ordem com plano claro (*take* / *stop* definidos na entrada), **não se deve ir alterando a ordem por impulso**. Se se modifica sem critério novo, muitas vezes é sinal de **falta de convicção no plano** — o problema passa a ser **aplicação da estratégia**, não a estratégia em si. Aplicar bem exige **disciplina** e, no manual, **estar presente** no gráfico no momento da execução (seja uma vez por dia ou só nas entradas escolhidas).

**Para a Maria Helena (automação):** quando houver envio de ordens, o desenho deve permitir **política “imutável após entrada”** (SL/TP só pelo plano pré-definido, sem *tweaks* emocionais), **janelas por sessão**, e **registo auditável**. Fases iniciais: só **alerta** ou **demo**, até a equipa validar números e risco.

**Demo “real” (MT5 via MetaAPI):** é **boa prática** um agente de **execução** colocar ordens **só em conta demo** ligada ao mesmo broker/lógica que o live — assim validam se a **ordem é válida** (símbolo, lote, SL/TP, horário de sessão) sem capital real. Bugs de execução em demo são baratos; em live são caros.

---

## Agentes por papel (“Sou notícias”, “Sou macro”, …)

Cada agente com **uma responsabilidade** clara (fácil de testar e de desligar):

| Papel (frase mental) | Função | Estado no repo |
|----------------------|--------|----------------|
| **Sou contexto** | `snapshot_mercado.py` — junta Twelve Data + Benzinga + TE (indicadores). | **Feito** |
| **Sou preço / gaps** | Ler candles XAU, regras de *gap* / zona (`docs/gaps_oportunidade_xau.md`). | **A fazer** |
| **Sou notícias** | Classificar manchetes (tema, impacto ouro) a partir do JSON. | **A fazer** |
| **Sou macro** | Resumir indicadores / regime a partir do snapshot + TE. | **A fazer** |
| **Sou execução (demo)** | Se *setup* + risco + janela baterem, enviar ordem **só em demo** + log imutável. | **A fazer** (último, depois de validar regras) |

**Treino vs operar:** primeiro **rotular** e **simular** (backtest / demo); só depois aumentar autonomia. “Ela posiciona-se e **mantém**” = política de **não mexer** na ordem após entrada, salvo regra escrita (ex.: *time stop*).

---

## Posso já criar os agentes?

**Sim**, desde que o **âmbito da primeira entrega** seja modesto:

1. **Ingestão** — Um módulo por fonte (ou funções) que chama APIs já testadas e devolve dados **normalizados** (dict / `pandas`).
2. **Sem “IA autónoma” no primeiro dia** — Começar por regras + números (ex.: *z-score* de retorno DXY, contagem de palavras‑chave nas notícias), depois embeddings / LLM se fizer sentido.
3. **Saída** — Ficheiro ou log com “regime sugerido” + timestamp, para auditar antes de ligar a ordens reais.

O código dos agentes vive nesta pasta `agents/`; integração com ordens MT5 começa em **conta demo** para validar fluxo; **live** só após auditoria.

---

## Procedimento operacional (ordem)

1. **VPS alinhada** — `git pull` no clone; `.env` com `set_env.py` (regra README: ambiente → VPS).
2. **Testes** — `make test-apis-sem-te-calendario` (e `make test-te-calendar` só quando o plano TE tiver calendário).
3. **Branch** — Trabalhar numa branch (ex. `feature/agentes-ingestao`) e `git push` antes de merge na `main`.
4. **Chaves** — Nunca no Git; rodar chaves se tiverem aparecido em chats.
5. **Twitter** — Se no futuro entrar no roadmap: conta developer X, plano API, variável `TWITTER_*` no `.env` + teste `make test-twitter` (ainda **não** existe).

---

## Snapshot de mercado (implementado)

Script **`agents/snapshot_mercado.py`** — lê o `.env`, chama **Twelve Data** (*quote* por símbolo), **Benzinga** (notícias `gold`, até 8 manchetes) e **Trading Economics** (lista de **indicadores** EUA — pode devolver 403 conforme plano). Grava **`data/market_snapshot.json`** com carimbo UTC. **Não envia ordens.**

Na raiz do repositório:

```bash
make snapshot-mercado
# ou: python3 agents/snapshot_mercado.py
# ou: python3 -m agents.snapshot_mercado
```

Opcional: `TWELVEDATA_SNAPSHOT_SYMBOLS="EUR/USD,DX-Y.NYB"` (vários símbolos separados por vírgula, máx. 8).

**Cron (exemplo a cada 15 min na VPS):**

```cron
*/15 * * * * cd /root/maria-helena && ./venv/bin/python agents/snapshot_mercado.py >> /tmp/snapshot_mercado.log 2>&1
```

(Ajustar caminho do `venv` e do clone.)

## Código implementado (agentes)

| Comando | Ficheiro | Descrição |
|---------|----------|-----------|
| `make features-gaps` | `agents/features_gaps.py` | Lê `data/xauusd_m5.json` (correr `coletar_candles.py` antes), grava `data/features_gaps_m5.json` com *gap* de sessão e *imbalance* 3 velas. Env: `GAP_MIN_ABS_PCT` (default `0.02`), `FEATURES_GAPS_TAIL` (default `80`). |
| `make regime-sugerido` | `agents/regime_sugerido.py` | Lê `data/market_snapshot.json` + `data/features_gaps_m5.json` (opcional), grava `data/regime_sugerido.json` com cobertura de dados, tonalidade simples dos títulos Benzinga, micro (gap/imbalance) e `viés_consolidado` por regras. |
| `make execucao-demo` | `agents/execucao_demo.py` | Exige `MARIA_EXECUCAO_DEMO=1`. Por defeito `MARIA_EXECUCAO_DRY=1` → liga MetaAPI, **não** envia ordem, regista linha em `data/execucao_demo_log.jsonl`. Conta com \"Live\" no nome **aborta** salvo `METAAPI_CONFIRMO_EXECUCAO_EM_CONTA_LIVE=1`. |

Ordem recomendada na VPS: `coletar_candles.py` → `make features-gaps` → `make snapshot-mercado` → `make regime-sugerido` → (opcional) `make execucao-demo` com `.env` de **conta demo** e `DRY=1`.

## Próximo passo técnico sugerido

1. **Ligar `viés_consolidado` / `regime_sugerido` à execução demo** — condicionar `execucao_demo.py` a *flags* explícitas (ex.: só `cautelosamente_*` e lista branca de regimes) + `MARIA_EXECUCAO_DRY=0` em conta **demo**.  
2. **Refinar regras** — mais símbolos no snapshot (DX, yields), curadoria de palavras‑chave, sessão do servidor no JSON de regime.
