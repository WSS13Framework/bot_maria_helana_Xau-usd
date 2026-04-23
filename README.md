# Maria Helena — XAU/USD Intelligence System

Sistema de inteligência para trading de ouro XAU/USD.

## Regra de negócio: ambiente → VPS (clone)

**Sempre** que o ambiente de referência mudar — código no Git, `Makefile`, scripts de teste, `requirements.txt`, regras de deploy ou fluxo documentado — a alteração tem de **replicar-se no clone do projecto na VPS** (servidor de execução, ex. `~/maria-helena`), para o ambiente em produção/testes alinhado com o de desenvolvimento.

| O quê muda | Onde actualizar na VPS |
|------------|-------------------------|
| Código, `Makefile`, README, testes | `git pull` na pasta do clone **ou** `./servidor_atualizar.sh <branch>` na mesma pasta |
| Chaves e segredos (`.env`) | **Não** vão pelo Git. Na VPS: `python3 set_env.py set CHAVE valor` (ou processo seguro acordado), espelhando o que foi definido no ambiente de referência |

Sem este passo, a VPS fica com **versão antiga** ou **credenciais desactualizadas** e os `make test-*` deixam de reflectir a realidade da equipa.

**IDE vs GitHub vs VPS:** o trabalho no Cursor (ou outro PC) e os `git push` actualizam **só** o repositório remoto; **não** substituem `git pull` na pasta do clone **no servidor**. Tabela e notas mais longas: `agents/README.md` → secção *Onde corre o quê*.

**VPS com MonetaBot-Pro (Tubarão) + Maria em paralelo:** inventário e deploy — [`docs/inventario_monetabot_tubarao.md`](docs/inventario_monetabot_tubarao.md), [`docs/deploy_maria_tubarao_vps.md`](docs/deploy_maria_tubarao_vps.md); contrato JSON — [`docs/contrato_handoff_regime.md`](docs/contrato_handoff_regime.md); *cron* e comandos — `agents/README.md` (secção *VPS Tubarão*). **Sem `nano` no servidor:** [`scripts/maria_exchange.sh`](scripts/maria_exchange.sh) (`doctor`, `pull`, `refresh-context`, `env-set …`).

---

## Assinaturas das APIs (o que contratar e onde)

Passo a passo para **criar conta / plano** e obter chaves. Depois grave no `.env` com `python3 set_env.py set NOME valor` (não edite o `.env` com `nano` se preferir o script).

### Ordem exacta de assinatura (macro A → B → C)

