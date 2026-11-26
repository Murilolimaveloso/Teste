#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Edite o arquivo .env e coloque sua ANTHROPIC_API_KEY, depois rode ./iniciar.sh de novo."
  exit 0
fi
python server.py
