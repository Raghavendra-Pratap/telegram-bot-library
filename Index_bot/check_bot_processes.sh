#!/bin/bash
# Script to check for running bot instances

echo "Checking for running bot processes..."
echo "======================================"
echo ""

# Check for python processes running bot.py
PROCESSES=$(ps aux | grep -i "python.*bot.py" | grep -v grep)

if [ -z "$PROCESSES" ]; then
    echo "✅ No bot processes found running"
else
    echo "⚠️  Found running bot processes:"
    echo "$PROCESSES"
    echo ""
    echo "To stop all bot processes, run:"
    echo "  pkill -f 'python.*bot.py'"
fi

echo ""
echo "Checking for Python processes in general..."
PYTHON_PROCS=$(ps aux | grep python | grep -v grep | wc -l | tr -d ' ')
echo "Total Python processes: $PYTHON_PROCS"
