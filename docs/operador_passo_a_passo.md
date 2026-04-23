# Operador — passo a passo (o que fazer e onde)

Tudo abaixo assume que estás **dentro da pasta do clone** do Maria Helena (ex.: `/opt/maria-helena-xau` na VPS ou a pasta do projecto no PC).

---

## A) Primeira vez nesta máquina (só uma vez)

```bash
cd /CAMINHO/DO/CLONE/bot_maria_helana_Xau-usd

git pull --ff-only origin main

make setup
make install
make env-init
chmod +x scripts/maria_exchange.sh
```

**Importante:** sempre que fizeres `git pull` e mudarem os requisitos (ou for a **primeira vez** depois de existir `requirements.txt`), corre **`make install`** antes de `make test-apis-*` ou `make maria-refresh-context`. Sem isto aparece `ModuleNotFoundError: dotenv` ou `requests`.

Definir chaves **sem abrir `nano`** — **não** uses o carácter `…` como valor; cola o token / ID **reais** (ex.: copiar do `.env` do Moneta só o valor, ou da consola MetaAPI):

```bash
./scripts/maria_exchange.sh env-set METAAPI_TOKEN 'eyJ...token_real...'
./scripts/maria_exchange.sh env-set METAAPI_ACCOUNT_ID 'id-guid-da-conta'
./scripts/maria_exchange.sh env-set TWELVEDATA_API_KEY 'chave_twelve'
./scripts/maria_exchange.sh env-set BENZINGA_API_KEY 'chave_benzinga'
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
make install
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

---

## H) Erros comuns

- **`fatal: invalid refspec '/opt/...'`** — Colaram-se dois comandos na mesma linha (ex.: `maincd` em vez de `main` Enter `cd`). Correr `git pull --ff-only origin main` **sozinho** numa linha.
- **`AVISO: sem requirements.txt`** no servidor — fazer `git pull` (o ficheiro tem de existir no Git) e `make install` ou `make setup` outra vez.
- **ML / Ray** (opcional): `.venv/bin/pip install -r requirements-ml.txt` na raiz do clone.
- **MetaAPI `401` / “no auth-token header provided”** — o `METAAPI_TOKEN` neste clone está **vazio**, é o placeholder `…`, ou foi cortado ao colar. Voltar a gravar: `./scripts/maria_exchange.sh env-set METAAPI_TOKEN 'cole_o_token_real'` (token da [consola MetaAPI](https://app.metaapi.cloud/)). O `.env` do **MonetaBot-Pro** é outro ficheiro: copiar o valor **manualmente**, não o path.
- **`make test-apis-sem-te-calendario` falha mas `make maria-refresh-context` corre** — snapshot/regime só precisam de Twelve/Benzinga/TE conforme o `.env`; o teste MetaAPI é separado. Corrigir o token para o *make* completo passar a verde.
