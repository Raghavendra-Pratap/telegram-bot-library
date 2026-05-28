"""Telegram bot hooks for the watch portal."""
from __future__ import annotations

import os

from telegram import Update
from telegram.ext import ContextTypes

from config import Config
from database import Database

db = Database()


def portal_public_url() -> str:
    return (os.getenv("PORTAL_PUBLIC_URL") or "http://127.0.0.1:8765").rstrip("/")


async def portal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return
    token = db.create_portal_session(user.id)
    if not token:
        await update.message.reply_text("❌ Could not create portal session.")
        return
    url = f"{portal_public_url()}/?token={token}"
    await update.message.reply_text(
        f"🌐 <b>Watch portal</b>\n\n"
        f"Open in your browser (phone, TV, or desktop):\n"
        f"<a href=\"{url}\">Open library</a>\n\n"
        f"<i>Link expires in 72 hours. Bookmark after login.</i>\n\n"
        f"<code>{url}</code>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_portal_start_payload(
    update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str
) -> bool:
    if not payload.startswith("portal_"):
        return False
    token = payload[7:].strip()
    uid = db.get_portal_user_id(token)
    if not uid:
        await update.message.reply_text(
            "❌ Portal link expired or invalid. Send /portal for a new link."
        )
        return True
    url = f"{portal_public_url()}/?token={token}"
    await update.message.reply_text(
        f"🌐 <b>Watch portal</b>\n\n"
        f"<a href=\"{url}\">Tap to open</a> in your browser.\n\n"
        f"<i>Same link works on TV browser — use Play to send files to Telegram "
        f"or stream smaller files in-browser.</i>",
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return True
