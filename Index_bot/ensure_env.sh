#!/bin/bash
# Shared env setup for Index_bot — same pattern as name-bot (repo root .venv + install_deps).
# Sourced by run_bot.sh / start_bot.sh; do not run directly unless debugging.

set -euo pipefail

_INDEX_BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_INDEX_ROOT_DIR="$(cd "${_INDEX_BOT_DIR}/.." && pwd)"

cd "${_INDEX_BOT_DIR}"

ensure_index_bot_dependencies() {
  if [[ -x "${_INDEX_ROOT_DIR}/scripts/setup_env.sh" ]]; then
    if [[ ! -d "${_INDEX_ROOT_DIR}/.venv" ]]; then
      echo "Creating shared virtualenv at ${_INDEX_ROOT_DIR}/.venv ..."
      "${_INDEX_ROOT_DIR}/scripts/setup_env.sh"
    fi
    # shellcheck source=/dev/null
    source "${_INDEX_ROOT_DIR}/.venv/bin/activate"

    if ! python -c "import telegram, sqlalchemy, telethon, dotenv" 2>/dev/null; then
      echo "Installing Index_bot dependencies (scripts/install_deps.sh index)..."
      "${_INDEX_ROOT_DIR}/scripts/install_deps.sh" index
    fi
    return 0
  fi

  # Fallback: Index_bot-only copy (e.g. zip on Termux without full monorepo)
  if [[ ! -d "${_INDEX_BOT_DIR}/venv" ]]; then
    echo "Creating local venv (standalone Index_bot folder)..."
    python -m venv "${_INDEX_BOT_DIR}/venv"
  fi
  # shellcheck source=/dev/null
  source "${_INDEX_BOT_DIR}/venv/bin/activate"

  if ! python -c "import telegram, sqlalchemy, telethon, dotenv" 2>/dev/null; then
    echo "Installing dependencies from requirements.txt..."
    pip install --upgrade pip wheel
    if [[ -f "${_INDEX_ROOT_DIR}/requirements/bot-index.txt" ]]; then
      pip install -r "${_INDEX_ROOT_DIR}/requirements/bot-index.txt"
    else
      pip install -r requirements.txt
    fi
  fi
}
