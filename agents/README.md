# Agentes Maria Helena — procedimentos (sprint actual)

## O que entra neste sprint

| Fonte | Estado típico | Papel do agente (fase inicial) |
|--------|----------------|--------------------------------|
| **MetaAPI** | Ligado | Contexto de preço XAUUSD / volatilidade (dados já no MT5). |
| **Twelve Data** | Teste OK | Cotações DXY, VIX, *rates* conforme plano. |
| **Benzinga** | Em uso | Texto / *headlines* para event risk. |
| **Trading Economics** | Indicadores + mercado (sem calendário API) | Séries macro com **cache** e limite de pedidos. |

**Twitter / X** — **fora** deste sprint por omissão: exige [API paga e regras próprias](https://developer.x.com/) da X Corp., não está no `Makefile` nem no `.env.example`. Só entra se a equipa decidir produto, orçamento e conformidade (LGPD/GDPR, *rate limits*).

---

## Posso já criar os agentes?

**Sim**, desde que o **âmbito da primeira entrega** seja modesto:

1. **Ingestão** — Um módulo por fonte (ou funções) que chama APIs já testadas e devolve dados **normalizados** (dict / `pandas`).
2. **Sem “IA autónoma” no primeiro dia** — Começar por regras + números (ex.: *z-score* de retorno DXY, contagem de palavras‑chave nas notícias), depois embeddings / LLM se fizer sentido.
3. **Saída** — Ficheiro ou log com “regime sugerido” + timestamp, para auditar antes de ligar a ordens reais.

O código dos agentes vive nesta pasta `agents/`; integração com ordens MT5 fica **depois** de validar offline / em papel.

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

## Próximo passo técnico sugerido

Camada seguinte: ler `market_snapshot.json` + candles MetaAPI e calcular **regime** / scores (regras ou ML), sem executar ordens até validação.
