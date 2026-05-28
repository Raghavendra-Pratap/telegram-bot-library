"""Optional deep links and buttons for file delivery / external downloader bot."""
from __future__ import annotations

from telegram import InlineKeyboardButton

from config import Config
from watch_deep_links import bot_start_url, file_start_payload


def index_bot_file_url(bot_username: str, upload_id: int) -> str:
    return bot_start_url(bot_username, file_start_payload(upload_id))


def down_oad_file_url(upload_id: int) -> str | None:
    """Deep link to companion downloader bot (if configured)."""
    user = (Config.DOWN_OAD_BOT_USERNAME or "").strip().lstrip("@")
    if not user:
        return None
    return bot_start_url(user, file_start_payload(upload_id))


def external_downloader_row(upload_id: int) -> list[InlineKeyboardButton] | None:
    url = down_oad_file_url(upload_id)
    if not url:
        return None
    return [InlineKeyboardButton("📥 Download helper", url=url)]
