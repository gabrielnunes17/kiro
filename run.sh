#!/usr/bin/env bash
# Atalho para a API e os testes. Uso:
#   ./run.sh            sobe a API (Swagger em /docs)
#   ./run.sh dev        sobe com recarga automatica ao editar o codigo
#   ./run.sh test       roda os testes
# Variaveis opcionais: HOST (127.0.0.1), PORT (8000), KODIAK_DB (data/app.db)
set -euo pipefail
cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PY=".venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Ambiente virtual nao encontrado em .venv. Crie com:" >&2
  echo "  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

case "${1:-start}" in
  start)
    echo "Swagger: http://${HOST}:${PORT}/docs"
    exec "$PY" -m uvicorn backend.api:app --host "$HOST" --port "$PORT"
    ;;
  dev)
    echo "Swagger: http://${HOST}:${PORT}/docs (recarga automatica)"
    exec "$PY" -m uvicorn backend.api:app --host "$HOST" --port "$PORT" --reload
    ;;
  test)
    exec "$PY" -m pytest -q
    ;;
  *)
    echo "Uso: ./run.sh [start|dev|test]" >&2
    exit 1
    ;;
esac
