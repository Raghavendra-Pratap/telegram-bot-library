#!/bin/bash
# Quick start script for Bot Launcher

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${ROOT_DIR}"

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed or not in PATH"
    exit 1
fi

# Prepare shared virtual environment
./scripts/setup_env.sh

# Activate shared virtual environment
# shellcheck source=/dev/null
source "${ROOT_DIR}/.venv/bin/activate"

# Check if Flask is installed (for dashboard)
if ! python -c "import flask" 2>/dev/null; then
    echo "⚠️  Flask not found. Installing launcher dependencies..."
    ./scripts/install_deps.sh launcher
fi

# Run the launcher
python bot_launcher.py
