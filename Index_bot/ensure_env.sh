#!/bin/bash
# Shared env setup for Index_bot — same pattern as name-bot (repo root .venv + install_deps).
# Sourced by run_bot.sh / start_bot.sh; do not run directly unless debugging.

set -euo pipefail

_INDEX_BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_INDEX_ROOT_DIR="$(cd "${_INDEX_BOT_DIR}/.." && pwd)"

cd "${_INDEX_BOT_DIR}"

ensure_index_bot_dependencies() {
  local req_file="${_INDEX_BOT_DIR}/requirements-all.txt"
  local import_check="import telegram, sqlalchemy, telethon, dotenv, uvicorn, fastapi, tmdbv3api, regex"
  local db_url="${DATABASE_URL:-}"
  if [[ -z "${db_url}" && -f "${_INDEX_BOT_DIR}/.env" ]]; then
    db_url="$(rg '^DATABASE_URL=' "${_INDEX_BOT_DIR}/.env" -n --no-heading 2>/dev/null | sed 's/^[0-9]*:DATABASE_URL=//')"
  fi
  if [[ "${db_url,,}" == *postgres* ]]; then
    import_check="${import_check}, psycopg"
  fi
  if [[ ! -f "${req_file}" ]]; then
    if [[ -f "${_INDEX_ROOT_DIR}/requirements/bot-index.txt" ]]; then
      req_file="${_INDEX_ROOT_DIR}/requirements/bot-index.txt"
    else
      req_file="${_INDEX_BOT_DIR}/requirements.txt"
    fi
  fi

  if [[ -x "${_INDEX_ROOT_DIR}/scripts/setup_env.sh" ]]; then
    if [[ ! -d "${_INDEX_ROOT_DIR}/.venv" ]]; then
      echo "Creating shared virtualenv at ${_INDEX_ROOT_DIR}/.venv ..."
      "${_INDEX_ROOT_DIR}/scripts/setup_env.sh"
    fi
    # shellcheck source=/dev/null
    source "${_INDEX_ROOT_DIR}/.venv/bin/activate"

    if ! python -c "${import_check}" 2>/dev/null; then
      echo "Installing Index_bot dependencies from ${req_file} ..."
      pip install --upgrade pip wheel
      pip install -r "${req_file}"
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

  if ! python -c "${import_check}" 2>/dev/null; then
    echo "Installing dependencies from ${req_file} ..."
    pip install --upgrade pip wheel
    pip install -r "${req_file}"
  fi
}
