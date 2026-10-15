#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Automatic pre-flight cleanup: clear any dead/orphaned processes on port 8770
PORT=${PORT:-8770}
if command -v fuser >/dev/null 2>&1; then
    fuser -k -9 "${PORT}/tcp" 2>/dev/null || true
fi
pkill -9 -f "launch.py" 2>/dev/null || true

echo "Starting OpenField on http://127.0.0.1:${PORT} ..."
exec .venv/bin/python launch.py
