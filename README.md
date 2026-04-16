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

## Benzinga: filtro de noticias XAU/USD
- O coletor da Benzinga agora faz duas camadas de selecao:
  1. query por `topics` na API;
  2. filtro local por keywords para garantir que apenas noticias relevantes avancem.
- Keywords padrao:
  - `gold, fed, fomc, inflation, dxy, geopolit, war`
- O script `test_benzinga.py` suporta resposta `application/xml` e `application/json`.

### Executar
```bash
python test_benzinga.py
```

### Configuracoes principais
- `BENZINGA_NEWS_KEYWORDS`: lista CSV usada no filtro final
- `BENZINGA_TOPICS`: lista CSV enviada para a API
- `BENZINGA_ACCEPT`: `application/xml` ou `application/json`
- `BENZINGA_DISPLAY_OUTPUT`: use `full` para expor `body` ao filtro
