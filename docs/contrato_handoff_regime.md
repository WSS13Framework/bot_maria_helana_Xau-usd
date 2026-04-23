# Contrato de handoff — `regime_sugerido.json`

Ficheiro gerado por [`agents/regime_sugerido.py`](../agents/regime_sugerido.py) (comando `make regime-sugerido`). Serve de **ponte legível** entre a camada Maria (snapshot + features) e qualquer consumidor (operador humano, script no MonetaBot-Pro, ou `context_api` no futuro).

**Local por defeito:** `data/regime_sugerido.json` (no `.gitignore`; cada clone gera o seu).

**Schema JSON:** [`schemas/regime_sugerido.schema.json`](../schemas/regime_sugerido.schema.json).

---

## Campos obrigatórios (v1)

| Campo | Tipo | Significado |
|--------|------|-------------|
| `generated_at_utc` | string (ISO 8601) | Quando o ficheiro foi escrito |
| `data_coverage` | object | `twelve_data`, `benzinga_gold`, `trading_economics_us` — valores como `ok`, `skipped`, `partial`, `error` |
| `regime_sugerido` | string | Rótulo de “quão completo” está o contexto (`contexto_muito_fino` … `contexto_completo`) |
| `noticias.tonalidade` | string | `neutro`, `supportivo_ouro`, `pressao_ouro` |
| `noticias.headline_count` | integer | |
| `macro.indicadores_disponiveis` | boolean | |
| `viés_consolidado` | string | Ex.: `neutro`, `cautelosamente_comprador`, `micro_vendedor`, `neutro_conflito`, … |
| `razoes` | array de strings | Explicação em texto (auditoria) |

Campos opcionais / nulos: `snapshot_generated_at_utc`, `inputs`, `micro_xau_m5` (pode ser `null` se não houver `features_gaps_m5.json`), `nota`.

---

## Quem consome o JSON

### A) Humano no loop (recomendado na Fase 1)

1. Operador abre `regime_sugerido.json` (ou dashboard que o mostre).
2. Cruza com o MonetaBot / MT5 **antes** de qualquer ordem.
3. Nenhum script Moneta altera posições só com base neste ficheiro.

### B) Leitor automático (Fase 2 — opcional)

- Script no MonetaBot-Pro (ou serviço) que **só valida** o JSON, regista em log e eventualmente alimenta `context_api` — **sem** enviar ordens até política explícita.
- Referência de validação no repo Maria: [`agents/regime_handoff_reader.py`](../agents/regime_handoff_reader.py) (`make regime-handoff-read`).

---

## Ingest em `context_api` (MonetaBot — Fase 2, checklist)

Só após revisão explícita de segurança:

- Endpoint **só leitura** ou *internal* (rede privada / firewall).
- **Auth** dedicada (token rotativo); não reutilizar o `.env` do Maria em variáveis públicas do *dashboard*.
- **Rate limit** e corpo máximo (o JSON de regime é pequeno).
- **Idempotência:** o mesmo ficheiro pode ser reenviado; o consumidor não deve disparar efeitos colaterais duplicados.
- **Sem ordens** a partir deste *payload* até política escrita e testes.

## Versão do contrato

Incluir no consumidor a convenção: **v1** = campos acima; evoluções futuras devem acrescentar campos **opcionais** ou `schema_version` (quando existir migração formal).
