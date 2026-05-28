#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PORTAL_PIDFILE="${DIR}/.portal.pid"

"${DIR}/stop_bot.sh" || true

echo "Stopping portal..."
if [[ -f "${PORTAL_PIDFILE}" ]]; then
  PID="$(tr -d '[:space:]' < "${PORTAL_PIDFILE}" || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}" 2>/dev/null || true
    sleep 1
    kill -9 "${PID}" 2>/dev/null || true
    echo "✅ Stopped portal PID ${PID}"
  else
    echo "⚠️  Stale .portal.pid"
  fi
  rm -f "${PORTAL_PIDFILE}"
else
  echo "⚠️  No .portal.pid file found"
fi

# Fallback: portal started without pidfile (or stale pidfile)
while read -r pid; do
  [[ -z "$pid" ]] && continue
  kill "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
  echo "✅ Stopped portal PID $pid (run_portal.py)"
done < <(pgrep -f "${DIR}/run_portal.py" 2>/dev/null || true)
