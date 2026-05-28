#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
source "${DIR}/ensure_env.sh"
ensure_index_bot_dependencies
cd "$DIR"
exec python run_portal.py
