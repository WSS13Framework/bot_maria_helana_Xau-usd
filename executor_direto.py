import os, time, hmac, hashlib, requests
from urllib.parse import urlencode

def main():
    print("🤖 TESTE DE CONEXÃO DIRETA COM FUTUROS DA BINANCE 🤖")
    print("="*55)
    with open('.env') as f:
        for line in f:
            k, _, v = line.strip().partition('=')
            os.environ[k] = v
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_SECRET_KEY")
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
