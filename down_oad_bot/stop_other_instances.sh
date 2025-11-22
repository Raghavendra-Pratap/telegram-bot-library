#!/bin/bash

# Script to stop other bot instances that might be causing conflicts

echo "🔍 Checking for other bot instances..."

# Find all Python processes running bot.py
BOT_PIDS=$(ps aux | grep -i "python.*bot.py" | grep -v grep | awk '{print $2}')

if [ -z "$BOT_PIDS" ]; then
    echo "✅ No other bot instances found"
    exit 0
fi

echo "⚠️  Found bot processes:"
ps aux | grep -i "python.*bot.py" | grep -v grep

echo ""
read -p "Do you want to stop these processes? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    for PID in $BOT_PIDS; do
        echo "Stopping process $PID..."
        kill $PID 2>/dev/null
        sleep 1
        # Force kill if still running
        if kill -0 $PID 2>/dev/null; then
            echo "Force killing process $PID..."
            kill -9 $PID 2>/dev/null
        fi
    done
    echo "✅ Stopped all bot instances"
    echo "Wait 2-3 seconds before starting the bot again"
else
    echo "❌ Cancelled"
    exit 1
fi

