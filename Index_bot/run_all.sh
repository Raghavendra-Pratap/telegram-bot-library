#!/bin/bash
# One-command launcher: installs deps if missing, then starts bot + portal.

set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_PIDFILE="${DIR}/.bot.pid"
PORTAL_PIDFILE="${DIR}/.portal.pid"

# shellcheck source=ensure_env.sh
source "${DIR}/ensure_env.sh"
ensure_index_bot_dependencies

cd "${DIR}"
python check_readiness.py

echo "Checking existing Index_bot processes..."
if [[ -f "${BOT_PIDFILE}" ]]; then
  BOT_PID="$(tr -d '[:space:]' < "${BOT_PIDFILE}" || true)"
  if [[ -n "${BOT_PID}" ]] && kill -0 "${BOT_PID}" 2>/dev/null; then
    echo "Bot already running (PID ${BOT_PID})"
  else
    rm -f "${BOT_PIDFILE}"
  fi
fi
if [[ -f "${PORTAL_PIDFILE}" ]]; then
  PORTAL_PID="$(tr -d '[:space:]' < "${PORTAL_PIDFILE}" || true)"
  if [[ -n "${PORTAL_PID}" ]] && kill -0 "${PORTAL_PID}" 2>/dev/null; then
    echo "Portal already running (PID ${PORTAL_PID})"
  else
    rm -f "${PORTAL_PIDFILE}"
  fi
fi

if [[ ! -f "${BOT_PIDFILE}" ]]; then
  echo "Starting bot..."
  nohup python bot.py >> "${DIR}/bot.log" 2>&1 &
  # bot.py writes .bot.pid after it acquires the single-instance lock (do not echo $! here)
fi

if [[ ! -f "${PORTAL_PIDFILE}" ]]; then
  echo "Starting portal..."
  nohup python run_portal.py >> "${DIR}/portal.log" 2>&1 &
  echo $! > "${PORTAL_PIDFILE}"
fi

echo ""
echo "Index_bot stack is up."
echo "Bot log:    ${DIR}/bot.log"
echo "Portal log: ${DIR}/portal.log"
echo "Stop all:   ${DIR}/stop_all.sh"
