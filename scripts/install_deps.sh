#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: ./scripts/install_deps.sh <target>"
  echo "Targets: main | name-bot | caption | tg-download | down_oad | upload | index | launcher | all"
  exit 1
fi

BOT_ID="$1"

"${ROOT_DIR}/scripts/setup_env.sh"

# shellcheck source=/dev/null
source "${ROOT_DIR}/.venv/bin/activate"

install_bot() {
  local req_file="$1"
  echo "Installing ${req_file}..."
  python -m pip install -r "${ROOT_DIR}/requirements/${req_file}"
}

install_launcher() {
  echo "Installing launcher_requirements.txt..."
  python -m pip install -r "${ROOT_DIR}/launcher_requirements.txt"
}

case "${BOT_ID}" in
  main)
    install_bot "bot-name-bot.txt"
    ;;
  name-bot)
    install_bot "bot-name-bot.txt"
    ;;
  caption)
    install_bot "bot-caption.txt"
    ;;
  tg-download)
    install_bot "bot-tg-download.txt"
    ;;
  down_oad)
    install_bot "bot-down_oad.txt"
    ;;
  upload)
    install_bot "bot-upload.txt"
    ;;
  index)
    install_bot "bot-index.txt"
    ;;
  launcher)
    install_launcher
    ;;
  all)
    install_bot "bot-name-bot.txt"
    install_bot "bot-caption.txt"
    install_bot "bot-tg-download.txt"
    install_bot "bot-down_oad.txt"
    install_bot "bot-upload.txt"
    install_bot "bot-index.txt"
    install_launcher
    ;;
  *)
    echo "Unknown bot: ${BOT_ID}"
    echo "Targets: main | name-bot | caption | tg-download | down_oad | upload | index | launcher | all"
    exit 1
    ;;
esac

echo "✅ Dependencies installed for ${BOT_ID}."
