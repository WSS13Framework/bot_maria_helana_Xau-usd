# Deploy Maria Helena no Tubarão (*side-by-side* com MonetaBot-Pro)

Objectivo: ter o clone **Maria Helena** no mesmo servidor que `/root/MonetaBot-Pro`, **sem** misturar `venv` nem `.env`, e gerar `data/*.json` para [contrato de handoff](contrato_handoff_regime.md).

**Path sugerido** (evitar confusão com outro clone): `/root/maria-helena-xau` ou `/opt/maria-helena-xau`.

---

## 1. Pré-requisitos no Ubuntu

- `git`, `python3`, `make`
- Utilizador com permissão de escrita na pasta escolhida (ex. `root` na VPS actual)

---

## 2. Clonar e instalar

```bash
sudo mkdir -p /opt/maria-helena-xau
sudo chown "$USER:$USER" /opt/maria-helena-xau
cd /opt/maria-helena-xau

git clone https://github.com/WSS13Framework/bot_maria_helana_Xau-usd.git .
# ou SSH: git clone git@github.com:WSS13Framework/bot_maria_helana_Xau-usd.git .

make setup
make env-init
```

Editar credenciais **só neste clone**:

```bash
./.venv/bin/python3 set_env.py set TWELVEDATA_API_KEY "…"
./.venv/bin/python3 set_env.py set BENZINGA_API_KEY "…"
# Trading Economics — conforme .env.example (client:secret ou CLIENT+SECRET)
./.venv/bin/python3 set_env.py set METAAPI_TOKEN "…"
./.venv/bin/python3 set_env.py set METAAPI_ACCOUNT_ID "…"
```

---

## 3. Verificação (sem ordens)

```bash
cd /opt/maria-helena-xau
make test-apis-sem-te-calendario
make snapshot-mercado
```

Para `features-gaps` + `regime-sugerido`, é preciso `data/xauusd_m5.json` (MetaAPI):

```bash
./.venv/bin/python3 coletar_candles.py
make features-gaps
make regime-sugerido
```

Execução demo **sempre** começar com DRY (ver `.env.example`):

```bash
export MARIA_EXECUCAO_DEMO=1
export MARIA_EXECUCAO_DRY=1
make execucao-demo
```

---

## 4. Não colidir com MonetaBot-Pro

- **Não** apagar nem alterar `/root/MonetaBot-Pro/.env` a partir do Maria.
- Agendar `cron` Maria em **minutos/horas diferentes** dos scripts `coletar_*` / `treinar_*` do Moneta (ver [agents/README.md](../agents/README.md)).
- Se ambos usarem MetaAPI, respeitar limites da conta e evitar dois *heavy poll* no mesmo minuto.

---

## 5. Actualizações

```bash
cd /opt/maria-helena-xau
git pull --ff-only origin main
make install
```

Alinhado à regra **ambiente → VPS** do [README.md](../README.md).
