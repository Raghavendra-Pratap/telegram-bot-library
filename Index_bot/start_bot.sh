#!/bin/bash
# Startup script for Index Bot (shared .venv + auto-install, like name-bot via launcher).

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=ensure_env.sh
source "${DIR}/ensure_env.sh"

echo "Checking for running bot instances..."
RUNNING=$(ps aux | grep -i "Index_bot.*bot.py" | grep -v grep || true)
if [[ -n "$RUNNING" ]]; then
    echo "⚠️  Bot is already running!"
    echo "$RUNNING"
    echo ""
    read -p "Stop existing instance and start new one? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopping existing instances..."
        "${DIR}/stop_bot.sh" 2>/dev/null || pkill -f "Index_bot.*bot.py" || true
        sleep 2
    else
        echo "Exiting. Bot is already running."
        exit 0
    fi
fi

ensure_index_bot_dependencies

echo "Running readiness check..."
python check_readiness.py || exit 1

echo ""
echo "Starting bot..."
echo "Press Ctrl+C to stop"
echo ""

exec python bot.py
