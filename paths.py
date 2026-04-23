"""Caminhos do projeto — evita depender de /root/maria-helena em servidores diferentes."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
