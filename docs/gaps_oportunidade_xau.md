# Gaps, zonas de procura e consistência (XAU/USD) — base para treinar a Maria Helena

Este ficheiro **não** substitui cursos pagos nem autoriza *scraping* massivo de sites de trading (ToS, direitos de autor, ruído). É um **mapa conceptual** + **features mensuráveis** a partir dos **vossos próprios candles** (MetaAPI / MT5), para depois **rotular** histórico e treinar modelos **em dados que vocês controlam**.

---

## 1. O que queremos que ela “aprenda”

| Ideia (linguagem de mercado) | Tradução mensurável |
|-----------------------------|---------------------|
| **Zona de procura** (*demand*) | Região de preço onde, no passado, a compra absorveu venda (estrutura: fundos ascendentes, rejeição de baixos, consolidação antes de impulso). |
| **Gap / desequilíbrio** | Trecho do gráfico onde poucos negócios ocorreram entre dois preços (ex.: *opening gap*; em análise de três candles, “buraco” entre máx/mín de velas adjacentes). |
| **Oportunidade com consistência** | O mesmo *setup* repetido com **regras fixas** (sessão, hora servidor broker, SL/TP na entrada, sem mexer na ordem) — ver `agents/README.md` (disciplina operacional). |

---

## 2. Features a calcular a partir de OHLC(V) (sem “raspar” a internet)

Todas derivam de séries temporais que já podem vir do MT5:

1. **Gaps clássicos de abertura** — `open[t]` vs `close[t-1]` (ou último fecho da sessão anterior); magnitude relativa ao ATR.
2. **Desequilíbrio em 3 velas (ideia geral)** — comparar `low[i]`, `high[i±1]` para detectar sobreposição vazia entre extremos (literatura pública descreve variantes; implementar **uma** definição escrita pela equipa e manter‑na estável).
3. **Zonas por estrutura** — últimos *N* *swing lows* / *swing highs*; largura da zona = percentil do range das velas no bloco.
4. **Contexto de sessão** — etiqueta `Ásia | Londres | NY` a partir do **tempo do servidor do broker** (ex.: Hantec).
5. **Volatilidade local** — ATR(14) ou desvio padrão dos retornos na janela do *setup*.
6. **Volume** — se o feed MT5 tiver volume por vela, usar; senão, proxies (contagem de ticks se disponível).

Assim o “ensino” é: **juntar candles + regras → rótulos** (ex.: `zona_procura=1`, `gap_bull=1`), e opcionalmente um **classificador** treinado nesses rótulos.

---

## 3. Pipeline de treino (recomendado)

1. **Exportar histórico** XAU (ex.: M5) para `data/` (script existente ou novo, só leitura MetaAPI).
2. **Definir regras** de rótulo em Python (funções puras, testadas com exemplos manuais de 10–20 velas).
3. **Gerar `dataset_zonas.parquet`** (colunas: timestamp, preços, features, `label`).
4. **Treinar** (logistic regression / gradient boosting primeiro; *deep learning* só se houver volume e validação *walk-forward*).
5. **Inferência em tempo real** — só **sugestão** + log; ordens reais só com política de risco aprovada.

---

## 4. Leitura humana (curadoria, não *scraping* automático)

Para aprofundar teoria, a equipa pode **seleccionar** manualmente fontes gerais (livros, papers de microestrutura de mercados, documentação de corretoras) e resumir **em próprias palavras** o que vão codificar. Termos de pesquisa úteis (Google Scholar / livrarias): *price discovery*, *order flow imbalance*, *support resistance auction*, *session returns gold futures*.

---

## 5. Ligação ao código actual

- **`data/market_snapshot.json`** — contexto macro/mercado/notícias.  
- **Candles XAU** — onde nascem gaps e zonas.  
- Próximo passo de código sugerido: `agents/features_zonas.py` (ou `tools/export_candles.py` alargado) que lê candles e escreve features + rótulos por regra.

Quando quiserem, o próximo *commit* pode ser só esse módulo de **features + rótulos por regras**, sem ML ainda.
