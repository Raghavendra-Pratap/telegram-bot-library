"""
Telegram Bot API rate limiting and flood-wait retries.

Use for every bot.send_*, edit_*, delete_*, and callback answer so large
channels and batch publishes stay within Telegram limits.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, TypeVar

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, NetworkError, RetryAfter, TelegramError, TimedOut

from config import Config

logger = logging.getLogger(__name__)

T = TypeVar("T")

_global_lock = asyncio.Lock()
_global_last = 0.0
_per_chat_last: dict[str, float] = defaultdict(float)
_per_chat_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

_FLOOD_RE = re.compile(
    r"(?:retry after|retry in)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def parse_retry_after_text(text: str) -> float | None:
    return parse_retry_after_seconds(Exception(text))


def parse_retry_after_seconds(exc: BaseException) -> float | None:
    if isinstance(exc, RetryAfter):
        return float(exc.retry_after)
    msg = str(exc)
    lower = msg.lower()
    if "flood control" not in lower and "too many requests" not in lower:
        return None
    m = _FLOOD_RE.search(msg)
    if m:
        return float(m.group(1))
    return 30.0


def is_unchanged_message_error(exc: BadRequest) -> bool:
    return "message is not modified" in str(exc).lower()


def _is_no_text_message_error(exc: BadRequest) -> bool:
    return "there is no text in the message" in str(exc).lower()


def _is_flood_bad_request(exc: BadRequest) -> bool:
    msg = str(exc).lower()
    return "flood control" in msg or "too many requests" in msg


def _is_permanent_bad_request(exc: BadRequest) -> bool:
    """Do not retry — markup/text is invalid or message is gone."""
    msg = str(exc).lower()
    return (
        is_unchanged_message_error(exc)
        or "button_data_invalid" in msg
        or "can't parse entities" in msg
        or "can't parse message text" in msg
        or "message to edit not found" in msg
        or "message can't be edited" in msg
        or "message_id_invalid" in msg
        or "message not found" in msg
        or "there is no text in the message" in msg
        or "there is no caption" in msg
    )


def _needs_caption_edit(message) -> bool:
    if not message:
        return False
    return bool(message.photo or message.video or message.animation or message.document)


def _is_channel_media_post(message) -> bool:
    """Catalog poster in a public channel — do not replace caption for one user."""
    if not message or not message.chat:
        return False
    if str(getattr(message.chat, "type", "")).lower() != "channel":
        return False
    return _needs_caption_edit(message)


def _is_delivered_file_message(message) -> bool:
    """Copied video/file in DM — picker UI must be a separate text message."""
    if not message:
        return False
    return bool(message.document or message.video or message.audio)


def watch_channel_chat_id(channel) -> int | str:
    if channel.channel_username:
        return f"@{channel.channel_username}"
    return int(channel.channel_id)


async def throttle(chat_id: Any = None) -> None:
    """Enforce minimum spacing between API calls (global + per-chat)."""
    global _global_last
    min_gap = Config.TELEGRAM_MIN_API_INTERVAL
    chat_key = str(chat_id) if chat_id is not None else "_global"

    async with _per_chat_locks[chat_key]:
        now = time.monotonic()
        wait = min_gap - (now - _per_chat_last[chat_key])
        if wait > 0:
            await asyncio.sleep(wait)
        _per_chat_last[chat_key] = time.monotonic()

    async with _global_lock:
        now = time.monotonic()
        wait = min_gap - (now - _global_last)
        if wait > 0:
            await asyncio.sleep(wait)
        _global_last = time.monotonic()


def _backoff_seconds(attempt: int, retry_after: float | None) -> float:
    if retry_after is not None:
        base = min(60.0, retry_after + 1.5)
    else:
        base = min(15.0, 2.0 ** attempt + 1.0)
    jitter = random.uniform(0.2, 0.8)
    return base + jitter


async def call_with_flood_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    chat_id: Any = None,
    max_retries: int | None = None,
    label: str = "telegram_api",
) -> T:
    if max_retries is None:
        if "edit_message" in label:
            max_retries = Config.TELEGRAM_EDIT_MAX_RETRIES
        else:
            max_retries = Config.TELEGRAM_FLOOD_MAX_RETRIES
    last_exc: BaseException | None = None
    for attempt in range(max_retries):
        await throttle(chat_id)
        try:
            return await coro_factory()
        except RetryAfter as e:
            wait = _backoff_seconds(attempt, float(e.retry_after))
            logger.warning("%s RetryAfter %.1fs (attempt %s/%s)", label, wait, attempt + 1, max_retries)
            await asyncio.sleep(wait)
            last_exc = e
        except (TimedOut, NetworkError) as e:
            wait = _backoff_seconds(attempt, None)
            logger.warning("%s %s, sleep %.1fs (attempt %s/%s)", label, type(e).__name__, wait, attempt + 1, max_retries)
            await asyncio.sleep(wait)
            last_exc = e
        except BadRequest as e:
            if is_unchanged_message_error(e):
                raise
            if _is_flood_bad_request(e):
                ra = parse_retry_after_seconds(e)
                wait = _backoff_seconds(attempt, ra)
                logger.warning("%s flood BadRequest, sleep %.1fs (attempt %s/%s)", label, wait, attempt + 1, max_retries)
                await asyncio.sleep(wait)
                last_exc = e
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise TelegramError(f"{label} failed after {max_retries} retries")


async def batch_pause(delay_s: float | None = None) -> None:
    delay = Config.TELEGRAM_PUBLISH_DELAY if delay_s is None else delay_s
    if delay > 0:
        await asyncio.sleep(delay)


def _is_benign_callback_answer_error(exc: BadRequest) -> bool:
    msg = str(exc).lower()
    return (
        "query is too old" in msg
        or "query id is invalid" in msg
        or "response timeout expired" in msg
        or "query is too short" in msg
        or "already answered" in msg
    )


async def flood_answer_callback(query, text: str | None = None, *, show_alert: bool = False):
    """Acknowledge a callback; never retry permanent BadRequest failures."""
    chat_id = query.message.chat_id if query.message else None
    await throttle(chat_id)
    try:
        return await query.answer(text=text, show_alert=show_alert)
    except BadRequest as e:
        if _is_benign_callback_answer_error(e):
            return None
        raise


async def flood_edit_message_text(
    edit_target,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> None:
    msg = edit_target.message if hasattr(edit_target, "message") else edit_target
    chat_id = msg.chat_id if msg else None
    if msg and _needs_caption_edit(msg):
        bot = edit_target.get_bot() if hasattr(edit_target, "get_bot") else msg.get_bot()
        await flood_edit_message_caption(
            bot,
            chat_id,
            msg.message_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    await call_with_flood_retry(
        lambda: edit_target.edit_message_text(
            text, reply_markup=reply_markup, parse_mode=parse_mode
        ),
        chat_id=chat_id,
        label="edit_message_text",
    )


async def present_callback_ui(
    query,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> bool:
    """Show picker UI: DM user for channel catalog cards; else edit in place."""
    from telegram.error import Forbidden

    user = getattr(query, "from_user", None)
    if not user:
        msg = getattr(query, "message", None)
        if msg and getattr(query, "_message_anchor", False):
            bot = msg.get_bot()
            await flood_send_message(
                bot,
                msg.chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        return False
    msg = query.message
    if msg and _is_channel_media_post(msg):
        bot = query.get_bot()
        try:
            await flood_send_message(
                bot,
                user.id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        except Forbidden:
            uname = getattr(bot, "username", None) or "bot"
            await query.answer(
                f"Tap ▶ Watch on the card to open @{uname}, or send /start here first.",
                show_alert=True,
            )
            return False
    return await safe_edit_callback_message(
        query, text, reply_markup=reply_markup, parse_mode=parse_mode
    )


async def present_watch_picker_ui(
    query,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> bool:
    """Episode/quality hub — never rewrite a delivered file's caption."""
    from telegram.error import Forbidden

    user = query.from_user
    if not user:
        return False
    msg = query.message
    if msg and _is_channel_media_post(msg):
        return await present_callback_ui(
            query, text, reply_markup=reply_markup, parse_mode=parse_mode
        )
    if msg and _is_delivered_file_message(msg):
        bot = query.get_bot()
        try:
            await flood_send_message(
                bot,
                msg.chat_id,
                text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return True
        except Forbidden:
            uname = getattr(bot, "username", None) or "bot"
            await query.answer(
                f"Open @{uname} in DM first (send /start).",
                show_alert=True,
            )
            return False
    return await safe_edit_callback_message(
        query, text, reply_markup=reply_markup, parse_mode=parse_mode
    )


async def safe_edit_callback_message(
    query,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> bool:
    """Edit the message behind a callback (text or photo caption); reply if edit fails."""
    msg = query.message
    if not msg:
        return False
    bot = query._bot if getattr(query, "_bot", None) else msg.get_bot()
    chat_id = msg.chat_id
    message_id = msg.message_id

    async def edit_caption() -> None:
        await flood_edit_message_caption(
            bot,
            chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    async def edit_text() -> None:
        await flood_edit_message_text(
            query, text, reply_markup=reply_markup, parse_mode=parse_mode
        )

    order = (edit_caption, edit_text) if _needs_caption_edit(msg) else (edit_text, edit_caption)
    for edit_fn in order:
        try:
            await edit_fn()
            return True
        except BadRequest as e:
            if is_unchanged_message_error(e):
                return True
            err = str(e).lower()
            if "no text in the message" in err or "there is no caption" in err:
                continue
            logger.warning("safe_edit_callback_message: %s", e)
            break
        except TelegramError as e:
            logger.warning("safe_edit_callback_message: %s", e)
            break

    try:
        await flood_reply_text(
            msg,
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except Exception as e:
        logger.warning("safe_edit_callback_message reply fallback: %s", e)
        return False


async def flood_bot_edit_message_text(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> None:
    await flood_bot_edit_message_ui(
        bot,
        chat_id,
        message_id,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def flood_bot_edit_message_ui(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    *,
    reply_markup=None,
    parse_mode=ParseMode.HTML,
) -> None:
    """Edit status text; fall back to caption for photo messages."""
    try:
        await call_with_flood_retry(
            lambda: bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            ),
            chat_id=chat_id,
            label="bot_edit_message_text",
        )
    except BadRequest as e:
        if is_unchanged_message_error(e):
            return
        if _is_no_text_message_error(e):
            await call_with_flood_retry(
                lambda: bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                ),
                chat_id=chat_id,
                label="bot_edit_message_caption",
            )
            return
        raise


async def flood_send_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    *,
    parse_mode=ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
    disable_web_page_preview: bool = False,
):
    return await call_with_flood_retry(
        lambda: bot.send_message(
            chat_id,
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        ),
        chat_id=chat_id,
        label="send_message",
    )


async def flood_copy_message(
    bot: Bot,
    chat_id: int | str,
    from_chat_id: int | str,
    message_id: int,
    *,
    caption: str | None = None,
    parse_mode=ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    """Copy a channel post into DM without forward attribution."""
    kwargs: dict[str, Any] = {
        "chat_id": chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id,
    }
    if caption is not None:
        kwargs["caption"] = caption
        kwargs["parse_mode"] = parse_mode
    if reply_markup is not None:
        kwargs["reply_markup"] = reply_markup

    return await call_with_flood_retry(
        lambda: bot.copy_message(**kwargs),
        chat_id=chat_id,
        label="copy_message",
    )


async def flood_send_photo(
    bot: Bot,
    chat_id: int | str,
    *,
    photo: str,
    caption: str | None = None,
    parse_mode=ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
):
    return await call_with_flood_retry(
        lambda: bot.send_photo(
            chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        ),
        chat_id=chat_id,
        label="send_photo",
    )


async def flood_edit_message_caption(
    bot: Bot,
    chat_id: int | str,
    message_id: int,
    caption: str,
    *,
    parse_mode=ParseMode.HTML,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    await call_with_flood_retry(
        lambda: bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        ),
        chat_id=chat_id,
        label="edit_message_caption",
    )


async def flood_delete_message(bot: Bot, chat_id: int, message_id: int) -> None:
    await call_with_flood_retry(
        lambda: bot.delete_message(chat_id=chat_id, message_id=message_id),
        chat_id=chat_id,
        label="delete_message",
    )


async def flood_reply_photo(message, **kwargs):
    chat_id = message.chat_id
    return await call_with_flood_retry(
        lambda: message.reply_photo(**kwargs),
        chat_id=chat_id,
        label="reply_photo",
    )


async def flood_reply_text(message, **kwargs):
    chat_id = message.chat_id
    return await call_with_flood_retry(
        lambda: message.reply_text(**kwargs),
        chat_id=chat_id,
        label="reply_text",
    )
