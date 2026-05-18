#!/bin/bash
# Run Index_bot in the foreground (same dependency flow as name-bot + launcher auto-install).

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=ensure_env.sh
source "${DIR}/ensure_env.sh"
ensure_index_bot_dependencies

echo "=========================================="
echo "Index Bot - Starting..."
echo "=========================================="
echo ""

python check_readiness.py || exit 1
exec python bot.py
