import pandas as pd, numpy as np, json, sys, glob, os
from pathlib import Path
import sqlite3

print('=== AUDITORIA V2 ===\n')

# 1. Listar colunas
feat = pd.read_csv('data/xauusd_feature_table.csv')
print('Colunas das features:')
for i, col in enumerate(feat.columns):
    print(f'  {i}: {col}')
print()

# 2. Verificar dados
print(f'Shape: {feat.shape}')
print(f'Período: {feat["time"].min()} a {feat["time"].max()}')
print(f'Duração: {pd.to_datetime(feat["time"]).max() - pd.to_datetime(feat["time"]).min()}')
print()

# 3. Checar se há coluna de volatilidade/ATR
vol_cols = [c for c in feat.columns if 'atr' in c.lower() or 'vol' in c.lower() or 'range' in c.lower()]
if vol_cols:
    print(f'Possíveis colunas de volatilidade: {vol_cols}')
    vol_col = vol_cols[0]
    feat['time_dt'] = pd.to_datetime(feat['time'])
    feat['day'] = feat['time_dt'].dt.date
    daily_vol = feat.groupby('day')[vol_col].mean()
    print(f'\nMédia diária de {vol_col} (últimos 5 dias):')
    print(daily_vol.tail(5))
else:
    print('Nenhuma coluna de volatilidade óbvia encontrada.')
print()

# 4. Verificar RAG
rag_dir = Path('data/local_rag')
if rag_dir.exists():
    print(f'RAG: diretório {rag_dir} existe')
    db_path = rag_dir / 'metadata.sqlite3'
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            print(f'Tabelas no RAG: {tables}')
            for table in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
                print(f'  {table[0]}: {count} registros')
        except Exception as e:
            print(f'Erro ao ler RAG: {e}')
        conn.close()
    else:
        print('RAG: metadata.sqlite3 não encontrado')
        # listar arquivos
        for f in rag_dir.glob('*'):
            print(f'  {f.name}')
else:
    print('RAG: diretório não encontrado')

# 5. Verificar labels
lab = pd.read_csv('data/xauusd_labeled_dataset.csv')
print(f'\nLabels: {lab.shape}')
print(f'Colunas labels: {list(lab.columns)}')
if 'tb_label' in lab.columns:
    print(f'tb_label distribuição:')
    print(lab['tb_label'].value_counts())
if 'rr_viable' in lab.columns:
    print(f'rr_viable distribuição:')
    print(lab['rr_viable'].value_counts())
