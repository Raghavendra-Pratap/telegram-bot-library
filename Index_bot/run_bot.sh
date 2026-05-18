#!/bin/bash
# Simple script to run the Index Bot

cd "$(dirname "$0")"

echo "=========================================="
echo "Index Bot - Starting..."
echo "=========================================="
echo ""

# Activate virtual environment
source venv/bin/activate

# Run the bot (foreground so you can see output)
python bot.py