1. **A — Trading Economics (primeiro)**  
   - Preços: [tradingeconomics.com/api/pricing.aspx](https://tradingeconomics.com/api/pricing.aspx)  
   - API de calendário (quando o plano incluir): [tradingeconomics.com/api/calendar.aspx](https://tradingeconomics.com/api/calendar.aspx)  
   - Objectivo ideal: CPI / NFP / FOMC com *actual* vs *forecast* (surpresa). *Com plano só indicadores + mercado, usar indicadores e respeitar o teto de pedidos.*

2. **B — Twelve Data Pro (segundo)**  
   - Individual: [twelvedata.com/prime](https://twelvedata.com/prime)  
   - Empresarial: [twelvedata.com/pricing-business](https://twelvedata.com/pricing-business)  
   - Objectivo: DXY, VIX, *rates*, *cross-market* com API estável.

3. **C — Benzinga Pro (terceiro; já em uso na equipa)**  
   - [pro.benzinga.com/pricing](https://pro.benzinga.com/pricing/)  
   - Objectivo: *headlines*, fluxo de notícias, event risk.

| Ordem | Serviço | O que precisa no `.env` | Onde assinar / obter chaves |
|:-----:|---------|-------------------------|-----------------------------|
| — | **MetaAPI** | `METAAPI_TOKEN`, `METAAPI_ACCOUNT_ID` | [metaapi.cloud](https://app.metaapi.cloud/) → token na conta; ID da conta MT5 ligada |
| A | **Trading Economics** | `TRADINGECONOMICS_API_KEY` = `client:secret` **ou** `TRADINGECONOMICS_CLIENT` + `TRADINGECONOMICS_SECRET` | [API pricing](https://tradingeconomics.com/api/pricing.aspx) → painel **API**. O **calendário económico na API** costuma exigir um **nível acima** do pacote “API standard” só com indicadores + mercado (500 req/mês): notícias, alertas, **calendário** e live são frequentemente **exclusões** desse escalão — ver 403 abaixo. |
| B | **Twelve Data** | `TWELVEDATA_API_KEY` | [Conta / API keys](https://twelvedata.com/account/api-keys) — há plano gratuito limitado; DXY/VIX estáveis costumam exigir [Prime](https://twelvedata.com/prime) ou [Business](https://twelvedata.com/pricing-business) conforme símbolos |
| C | **Benzinga Pro** | `BENZINGA_API_KEY`, `BENZINGA_USERNAME` | [Benzinga Pro](https://pro.benzinga.com/pricing/) → API key + username do produto API |

Validação rápida após preencher o `.env`:

```bash
make test-metaapi && make test-te-calendar && make test-twelvedata && make test-benzinga
```

Ou num só comando: `make test-apis`.

Se o plano **Trading Economics** não incluir **calendário na API** (resposta **403** em `make test-te-calendar`), use o conjunto de testes **sem** esse passo:

```bash
make test-apis-sem-te-calendario   # MetaAPI + Twelve Data + Benzinga
```

**Problemas frequentes na VPS**

- `make: *** No rule to make target 'test-apis'` ou **`test-apis-sem-te-calendario`** — o clone está **desactualizado**. `./servidor_atualizar.sh main` ou `make pull`, depois `make help` e confirme as linhas `test-apis` e `test-apis-sem-te-calendario`.
- Trading Economics **401** — quase sempre **valores de exemplo no `.env`** (textos como `COLA_AQUI…`, `CLIENT_REAL`, `CLIENT_DO_SITE` — não são chaves do site). Abra o painel TE, copie **só** o Client e o Secret que lá aparecem, e grave com `set_env.py` **sem** essas frases. Se ainda 401 com valores reais, plano inactivo ou contactar suporte TE.
- Trading Economics **403** (“no access to this feature”) — as chaves estão **correctas**; o **plano não inclui** esse produto na API. Exemplo: plano com **indicadores económicos + mercado financeiro** (cotações, etc.) e **500 pedidos/mês**, mas **sem** calendário, notícias, alertas ou live no contrato — o teste `make test-te-calendar` chama precisamente o **calendário** e a TE devolve 403. Para a prioridade A (CPI/NFP/FOMC no calendário) é preciso um plano que liste **Economic Calendar** / API de calendário (muitas vezes **Enterprise** ou add-on equivalente). Ver [API calendar](https://tradingeconomics.com/api/calendar.aspx) · [pricing](https://tradingeconomics.com/api/pricing.aspx). Até lá, usem os endpoints que o vosso contrato cobre (indicadores / mercados) ou outra fonte para macro.
- Twelve Data **apikey incorrect** com HTTP 200 — a chave no `.env` está errada ou truncada; confira em [API keys](https://twelvedata.com/account/api-keys). Diagnóstico: o teste imprime comprimento e o primeiro carácter Unicode (BOM `U+FEFF` indica ficheiro/cópia estragada).
- Trading Economics: `TE_DIAG=1 make test-te-calendar` imprime o URL final com `c` oculto (confirma que o pedido leva o parâmetro `c`).

## Estratégia com o contrato actual (extrair o máximo)

Com o **plano TE standard** (indicadores + mercado, **sem** calendário na API), a prioridade A original (CPI/NFP via **calendário** TE) **não está disponível por API**. A estratégia passa a usar **só o que está pago e activo**:

| Fonte | O que extrair para XAU/USD |
|--------|----------------------------|
| **MetaAPI** | Candles e microestrutura do **XAUUSD** no MT5 (volatilidade, sessões, spreads); base para sinais e execução. |
| **Trading Economics** | **Indicadores** e séries macro (inflação, emprego, PIB, confiança) por país — úteis para **regime** e contexto, com **atraso** face a um calendário ao vivo. Respeitar o teto (**~500 pedidos/mês**): cache, agregação diária, pedidos só quando necessário. |
| **Twelve Data** | **Cotações** DXY, VIX, yields, pares — stress do dólar e risk-on/off que empurram o ouro. |
| **Benzinga** | **Headlines** e fluxo — event risk (Fed, guerra, bancos) quando o calendário formal não vem da TE. |

**Calendário “surpresa” (actual vs forecast):** sem API de calendário TE, opções são: subir plano mais tarde, usar **notícias + NLP** (Benzinga) como proxy de evento, ou uma fonte de calendário **externa** com licença compatível. Até lá, documentar no código que a camada A por TE é **indicadores + contexto**, não releases ao segundo.

### Agentes autónomos (próxima fase de código)

Procedimentos e âmbito do sprint: **`agents/README.md`**. Gaps/zonas para treino (OHLC): **`docs/gaps_oportunidade_xau.md`**. Snapshot: `make snapshot-mercado` → `data/market_snapshot.json`. Gaps M5: `make features-gaps`. Regime (regras): `make regime-sugerido`. Validar handoff: `make regime-handoff-read`. Demo exec: `make execucao-demo` (ver `agents/README.md`).

Objectivo: **agentes** que consultam de forma autónoma **Benzinga** (C), **Twelve Data** (B) e **Trading Economics** (A — no vosso caso sobretudo **indicadores** enquanto o calendário API não estiver no plano), cruzam sinais e produzem **classificação** (numérica e semântica) sobre **o que move o ouro** no mercado (dólar, *rates*, risco, macro, notícias), para apoio **estatístico** e decisão da Maria Helena.

Pipeline alvo (a implementar): ingestão por fonte → normalização → *features* (ex.: embeddings ou etiquetas para texto Benzinga; *z-scores* ou surpresas onde houver série) → agregação por janela temporal → saída interpretável (scores, regimes, alertas). A ordem de **prioridade de negócio** continua **A → B → C**; a ordem de **assinatura** segue a mesma.

**Testar o que já têm (VPS ou máquina com `.env`):**

```bash
cd /caminho/do/clone && source venv/bin/activate   # ou .venv
make test-apis    # inclui TE calendário — falha com 403 se o plano não tiver esse recurso
make test-apis-sem-te-calendario   # recomendado enquanto o TE for só indicadores/mercado
```

*Nota:* `make test-apis` **para** no primeiro erro; com **403** no calendário TE, Twelve Data e Benzinga **não chegam a correr**. Use `make test-apis-sem-te-calendario` até haver add-on de calendário ou outra fonte.

---

## Ordem das fontes macro e mercado (assinatura / prioridade)

Ordem **exacta** para monitorização e features (surpresas de calendário antes de cross‑market estável; notícias por cima como camada adicional):

| Prioridade | Fonte | Objectivo | Preços / docs |
|:-----------:|--------|-----------|----------------|
| **A (1.º)** | **Trading Economics** | Calendário: CPI, NFP, FOMC, *actual* vs *forecast* (surpresa) | [Preços API](https://tradingeconomics.com/api/pricing.aspx) · [Calendário API](https://tradingeconomics.com/api/calendar.aspx) |
| **B (2.º)** | **Twelve Data Pro** | DXY, VIX, rates, cross‑market com API estável | [Prime (individual)](https://twelvedata.com/prime) · [Business](https://twelvedata.com/pricing-business) |
| **C (3.º)** | **Benzinga Pro** | Headlines / fluxo de notícias (já em uso) | [Benzinga Pro pricing](https://pro.benzinga.com/pricing/) |

Testes de ligação (`.env` com chaves correspondentes):

```bash
make test-te-calendar    # Trading Economics
make test-twelvedata     # Twelve Data (opcional: TWELVEDATA_TEST_SYMBOL=DX-Y.NYB python3 …)
make test-benzinga
```

## Contexto no código (hoje)

| Camada | Ferramenta | Scripts |
|--------|------------|---------|
| Dados MT5 / XAUUSD | MetaAPI (candles, símbolos) | `coletar_candles.py`, `listar_simbolos.py`, `test_conexao.py` |
| Macro A | Trading Economics | `test_tradingeconomics_calendar.py` |
| Mercado B | Twelve Data | `test_twelvedata_quote.py` |
| Notícias C | Benzinga API | `test_benzinga.py` |
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

Criar conta MT5 **demo** via API MetaAPI: `python3 criar_conta_demo_mt5.py --help` — exige `--telefone` (ex. `+351…`) e `--tipo-conta` (valor exacto do MT5 do broker), conforme a [documentação MetaAPI](https://metaapi.cloud/docs/provisioning/api/generateAccount/createMT5DemoAccount/).

## Setup (manual, equivalente ao make)
```bash
cd /caminho/para/bot_maria_helana_Xau-usd
cp .env.example .env
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Credenciais ficam em `.env` na **raiz deste projeto** (`paths.py`). Os dados históricos gravam-se em `data/xauusd_m5.json` (pasta criada automaticamente).
