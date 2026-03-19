#!/bin/bash
# Script to authenticate MTProto client interactively

cd "$(dirname "$0")"

echo "🔐 MTProto Authentication Script"
echo "================================"
echo ""
echo "This will stop any running bot instances and start it interactively"
echo "for MTProto authentication."
echo ""
read -p "Press Enter to continue..."

# Stop any running bot processes
echo "🛑 Stopping any running bot processes..."
pkill -f "TG_download_bot.*bot.py" 2>/dev/null
pkill -f "python.*TG_download_bot/bot.py" 2>/dev/null
sleep 2

# Activate virtual environment
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  Virtual environment not found. Make sure you've set it up."
    exit 1
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo "Please create .env file from env_template.txt"
    exit 1
fi

echo ""
echo "🚀 Starting bot interactively for authentication..."
echo "=================================================="
echo ""
echo "You will be prompted to:"
echo "1. Enter your phone number (with country code, e.g., +1234567890)"
echo "2. Enter the verification code sent to your Telegram app"
echo "3. Enter 2FA password (if you have 2FA enabled)"
echo ""
echo "After authentication, a session file will be created and you can"
echo "run the bot in the background."
echo ""
read -p "Press Enter to start authentication..."

# Run bot interactively
python bot.py
