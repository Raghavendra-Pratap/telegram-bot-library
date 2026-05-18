"""
Global "heavy task" guard — show please-wait while long admin jobs block the bot.
"""
from __future__ import annotations

import asyncio
from html import escape

from telegram import Update
from telegram.ext import ContextTypes

_BUSY_KEY = "heavy_task"
_lock = asyncio.Lock()


def is_busy(application) -> bool:
    from job_queue import get_job_queue

    jq = get_job_queue(application)
    if jq and jq.exclusive_label():
        return True
    return bool(application.bot_data.get(_BUSY_KEY))


def busy_reason(application) -> str | None:
    from job_queue import get_job_queue

    jq = get_job_queue(application)
    if jq and jq.exclusive_label():
        return jq.exclusive_label()
    return application.bot_data.get(_BUSY_KEY)


def busy_alert(application) -> str:
    reason = busy_reason(application) or "a large task"
    return f"⏳ Please wait — {reason} is still running."


def busy_message_html(application) -> str:
    from job_queue import get_job_queue

    reason = escape(busy_reason(application) or "a large operation")
    extra = ""
    jq = get_job_queue(application)
    if jq:
        depth = jq.pending_count()
        if depth > 0:
            extra = f"\n<i>{depth} job(s) queued — yours will run in order.</i>"
    return (
        "⏳ <b>Please wait</b>\n\n"
        f"The bot is busy with:\n<b>{reason}</b>\n\n"
        "<i>Commands still work; heavy tasks run in the background queue. "
        "Channel indexing continues separately.</i>"
        f"{extra}"
    )


async def try_acquire(application, reason: str) -> bool:
    """Legacy guard — prefer enqueue_background(exclusive=True) for new code."""
    if is_busy(application):
        return False
    async with _lock:
        if application.bot_data.get(_BUSY_KEY):
            return False
        application.bot_data[_BUSY_KEY] = reason
        return True


def release(application) -> None:
    application.bot_data.pop(_BUSY_KEY, None)


async def answer_busy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """If a heavy task is running, notify via callback alert and return True (caller should stop)."""
    query = update.callback_query
    if not query or not is_busy(context.application):
        return False
    from telegram_flood import flood_answer_callback

    await flood_answer_callback(query, busy_alert(context.application), show_alert=True)
    return True


async def reply_busy_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """If busy, send or edit a please-wait notice and return True."""
    if not is_busy(context.application):
        return False
    text = busy_message_html(context.application)
    query = update.callback_query
    if query and query.message:
        from telegram_flood import safe_edit_callback_message

        await safe_edit_callback_message(query, text, parse_mode="HTML")
        return True
    if update.message:
        await update.message.reply_text(text, parse_mode="HTML")
        return True
    return True
