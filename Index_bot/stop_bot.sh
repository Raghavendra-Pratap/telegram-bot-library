#!/bin/bash
# Stop only the Index_bot instance (does not touch other bots in the repo).

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/.bot.pid"

echo "Stopping Index_bot..."
echo "=============================="

if [[ -f "$PIDFILE" ]]; then
  PID="$(tr -d '[:space:]' < "$PIDFILE")"
  if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null || true
    sleep 2
    if kill -0 "$PID" 2>/dev/null; then
      kill -9 "$PID" 2>/dev/null || true
    fi
    echo "✅ Stopped PID $PID (from .bot.pid)"
  else
    echo "⚠️  Stale .bot.pid (process not running)"
  fi
  rm -f "$PIDFILE"
fi

# Fallback: any bot.py whose cwd is this directory
while read -r pid; do
  [[ -z "$pid" ]] && continue
  kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  echo "✅ Stopped PID $pid"
done < <(lsof -t +D "$DIR" 2>/dev/null | while read -r pid; do
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  [[ "$cmd" == *"bot.py"* ]] && echo "$pid"
done)

sleep 1
REMAINING=$(ps aux | grep "$DIR" | grep 'bot.py' | grep -v grep || true)
if [[ -z "$REMAINING" ]]; then
  echo "✅ Index_bot is not running"
else
  echo "⚠️  Still running:"
  echo "$REMAINING"
fi

echo ""
echo "Start again: cd \"$DIR\" && source venv/bin/activate && python bot.py"
