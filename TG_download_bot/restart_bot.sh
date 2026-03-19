#!/bin/bash
# Script to restart the bot with updated configuration

cd "$(dirname "$0")"

echo "🔄 Restarting Telegram Download Bot"
echo "===================================="
echo ""

# Stop any running bot processes
echo "🛑 Stopping existing bot processes..."
pkill -f "TG_download_bot.*bot.py" 2>/dev/null
pkill -f "python.*TG_download_bot/bot.py" 2>/dev/null
sleep 2

# Check if any processes are still running
REMAINING=$(ps aux | grep -E "python.*bot.py" | grep TG_download_bot | grep -v grep | wc -l | tr -d ' ')
if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  Some processes still running, force killing..."
    pkill -9 -f "TG_download_bot.*bot.py" 2>/dev/null
    sleep 1
fi

# Verify .env configuration
echo ""
echo "📋 Checking configuration..."
if [ -f ".env" ]; then
    BASE_URL=$(grep "FILE_SERVER_BASE_URL" .env | cut -d'=' -f2 | tr -d ' ')
    if [[ "$BASE_URL" == *"localhost"* ]]; then
        echo "⚠️  WARNING: FILE_SERVER_BASE_URL still uses localhost!"
        echo "   Current: $BASE_URL"
        echo "   Run: ./setup_local_server.sh to fix"
        echo ""
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo "✅ FILE_SERVER_BASE_URL: $BASE_URL"
    fi
else
    echo "❌ .env file not found!"
    exit 1
fi

# Activate virtual environment
if [ -d "venv" ]; then
    echo ""
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  Virtual environment not found"
fi

# Start bot
echo ""
echo "🚀 Starting bot..."
echo ""
python bot.py
