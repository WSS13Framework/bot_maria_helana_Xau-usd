#!/usr/bin/env python3
"""Executor enxuto para GC_F (ouro). Yahoo Finance + MetaApi."""
import argparse, asyncio, json, os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import joblib
import yfinance as yf
from dotenv import dotenv_values
from metaapi_cloud_sdk import MetaApi

MODEL_PATH = Path(__file__).parent / "GC_F_xgb_unified.pkl"
ENV_PATH = Path("/root/maria-helena/.env")
LOG_PATH = Path("/root/maria-helena/logs/executor_clean.jsonl")

def append_log(payload):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(payload, default=str) + "\n")

def compute_features(df):
    df = df.copy()
    # Garantir que 'volume' existe (Yahoo Finance já fornece 'volume')
    if "volume" not in df.columns:
        df["volume"] = 0
    df["returns"] = df["close"].pct_change()
    df["volatility"] = df["returns"].rolling(20).std()
    df["ma_ratio"] = df["close"] / df["close"].rolling(20).mean()
    return df.dropna().reset_index(drop=True)

async def main(args):
    model = joblib.load(MODEL_PATH)
    threshold = args.threshold
    symbol = args.symbol

    env = dotenv_values(ENV_PATH)
    api = MetaApi(env.get("METAAPI_TOKEN"))
    if env.get("METAAPI_TOKEN") and env.get("METAAPI_ACCOUNT_ID"):
        try:
            account = await api.metatrader_account_api.get_account(env["METAAPI_ACCOUNT_ID"])
            if account.state != "DEPLOYED":
                await account.deploy()
            print("MetaApi conectado.")
        except Exception as e:
            print(f"Aviso: MetaApi não conectado ({e}). Prosseguindo apenas com sinais.")

    print(f"Executor iniciado para {symbol}, threshold={threshold}")

    while True:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period="2mo")
            if df.empty or len(df) < 25:
                await asyncio.sleep(60)
                continue

            df.columns = [c.lower() for c in df.columns]
            df = df.rename_axis("time").reset_index()
            df = compute_features(df)
            if df.empty:
                await asyncio.sleep(60)
                continue

            latest = df.iloc[-1:][["volume", "returns", "volatility", "ma_ratio"]]
            prob = model.predict_proba(latest)[0, 1]
            print(f"{datetime.now()} Prob: {prob:.4f}")

            if prob >= threshold:
                print("Sinal de compra - implementar ordem.")
                append_log({
                    "time": datetime.now(timezone.utc).isoformat(),
                    "prob": prob,
                    "symbol": symbol,
                    "signal": "buy"
                })
            await asyncio.sleep(args.interval)

        except Exception as e:
            print(f"Erro: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="GC=F")
    parser.add_argument("--threshold", type=float, default=0.6)
    parser.add_argument("--interval", type=int, default=3600)
    asyncio.run(main(parser.parse_args()))
