#!/bin/bash
# Script to stop all running bot instances

echo "Stopping all bot processes..."
echo "=============================="
echo ""

# Find and kill all bot.py processes
pkill -f "python.*bot.py"

if [ $? -eq 0 ]; then
    echo "✅ All bot processes stopped"
    sleep 2
    echo ""
    echo "Checking for remaining processes..."
    REMAINING=$(ps aux | grep -i "python.*bot.py" | grep -v grep)
    if [ -z "$REMAINING" ]; then
        echo "✅ Confirmed: No bot processes running"
    else
        echo "⚠️  Some processes may still be running:"
        echo "$REMAINING"
        echo ""
        echo "You may need to kill them manually:"
        echo "  kill -9 <PID>"
    fi
else
    echo "⚠️  No bot processes found to stop"
fi

echo ""
echo "You can now start the bot with:"
echo "  source venv/bin/activate && python bot.py"
