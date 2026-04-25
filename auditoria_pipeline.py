import pandas as pd, numpy as np, json, sys, glob
from pathlib import Path
import sqlite3

print('=== AUDITORIA DO PIPELINE ===\n')

# 1. Estrutura dos dados
feat = pd.read_csv('data/xauusd_feature_table.csv')
lab = pd.read_csv('data/xauusd_labeled_dataset.csv')
print(f'Features: {feat.shape[0]} linhas, {feat.shape[1]} colunas')
print(f'Labels: {lab.shape[0]} linhas')
print(f'Período features: {feat["time"].min()} até {feat["time"].max()}')
print(f'Período labels: {lab["time"].min()} até {lab["time"].max()}')
print()

# 2. Features mais importantes (se modelo existir)
model_files = glob.glob('models/*.cbm')
if model_files:
    from catboost import CatBoostClassifier
    model = CatBoostClassifier()
    model.load_model(model_files[0])
    importance = model.get_feature_importance()
    feature_names = model.feature_names_
    top = sorted(zip(feature_names, importance), key=lambda x: x[1], reverse=True)[:15]
    print('Top 15 features:')
    for name, imp in top:
        print(f'  {name}: {imp:.2f}')
else:
    print('Nenhum modelo .cbm encontrado em models/')
print()

# 3. Análise de regime (ATR mensal)
feat['time'] = pd.to_datetime(feat['time'])
feat['year_month'] = feat['time'].dt.to_period('M')
monthly = feat.groupby('year_month').agg(
    atr_mean=('atr','mean'),
    atr_std=('atr','std'),
    rows=('atr','count')
)
print('ATR mensal (últimos 6 meses):')
print(monthly.tail(6).to_string())
print()

# 4. Verificar RAG
rag_db = Path('data/local_rag/metadata.sqlite3')
if rag_db.exists():
    conn = sqlite3.connect(rag_db)
    cursor = conn.execute("SELECT COUNT(*), MIN(pub_date), MAX(pub_date) FROM documents")
    count, min_date, max_date = cursor.fetchone()
    print(f'RAG: {count} docs, {min_date} até {max_date}')
    conn.close()
else:
    print('RAG: metadata.sqlite3 não encontrado')
