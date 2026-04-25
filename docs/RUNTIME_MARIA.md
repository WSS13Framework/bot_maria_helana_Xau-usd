# RUNTIME Maria (G-TRADE — passo 1)

## 1. Droplet (preenche)
- Nome DO: ubuntu-s--Maria-Helena-v2
- Regiao: SGP1
- IP: 143.198.95.64

## 2. Env canónico
- Ficheiro: /root/maria-helena/.env
- Antes de python: set -a && source /root/maria-helena/.env && set +a

## 3. Arranque executor (cola a linha real do python3 ...)
(vazio por agora)

## 4. Inventario (colar outputs)
(vazio por agora)

### systemd (output)
(nada encontrado)

### crontab
0 * * * * source /opt/maria-helena-dataset/.env && /opt/maria-helena-dataset/scripts/cron_collect.sh >> /opt/maria-helena-dataset/logs/cron.log 2>&1
(crontab root: 3 jobs — dataset horário, notifier crypto, daily report; **credenciais só em .env no servidor**, não documentar aqui)

0 * * * * /opt/crypto-trading-bot/scripts/schedule_trading.sh >> /opt/crypto-trading-bot/logs/schedule.log 2>&1

### ps
root         724  0.0  0.7  33212 15516 ?        Ss   Apr23   0:22 /usr/bin/python3 /usr/bin/networkd-dispatcher --run-startup-triggers
root         782  0.0  0.8 110156 16264 ?        Ssl  Apr23   0:00 /usr/bin/python3 /usr/share/unattended-upgrades/unattended-upgrade-shutdown -
root      478579  0.0  7.6 465608 154028 pts/0   Sl   16:58   0:02 python3 executor_onnx.py --iterations 0 --sleep 3600
root      478580  0.0  0.1   7896  3508 pts/0    S    16:58   0:00 bash -lc while true; do \   python3 scripts/summarize_executor_onnx_hourly.py
root      480916  0.0  7.6 465612 154832 pts/0   Sl   17:11   0:02 python3 executor_onnx.py --iterations 0 --sleep 3600
