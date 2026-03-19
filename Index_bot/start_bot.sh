#!/bin/bash
# Startup script for Index Bot

cd "$(dirname "$0")"

# Check for running instances
echo "Checking for running bot instances..."
RUNNING=$(ps aux | grep -i "Index_bot.*bot.py" | grep -v grep)
if [ ! -z "$RUNNING" ]; then
    echo "⚠️  Bot is already running!"
    echo "$RUNNING"
    echo ""
    read -p "Stop existing instance and start new one? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Stopping existing instances..."
        pkill -f "Index_bot.*bot.py"
        sleep 2
    else
        echo "Exiting. Bot is already running."
        exit 0
    fi
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Check readiness
echo "Running readiness check..."
python check_readiness.py
if [ $? -ne 0 ]; then
    echo "❌ Readiness check failed. Please fix issues before starting."
    exit 1
fi

echo ""
echo "Starting bot..."
echo "Press Ctrl+C to stop"
echo ""

# Run the bot
python bot.py
