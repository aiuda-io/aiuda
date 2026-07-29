#!/usr/bin/env bash
# Desarrollo local con recarga en vivo (dos procesos, mismo origen vía rewrite).
# La instalación normal NO usa esto: es `uvx aiuda` (o `uv run aiuda start`).
#
#   scripts/dev.sh          # API :8000 (reload) + consola Next :3000
#   scripts/dev.sh down     # detener ambos
set -euo pipefail
cd "$(dirname "$0")/.."

RUN_DIR="$HOME/.aiuda/dev"
mkdir -p "$RUN_DIR"

down() {
  for f in api web; do
    if [ -f "$RUN_DIR/$f.pid" ]; then
      kill "$(cat "$RUN_DIR/$f.pid")" 2>/dev/null || true
      rm -f "$RUN_DIR/$f.pid"
    fi
  done
  echo "dev abajo"
}

if [ "${1:-}" = "down" ]; then down; exit 0; fi

down >/dev/null 2>&1 || true
uv run uvicorn aiuda_server.api.main:app --reload --port 8000 \
  > "$RUN_DIR/api.log" 2>&1 & echo $! > "$RUN_DIR/api.pid"
( cd web && npm run dev > "$RUN_DIR/web.log" 2>&1 & echo $! > "$RUN_DIR/web.pid" )

echo "API   http://127.0.0.1:8000  (log: $RUN_DIR/api.log)"
echo "Web   http://localhost:3000  (log: $RUN_DIR/web.log)"
echo "Alto  scripts/dev.sh down"
