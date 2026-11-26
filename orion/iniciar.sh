#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Preencha o arquivo .env (ANTHROPIC_API_KEY e DATABASE_URL), salve e rode de novo: bash iniciar.sh"
  if command -v open >/dev/null; then open -e .env; fi
  exit 0
fi
python server.py
