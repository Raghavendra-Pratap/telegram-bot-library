"""
Global "heavy task" guard — show please-wait while long admin jobs block the bot.
"""
from __future__ import annotations

import asyncio
from html import escape

from telegram import Update
from telegram.ext import ContextTypes

_BUSY_KEY = "heavy_task"
UPLOAD_ACTIVE_KEY = "upload_job_active"
_lock = asyncio.Lock()


def upload_job_active(application) -> bool:
    """True while a Telethon bulk upload job is sending files (indexing should yield)."""
    return bool(application and application.bot_data.get(UPLOAD_ACTIVE_KEY))


async def wait_while_upload_active(application, *, max_wait_s: float = 600) -> None:
    """Let bulk upload own the DB writer; ingest/index runs after or between files."""
    if not application:
        return
    waited = 0.0
    while upload_job_active(application) and waited < max_wait_s:
        await asyncio.sleep(0.75)
        waited += 0.75


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


def exclusive_job_running(application) -> bool:
    """True while a Telethon-scale exclusive job holds the background lock."""
    return is_busy(application)


async def reject_if_exclusive_busy(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    """
    Block starting another exclusive job (discover, ingest, verify, bulk upload).
    Returns True if blocked — navigation and menus are not affected.
    """
    if not exclusive_job_running(context.application):
        return False
    query = update.callback_query
    if query:
        from telegram_flood import flood_answer_callback

        await flood_answer_callback(query, busy_alert(context.application), show_alert=True)
    elif update.message:
        await update.message.reply_text(busy_alert(context.application))
    return True


def busy_banner_html(application) -> str:
    """Short notice to prepend above a normal menu while a heavy job runs."""
    from job_queue import get_job_queue

    reason = escape(busy_reason(application) or "a large operation")
    extra = ""
    jq = get_job_queue(application)
    if jq:
        depth = jq.pending_count()
        if depth > 0:
            extra = f"\n<i>{depth} job(s) queued — yours will run in order.</i>"
    return (
        f"⏳ <b>Background task:</b> {reason}\n"
        "<i>Use the buttons below — channel indexing continues separately.</i>"
        f"{extra}"
    )


def busy_message_html(application) -> str:
    """Standalone busy notice (prefer showing main menu + busy_banner_html instead)."""
    return busy_banner_html(application)


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


async def reply_busy_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    reply_markup=None,
) -> bool:
    """If busy, send or edit a please-wait notice and return True."""
    if not is_busy(context.application):
        return False
    text = busy_message_html(context.application)
    query = update.callback_query
    if query and query.message:
        from telegram_flood import safe_edit_callback_message

        await safe_edit_callback_message(
            query, text, parse_mode="HTML", reply_markup=reply_markup
        )
        return True
    if update.message:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=reply_markup
        )
        return True
    return True
