#!/usr/bin/env python3
"""
Configura .env na raiz do projeto sem abrir nano.
Uso:
  python3 set_env.py init
  python3 set_env.py set METAAPI_ACCOUNT_ID 5db1a8c3-c76b-457a-a967-2fd7b002e6b4
  python3 set_env.py set METAAPI_TOKEN 'eyJ...'   # aspas se o shell cortar caracteres
  python3 set_env.py get METAAPI_ACCOUNT_ID
  python3 set_env.py list

Para Trading Economics: o valor tem de ser copiado do site (painel API), não frases
de tutorial (README/chat).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from te_env_markers import te_value_looks_like_placeholder as _te_placeholder

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
EXAMPLE_PATH = ROOT / ".env.example"


def _format_value(value: str) -> str:
    if value == "":
        return ""
    if re.search(r'[\s#"\'\\]', value) or "=" in value:
        esc = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{esc}"'
    return value


def _parse_line(line: str) -> tuple[str | None, str | None]:
    s = line.strip()
    if not s or s.startswith("#"):
        return (None, None)
    if "=" not in s:
        return (None, None)
    key, _, val = s.partition("=")
    key = key.strip()
    val = val.strip()
    if len(val) >= 2 and val[0] == val[-1] == '"':
        val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return (key, val)


def _read_env() -> tuple[list[str], dict[str, str]]:
    """Preserva linhas não-chave; devolve (linhas_originais_para_reconstruir, dict)."""
    if not ENV_PATH.is_file():
        return ([], {})
    raw = ENV_PATH.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    data: dict[str, str] = {}
    for line in lines:
        k, v = _parse_line(line)
        if k is not None:
            data[k] = v or ""
    return (lines, data)


def _write_env(data: dict[str, str], preserve_comments: bool) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    out: list[str] = []

    if preserve_comments and ENV_PATH.is_file():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True):
            k, _ = _parse_line(line)
            if k is None:
                out.append(line if line.endswith("\n") else line + "\n")
                continue
            if k in data:
                v = _format_value(data[k])
                out.append(f"{k}={v}\n")
                seen.add(k)
            else:
                out.append(line if line.endswith("\n") else line + "\n")

    for k, v in data.items():
        if k not in seen:
            out.append(f"{k}={_format_value(v)}\n")

    ENV_PATH.write_text("".join(out), encoding="utf-8")
    try:
        ENV_PATH.chmod(0o600)
    except OSError:
        pass


def cmd_init(_: argparse.Namespace) -> int:
    if ENV_PATH.is_file():
        print(f"Já existe: {ENV_PATH}")
        return 0
    if EXAMPLE_PATH.is_file():
        shutil.copy(EXAMPLE_PATH, ENV_PATH)
        ENV_PATH.chmod(0o600)
        print(f"Criado a partir de .env.example → {ENV_PATH}")
        return 0
    ENV_PATH.write_text(
        "METAAPI_TOKEN=\nMETAAPI_ACCOUNT_ID=\nBENZINGA_API_KEY=\nBENZINGA_USERNAME=\n",
        encoding="utf-8",
    )
    ENV_PATH.chmod(0o600)
    print(f"Criado mínimo → {ENV_PATH}")
    return 0


def cmd_set(ns: argparse.Namespace) -> int:
    key = ns.key.strip()
    value = ns.value
    if not key:
        print("Chave vazia.", file=sys.stderr)
        return 1
    _, data = _read_env()
    if not data and not ENV_PATH.is_file():
        cmd_init(argparse.Namespace())
        _, data = _read_env()
    data[key] = value
    _write_env(data, preserve_comments=ENV_PATH.is_file())
    print(f"OK {key}=*** ({ENV_PATH})")
    if key.upper().startswith("TRADINGECONOMICS_") and _te_placeholder(value):
        print(
            "AVISO: Este valor parece texto de TUTORIAL (README/chat), não Client/Secret do site TE. "
            "A API responderá 401. Copie do browser (painel API) — sem PRIMEIRA_STRING, CLIENT_DO_SITE, etc.",
            file=sys.stderr,
        )
    return 0


def cmd_get(ns: argparse.Namespace) -> int:
    _, data = _read_env()
    v = data.get(ns.key.strip())
    if v is None:
        print("(não definido)")
        return 1
    show = v[:6] + "…" + v[-4:] if len(v) > 14 else "***"
    print(f"{ns.key.strip()}={show} (len={len(v)})")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    _, data = _read_env()
    if not data:
        print("(sem .env ou vazio)")
        return 1
    for k in sorted(data.keys()):
        v = data[k]
        masked = "(vazio)" if not v else (v[:4] + "…" if len(v) > 8 else "***")
        print(f"  {k}={masked}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Gerir .env sem nano")
    sub = p.add_subparsers(dest="cmd", required=True)

    ip = sub.add_parser("init", help="Cria .env a partir de .env.example")
    ip.set_defaults(func=cmd_init)

    sp = sub.add_parser("set", help="Define ou atualiza uma chave")
    sp.add_argument("key")
    sp.add_argument("value", nargs=argparse.REMAINDER, help="Valor (resto da linha)")
    sp.set_defaults(func=cmd_set)

    gp = sub.add_parser("get", help="Mostra se a chave existe (valor mascarado)")
    gp.add_argument("key")
    gp.set_defaults(func=cmd_get)

    lp = sub.add_parser("list", help="Lista chaves (valores mascarados)")
    lp.set_defaults(func=cmd_list)

    ns = p.parse_args()
    if ns.cmd == "set":
        if not ns.value:
            print("Falta valor. Ex.: python3 set_env.py set METAAPI_ACCOUNT_ID uuid-aqui", file=sys.stderr)
            return 1
        ns.value = " ".join(ns.value).strip()

    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
