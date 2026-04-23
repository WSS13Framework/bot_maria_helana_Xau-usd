#!/usr/bin/env bash
# Na VPS, na pasta do repo:
#   chmod +x servidor_atualizar.sh
#   ./servidor_atualizar.sh              # usa main
#   ./servidor_atualizar.sh cursor/exogenous-shock-flags-a713
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
BRANCH="${1:-main}"
git fetch origin
if git rev-parse --verify "origin/$BRANCH" >/dev/null 2>&1; then
  :
else
  echo "Branch remota inexistente: origin/$BRANCH" >&2
  exit 1
fi
if git show-ref -q "refs/heads/$BRANCH"; then
  git checkout "$BRANCH"
else
  git checkout -b "$BRANCH" "origin/$BRANCH"
fi
git pull --ff-only "origin" "$BRANCH"
echo "OK — $BRANCH @ $(git rev-parse --short HEAD)"
