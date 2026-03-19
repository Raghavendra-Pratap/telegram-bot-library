#!/bin/bash

# Quick start script for the Telegram Bot
# This script should be run from the down_oad_bot directory

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🎬 Starting Telegram Video Downloader Bot..."
echo ""

# Use shared virtual environment at repo root
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"

# Check if virtual environment exists
if [ ! -d "${VENV_DIR}" ]; then
    echo "❌ Shared virtual environment not found!"
    echo "Run: ${ROOT_DIR}/scripts/setup_env.sh"
    echo "Then: ${ROOT_DIR}/scripts/install_deps.sh down_oad"
    exit 1
fi

# Determine Python executable in venv
if [ -f "${VENV_DIR}/bin/python" ]; then
    PYTHON_CMD="${VENV_DIR}/bin/python"
elif [ -f "${VENV_DIR}/bin/python3" ]; then
    PYTHON_CMD="${VENV_DIR}/bin/python3"
else
    echo "❌ Python not found in venv!"
    echo "Run: ${ROOT_DIR}/scripts/setup_env.sh"
    echo "Then: ${ROOT_DIR}/scripts/install_deps.sh down_oad"
    exit 1
fi

# Activate virtual environment (for PATH and other env vars)
# shellcheck source=/dev/null
source "${VENV_DIR}/bin/activate"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo "Run: cp env_template.txt .env"
    echo "Then edit .env and add your TELEGRAM_BOT_TOKEN"
    exit 1
fi

# Check if token is configured
if grep -q "your_bot_token_here" .env; then
    echo "⚠️  Warning: Bot token not configured in .env"
    echo "Please edit .env and add your TELEGRAM_BOT_TOKEN"
    echo "See GET_BOT_TOKEN.md for instructions"
    exit 1
fi

# Check for other bot instances
BOT_PIDS=$(ps aux | grep -i "python.*bot.py" | grep -v grep | awk '{print $2}')
if [ ! -z "$BOT_PIDS" ]; then
    echo "⚠️  Warning: Found other bot instances running:"
    ps aux | grep -i "python.*bot.py" | grep -v grep
    echo ""
    echo "These may cause conflicts. To stop them, run:"
    echo "  ./stop_other_instances.sh"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. Please stop other instances first."
        exit 1
    fi
fi

# Run test setup
echo "Running setup test..."
$PYTHON_CMD test_setup.py
echo ""

# Start the bot
echo "Starting bot..."
echo "Press Ctrl+C to stop"
echo ""
$PYTHON_CMD bot.py

