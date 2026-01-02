#!/bin/bash
# Startup script for Telegram Download Bot

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Run the bot
python bot.py
