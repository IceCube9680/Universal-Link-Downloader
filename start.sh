#!/usr/bin/env bash
set -e

# ==============================================================================
# Universal Link Downloader Bot - Foreground / Daemon Runner
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 [Universal Bot] Starting Universal Link Downloader..."

# 1. Activate Virtual Environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ Error: Virtual environment (.venv) not found!"
    echo "💡 Create it with: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# 2. Cleanup stale journal/lock files
mkdir -p data logs downloads temp
rm -f data/*.session-journal data/*.session-wal data/*.session-shm

# 3. Terminate any previous orphaned instance
if [ -f "data/bot.pid" ]; then
    OLD_PID=$(cat data/bot.pid 2>/dev/null || true)
    if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️ Found running bot instance (PID $OLD_PID). Stopping it..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
        kill -9 "$OLD_PID" 2>/dev/null || true
    fi
    rm -f data/bot.pid
fi

# 4. Run the Bot
echo "⚡ Executing main.py..."
exec python3 main.py "$@"
