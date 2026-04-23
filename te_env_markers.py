"""
Fragmentos que aparecem em tutoriais — não são credenciais do painel Trading Economics.
Usado por set_env.py e test_tradingeconomics_calendar.py.
"""
from __future__ import annotations

# Comparar sempre em UPPER no valor.
TE_PLACEHOLDER_FRAGMENTS: tuple[str, ...] = (
    "COLA_AQUI",
    "PARTE_ANTES",
    "PARTE_DEPOIS",
    "DOIS_PONTOS",
    "CLIENT_REAL",
    "SECRET_REAL",
    "CLIENT_DO_SITE",
    "SECRET_DO_SITE",
    "PRIMEIRA_STRING",
    "SEGUNDA_STRING",
    "STRING_DO_PAINEL",
    "DO_PAINEL",
    "SEU_CLIENT",
    "SEU_SECRET",
    "YOUR_CLIENT",
    "YOUR_SECRET",
    "REPLACE_ME",
    "CHANGEME",
    "EXAMPLE_KEY",
    "VALOR_EXACTO",
    "NOME_EXACTO",
    "INSERT_HERE",
    "TUTORIAL",
)


def te_value_looks_like_placeholder(value: str) -> bool:
    if not value:
        return False
    u = value.upper()
    return any(m in u for m in TE_PLACEHOLDER_FRAGMENTS)
