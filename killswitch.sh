#!/usr/bin/env bash
echo "=== [OPENFIELD KILLSWITCH ACTIVATED] ==="

# 1. Kill any process listening on port 8770
PORT=${PORT:-8770}
echo "[-] Checking port $PORT..."
if command -v fuser >/dev/null 2>&1; then
    fuser -k -9 "${PORT}/tcp" 2>/dev/null || true
fi

# 2. Kill by lsof if present
if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti :${PORT} 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        echo "[-] Killing port $PORT PIDs: $PIDS"
        kill -9 $PIDS 2>/dev/null || true
    fi
fi

# 3. Kill lingering python worker and launch scripts
echo "[-] Terminating lingering OpenField processes..."
pkill -9 -f "launch.py" 2>/dev/null || true
pkill -9 -f "uvicorn.*app:app" 2>/dev/null || true
pkill -9 -f "segment_sam3" 2>/dev/null || true
pkill -9 -f "segment_worker" 2>/dev/null || true
pkill -9 -f "pipeline.py" 2>/dev/null || true

sleep 0.5
echo "[✓] Port $PORT is now FREE."
echo "[✓] All OpenField workers terminated successfully."
echo "=== You can now run ./start.sh cleanly! ==="
