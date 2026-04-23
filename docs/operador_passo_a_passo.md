# Operador — passo a passo (o que fazer e onde)

Tudo abaixo assume que estás **dentro da pasta do clone** do Maria Helena (ex.: `/opt/maria-helena-xau` na VPS ou a pasta do projecto no PC).

---

## A) Primeira vez nesta máquina (só uma vez)

```bash
cd /CAMINHO/DO/CLONE/bot_maria_helana_Xau-usd

git pull --ff-only origin main

make setup
make env-init
chmod +x scripts/maria_exchange.sh
```

Definir chaves **sem abrir `nano`** (repete uma linha por chave; troca os `…` pelos valores reais):

```bash
./scripts/maria_exchange.sh env-set METAAPI_TOKEN '…'
./scripts/maria_exchange.sh env-set METAAPI_ACCOUNT_ID '…'
./scripts/maria_exchange.sh env-set TWELVEDATA_API_KEY '…'
./scripts/maria_exchange.sh env-set BENZINGA_API_KEY '…'
```

Testar APIs (não envia ordens):

```bash
make maria-doctor
make test-apis-sem-te-calendario
```

Se `maria-doctor` avisar que falta `.env`, corre de novo `make env-init` e volta a gravar as chaves com `env-set`.

---

## B) Todos os dias (ou várias vezes ao dia) — contexto sem candles

Isto actualiza notícias/cotações no snapshot, recalcula o regime e valida o JSON:

```bash
cd /CAMINHO/DO/CLONE/bot_maria_helana_Xau-usd
git pull --ff-only origin main
make maria-refresh-context
```

É o mesmo que:

```bash
./scripts/maria_exchange.sh refresh-context
```

---

## C) Quando quiseres gaps no M5 (precisa de velas MetaAPI)

**1.** Recolher velas (MetaAPI):

```bash
make coletar-candles
```

**2.** Recalcular features + snapshot + regime:

```bash
make maria-refresh-bars
```

Se o passo 1 falhar (conta, rede), o passo 2 também pode falhar — resolve primeiro o `coletar_candles`.

---

## D) Demo MetaAPI sem ordem real (DRY)

```bash
make maria-demo-dry
```

Exige `.env` com `MARIA_EXECUCAO_DEMO=1` (o script `demo-dry` força `DEMO` e `DRY` se não estiverem definidos — vê `scripts/maria_exchange.sh`). Se a conta não for demo, o programa pode recusar; isso é intencional.

---

## E) Atualizar só o código (sem correr agentes)

```bash
cd /CAMINHO/DO/CLONE/bot_maria_helana_Xau-usd
make maria-pull
```

Outra branch:

```bash
make maria-pull BRANCH=nome-da-branch
```

---

## F) Tabela rápida — o que usar

| Quero… | Comando |
|--------|---------|
| Ver se está tudo OK | `make maria-doctor` |
| Puxar código `main` | `make maria-pull` |
| Snapshot + regime + validação | `make maria-refresh-context` |
| Velas M5 + tudo acima | `make coletar-candles` depois `make maria-refresh-bars` |
| Demo sem ordem | `make maria-demo-dry` |
| Gravar uma chave no `.env` | `./scripts/maria_exchange.sh env-set NOME_DA_CHAVE 'valor'` |
| Ver chaves definidas (masc.) | `./scripts/maria_exchange.sh env-list` |

---

## G) Onde está o quê

| Ficheiro / pasta | Para quê |
|------------------|----------|
| `scripts/maria_exchange.sh` | Atalhos seguros no terminal |
| `Makefile` | `make maria-*` chama o mesmo script |
| `docs/deploy_maria_tubarao_vps.md` | Instalar clone na VPS ao lado do MonetaBot |
| `agents/README.md` | Detalhe dos agentes e *cron* |

Se algo falhar, copia a **mensagem de erro completa** e o output de `make maria-doctor` para a equipa.
