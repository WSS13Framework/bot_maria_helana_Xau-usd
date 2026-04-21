import os, time, hmac, hashlib, requests
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"

def main():
    print("🤖 TESTE DE CONEXÃO DIRETA COM FUTUROS DA BINANCE 🤖")
    print("="*55)
    if not ENV_PATH.exists():
        raise RuntimeError(f"Arquivo .env não encontrado em {ENV_PATH}")

    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            k, _, v = line.strip().partition('=')
            os.environ[k] = v
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_SECRET_KEY")
    if not api_key or api_key == "sua_api_key_aqui":
        raise RuntimeError(f"BINANCE_API_KEY ausente/invalida em {ENV_PATH}")
    if not api_secret or api_secret == "sua_secret_key_aqui":
        raise RuntimeError(f"BINANCE_SECRET_KEY ausente/invalida em {ENV_PATH}")
    print(f"✅ API Key: {api_key[:8]}...")
    timestamp = int(time.time() * 1000)
    params = {'timestamp': timestamp}
    qs = urlencode(params)
    sig = hmac.new(api_secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    params['signature'] = sig
    headers = {'X-MBX-APIKEY': api_key}
    r = requests.get('https://fapi.binance.com/fapi/v2/account', headers=headers, params=params, timeout=10 )
    print(f"📡 Status HTTP: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        usdt = next((a for a in data.get('assets', []) if a['asset'] == 'USDT'), None)
        print("\n🎉🎉🎉 SUCESSO! CONEXÃO COM FUTUROS ESTABELECIDA! 🎉🎉🎉")
        if usdt:
            print(f"   Saldo USDT: {usdt['walletBalance']}")
    else:
        print(f"\n❌ FALHA: {r.text}")

main()
