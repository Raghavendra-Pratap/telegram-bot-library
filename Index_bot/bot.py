"""
Main Telegram Bot for Index Bot
"""
import asyncio
import atexit
import logging
import os
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from types import SimpleNamespace
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageOriginChannel
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatType, ParseMode, ChatMemberStatus
from telegram.error import BadRequest

from config import Config
from database import Database, Channel, FileUpload, CustomList
from name_parser import NameParser
from tmdb_helper import split_title_year, tmdb_helper
from media_utils import is_indexable_filename
from title_indexer import build_index_metadata, build_pick_metadata, episode_display_name, gather_tmdb_suggestions
from series_grouping import (
    batched_pending_file_ids,
    build_pending_groups,
    sibling_pending_ids,
    show_group_key,
)
from channel_status import channel_list_label_with_status, channel_status_lines
from tmdb_helper import format_suggestion_card_caption, poster_image_url, titles_match
from file_variant import extract_quality_label, format_file_size
from watch_library import (
    build_delivery_text,
    build_bulk_share_summary_keyboard,
    build_bulk_share_summary_text,
    build_episode_hub_keyboard,
    build_episode_hub_text,
    build_episode_list_text,
    build_quality_list_text,
    build_title_hub_text,
    channel_message_link,
    copy_delivery_error_hint,
    dedupe_upload_variants,
    deliver_upload_to_chat,
    episode_label,
    format_variant_button_label,
    filter_watchable_media_uploads,
    group_tv_episodes,
    message_link_for_upload,
    parse_ep_callback_parts,
    pick_best_upload,
    sort_variants,
    upload_channel_label,
    _ep_callback_parts,
)
from message_verify import (
    filter_watchable_uploads,
    telethon_configured,
    telethon_session_path,
    verify_upload_list_for_watch,
)
from message_verify import run_verify_sweep
from tracking_stats import (
    build_tracking_list_keyboard,
    collection_tracking_counts,
    format_collection_tracking_detail,
    format_multipart_tracking_detail,
    format_tv_tracking_detail,
)
from watch_channel import maybe_auto_publish_watch
import watch_features
import upload_features
import vault_features
import archive_browse
import library_setup
import bot_busy
from upload_pipeline import extract_message_file, index_channel_upload
from job_queue import enqueue_background, enqueue_ingest, enqueue_interactive, start_job_queue
from telegram_flood import (
    batch_pause,
    flood_answer_callback,
    flood_bot_edit_message_text,
    flood_bot_edit_message_ui,
    flood_delete_message,
    flood_edit_message_text,
    flood_reply_photo,
    flood_reply_text,
    flood_send_message,
    flood_send_photo,
    is_unchanged_message_error,
    present_callback_ui,
    present_watch_picker_ui,
    safe_edit_callback_message,
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Enable debug logging for channel detection
logging.getLogger('telegram.ext').setLevel(logging.INFO)

# Initialize components
db = Database()
parser = NameParser()


def _fire_background_job(
    application,
    name: str,
    coro_factory,
    *,
    exclusive: bool = False,
) -> None:
    async def _run() -> None:
        await enqueue_background(application, name, coro_factory, exclusive=exclusive)

    application.create_task(_run())


def _fire_interactive_job(application, name: str, coro_factory) -> None:
    async def _run() -> None:
        await enqueue_interactive(application, name, coro_factory)

    application.create_task(_run())


def _is_stale_callback_error(exc: BadRequest) -> bool:
    msg = str(exc).lower()
    return "query is too old" in msg or "query id is invalid" in msg


async def safe_answer_callback(query, text: str | None = None, *, show_alert: bool = False) -> bool:
    """Acknowledge a button press; return False if the query expired (>~30s old)."""
    try:
        await flood_answer_callback(query, text=text, show_alert=show_alert)
        return True
    except BadRequest as e:
        msg = str(e).lower()
        if _is_stale_callback_error(e):
            logger.debug("Stale callback query (use /menu or Pending for a fresh message): %s", e)
            return False
        if "query is too old" in msg or "query id is invalid" in msg:
            return False
        if (
            "query is too short" in msg
            or "already answered" in msg
            or "response timeout" in msg
        ):
            return True
        raise


async def safe_edit_message(query, text: str, reply_markup=None, *, parse_mode=ParseMode.HTML) -> bool:
    """Edit callback message; return False if content unchanged or edit not allowed."""
    try:
        return await present_callback_ui(
            query, text, reply_markup=reply_markup, parse_mode=parse_mode
        )
    except BadRequest as e:
        if is_unchanged_message_error(e):
            return False
        if "message can't be edited" in str(e).lower():
            logger.warning("Cannot edit message: %s", e)
            return False
        logger.warning("edit_message_text failed: %s", e)
        return False


def _ui_anchor_bot(query, context: ContextTypes.DEFAULT_TYPE):
    if hasattr(query, "get_bot"):
        return query.get_bot()
    return context.bot


async def _send_tmdb_suggestion_card(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    photo: str | None,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> object | None:
    """Post one suggestion card (reply or send with reply_to for HeaderEditAnchor)."""
    msg = query.message
    if hasattr(msg, "reply_photo") and photo:
        return await flood_reply_photo(
            msg,
            photo=photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    if hasattr(msg, "reply_text") and not photo:
        return await flood_reply_text(
            msg,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
        )
    bot = _ui_anchor_bot(query, context)
    reply_to = msg.message_id
    chat_id = msg.chat_id
    if photo:
        return await flood_send_photo(
            bot,
            chat_id,
            photo=photo,
            caption=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup,
            reply_to_message_id=reply_to,
        )
    return await flood_send_message(
        bot,
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to,
    )


async def _send_tmdb_suggestion_cards(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    suggestions: list[dict],
    pick_callback,
    *,
    file_id: int | None = None,
    match_key: str | None = None,
    start_index: int = 0,
    clear_existing: bool = True,
) -> None:
    """One Telegram message per TMDB match (poster + plot + Select button)."""
    chat_id = query.message.chat_id
    if clear_existing:
        await _clear_tmdb_suggestion_cards(
            context, chat_id, file_id=file_id, match_key=match_key
        )
        _remember_tmdb_pick_header(query, context, file_id=file_id, match_key=match_key)

    msg_ids: list[int] = list(
        context.user_data.get(_tmdb_card_msgs_key(file_id=file_id, match_key=match_key))
        or []
    )
    for i, s in enumerate(suggestions):
        global_i = start_index + i
        cap = format_suggestion_card_caption(s, global_i + 1)
        if len(cap) > 1024:
            cap = cap[:1020] + "…"
        markup = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Select this title",
                        callback_data=pick_callback(global_i),
                    )
                ]
            ]
        )
        img_url = poster_image_url(s)
        sent = None
        try:
            sent = await _send_tmdb_suggestion_card(
                query,
                context,
                photo=img_url or None,
                text=cap,
                reply_markup=markup,
            )
        except BadRequest as e:
            logger.warning("Suggestion card %s photo failed: %s", i + 1, e)
            try:
                sent = await _send_tmdb_suggestion_card(
                    query,
                    context,
                    photo=None,
                    text=cap,
                    reply_markup=markup,
                )
            except Exception as e2:
                logger.warning("Suggestion card %s text failed: %s", i + 1, e2)
        except Exception as e:
            logger.warning("Suggestion card %s failed: %s", i + 1, e)
        if sent:
            msg_ids.append(sent.message_id)

    context.user_data[_tmdb_card_msgs_key(file_id=file_id, match_key=match_key)] = msg_ids


class MessageUiAnchor:
    """Edit the bot message used as the UI surface (e.g. TMDB search status)."""

    _message_anchor = True

    def __init__(self, message):
        self.message = message
        self.from_user = message.from_user

    def get_bot(self):
        return self.message.get_bot()


class HeaderEditAnchor:
    """Edit an existing bot message (pending map auto-advance)."""

    _header_edit_anchor = True

    def __init__(self, bot, chat_id: int, message_id: int, from_user=None):
        self.from_user = from_user
        self.message = SimpleNamespace(
            chat_id=chat_id,
            message_id=message_id,
            chat=SimpleNamespace(id=chat_id),
            from_user=from_user,
        )
        self._bot = bot

    def get_bot(self):
        return self._bot

    async def edit_message_text(
        self,
        text: str,
        reply_markup=None,
        parse_mode=ParseMode.HTML,
    ) -> None:
        await flood_bot_edit_message_text(
            self._bot,
            self.message.chat_id,
            self.message.message_id,
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


def _parsed_release_year(parsed: dict | None) -> int | None:
    if not parsed:
        return None
    try:
        y = parsed.get("year")
        return int(y) if y else None
    except (TypeError, ValueError):
        return None


async def _fetch_tmdb_pick_page(
    query_text: str,
    *,
    media_type: str,
    parsed: dict | None,
    page: int = 1,
    filter_type: str = "all",
) -> dict:
    year_int = _parsed_release_year(parsed)
    _, emb = split_title_year(query_text)
    if emb is not None:
        year_int = emb
    return await asyncio.to_thread(
        tmdb_helper.search_pick_page,
        query_text,
        page=page,
        filter_type=filter_type,
        media_type=media_type,
        year=year_int,
    )


async def _apply_tmdb_pick_page_to_meta(
    meta: dict,
    query_text: str,
    *,
    media_type: str,
    parsed: dict | None,
    page: int = 1,
    filter_type: str = "all",
) -> dict:
    pick = await _fetch_tmdb_pick_page(
        query_text,
        media_type=media_type,
        parsed=parsed,
        page=page,
        filter_type=filter_type,
    )
    meta["suggestions"] = pick.get("items") or []
    meta["pick_page"] = page
    meta["pick_has_more"] = bool(pick.get("has_more"))
    meta["pick_filter"] = filter_type
    meta["pick_query"] = query_text
    meta["tmdb_unreachable"] = bool(tmdb_helper._last_api_error) and not meta["suggestions"]
    return pick


def _tmdb_load_more_row(
    meta: dict, *, gid: int | None = None, file_id: int | None = None
) -> list[InlineKeyboardButton]:
    if not meta.get("pick_has_more"):
        return []
    if gid is not None:
        return [
            InlineKeyboardButton(
                "📄 Load more results", callback_data=f"tpml:g:{gid}"
            )
        ]
    if file_id is not None:
        return [
            InlineKeyboardButton(
                "📄 Load more results", callback_data=f"tpml:f:{file_id}"
            )
        ]
    return []


def _format_batch_files_preview(group: dict, *, max_lines: int = 6) -> str:
    ep_lines = []
    for f in sorted(
        group.get("files") or [],
        key=lambda x: (x.get("parsed") or {}).get("episode") or 0,
    ):
        ep_lines.append(
            f"• <code>{escape(_truncate_for_telegram(f['file_name'], 48))}</code>"
        )
    preview = "\n".join(ep_lines[:max_lines])
    if len(ep_lines) > max_lines:
        preview += f"\n<i>…and {len(ep_lines) - max_lines} more</i>"
    return preview or "<i>(no files)</i>"


async def reply_or_edit_query(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
) -> None:
    """Edit the callback message, or send a new one if edit fails."""
    if getattr(query, "_message_anchor", False):
        await bot_edit_message(
            context,
            query.message.chat_id,
            query.message.message_id,
            text,
            reply_markup,
        )
        return
    if getattr(query, "_header_edit_anchor", False):
        await bot_edit_message(
            context,
            query.message.chat_id,
            query.message.message_id,
            text,
            reply_markup,
        )
        return
    if await safe_edit_message(query, text, reply_markup=reply_markup):
        return
    try:
        bot = query.get_bot() if hasattr(query, "get_bot") else context.bot
        await flood_send_message(
            bot,
            query.message.chat_id,
            text,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error("reply_text fallback failed: %s", e)


def _truncate_for_telegram(text: str, max_len: int = 180) -> str:
    text = text or ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


async def bot_edit_message(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
) -> bool:
    """Edit a message by chat/id (for background jobs)."""
    try:
        await flood_bot_edit_message_ui(
            context.bot,
            chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
        )
        return True
    except BadRequest as e:
        if is_unchanged_message_error(e):
            return False
        logger.warning("edit_message failed: %s", e)
        return False


def format_backfill_progress(
    *,
    mode_label: str,
    source_label: str,
    ingest_label: str,
    phase: str,
    scanned: int,
    forwarded: int,
    skipped: int,
    elapsed_s: float,
    duplicates: int = 0,
) -> str:
    mins, secs = divmod(int(elapsed_s), 60)
    elapsed = f"{mins}m {secs}s" if mins else f"{secs}s"
    media_label = "Media found" if "dry" in mode_label.lower() else "Media forwarded"
    dup_line = ""
    if duplicates:
        dup_line = f"Already in library (dupes): <b>{duplicates:,}</b>\n"
    return (
        f"▶️ <b>{escape(mode_label)}</b>\n\n"
        f"Source: <b>{escape(source_label)}</b>\n"
        f"→ <b>{escape(ingest_label)}</b>\n\n"
        f"Status: <i>{escape(phase)}</i>\n"
        f"⏱ Elapsed: <b>{elapsed}</b>\n\n"
        f"Messages scanned: <b>{scanned:,}</b>\n"
        f"{media_label}: <b>{forwarded:,}</b>\n"
        f"Skipped (no media): <b>{skipped:,}</b>\n"
        f"{dup_line}\n"
        "<i>Live updates — safe to browse other menus while this runs.</i>"
    )


def is_admin(user_id):
    """Check if user is admin"""
    return Config.is_admin(user_id)


_MONITORABLE_CHAT_TYPES = (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP)
_JOIN_STATUSES = (
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.OWNER,
)
_LEFT_STATUSES = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)


def _ingest_channel_id_str() -> str | None:
    ingest = db.get_ingest_channel()
    return str(ingest.channel_id) if ingest else None


def _forward_source_chat(message):
    """Channel/group chat from a forwarded message (PTB v20+ forward_origin, legacy fallback)."""
    origin = getattr(message, "forward_origin", None)
    if isinstance(origin, MessageOriginChannel) and origin.chat:
        return origin.chat
    if origin is not None:
        chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if chat and getattr(chat, "type", None) in _MONITORABLE_CHAT_TYPES:
            return chat
    legacy = getattr(message, "forward_from_chat", None)
    if legacy and legacy.type in _MONITORABLE_CHAT_TYPES:
        return legacy
    return None


def resolve_forward_source_channel(message) -> str | None:
    """
    Channel id of the original archive when this post is a forward.

    Never returns the ingest/backfill sink channel — that would double-count files.
    Uses active historical-ingest source as fallback when forward metadata is missing
    (delivery can still resolve via ingest channel post).
    """
    ingest_id = _ingest_channel_id_str()

    def _accept(cid: str | None) -> str | None:
        if not cid:
            return None
        if ingest_id and cid == ingest_id:
            return None
        return cid

    chat = _forward_source_chat(message)
    if chat:
        log_source = (
            "forward_origin" if getattr(message, "forward_origin", None) else "forward_from_chat"
        )
        register_chat_channel(chat, log_source=log_source)
        got = _accept(str(chat.id))
        if got:
            return got
    try:
        from forward_ingest import get_active_backfill_source_id

        return _accept(get_active_backfill_source_id())
    except ImportError:
        return None


def register_chat_channel(
    chat, *, log_source: str = "unknown", bot_can_post: bool | None = None
) -> Channel | None:
    """Save a Telegram chat to the channels table if it is a channel/group we can monitor."""
    if chat.type not in _MONITORABLE_CHAT_TYPES:
        return None
    if bot_can_post is None:
        from bot_channel_access import BOT_POST_LOG_SOURCES

        bot_can_post = log_source in BOT_POST_LOG_SOURCES
    try:
        channel = db.auto_register_channel(
            channel_id=str(chat.id),
            channel_username=getattr(chat, "username", None),
            channel_title=chat.title,
            bot_can_post=bool(bot_can_post),
        )
        logger.info(
            "Registered channel via %s: %s (%s)",
            log_source,
            chat.title or chat.id,
            chat.id,
        )
        return channel
    except Exception as e:
        logger.error("Failed to register channel via %s: %s", log_source, e, exc_info=True)
        return None


def channel_button_label(channel, max_len=60):
    """Short label for inline keyboard buttons."""
    title = channel.channel_title or "Unknown"
    if channel.channel_username:
        suffix = f"@{channel.channel_username}"
    else:
        suffix = channel.channel_id
    label = f"{title} ({suffix})"
    if len(label) > max_len:
        return label[: max_len - 3] + "..."
    return label


def channel_list_button_label(channel, file_count: int | None = None, max_len=64) -> str:
    """Channel label with optional indexed file count (Telegram button limit ~64 chars)."""
    count_suffix = f" · {file_count}" if file_count is not None else ""
    inner_max = max_len - len(count_suffix)
    base = channel_button_label(channel, max_len=inner_max)
    return f"{base}{count_suffix}"


TITLE_PICK_LIST_KEY = "title_pick_list"


def store_title_pick_list(context, titles: list[str]) -> None:
    """Store titles for index-based callbacks (Telegram callback_data max 64 bytes)."""
    context.user_data[TITLE_PICK_LIST_KEY] = list(titles)


def resolve_title_pick(context, idx: int) -> str | None:
    titles = context.user_data.get(TITLE_PICK_LIST_KEY) or []
    if 0 <= idx < len(titles):
        return titles[idx]
    return None


def build_title_pick_rows(
    grouped: dict,
    *,
    max_items: int = 20,
    label_max: int = 36,
) -> list[list[InlineKeyboardButton]]:
    """Build keyboard rows with callback_data title_pick:{index}."""
    rows = []
    for i, (name, uploads) in enumerate(list(grouped.items())[:max_items]):
        short = name if len(name) <= label_max else name[: label_max - 3] + "..."
        count = len(uploads)
        rows.append(
            [
                InlineKeyboardButton(
                    f"🎬 {short} ({count})",
                    callback_data=f"title_pick:{i}",
                )
            ]
        )
    return rows


def channel_telegram_ref(channel) -> str:
    """@username or numeric id for Telethon / forward_ingest."""
    if channel.channel_username:
        return f"@{channel.channel_username}"
    return str(channel.channel_id)


def tmdb_status_line(title: str, content_title=None) -> str:
    """One-line TMDB sync status for library views."""
    if not tmdb_helper.enabled:
        return "🎬 <b>TMDB:</b> not configured (<code>TMDB_API_KEY</code> in .env)\n"
    ms = content_title or db.get_movie_series(title)
    if ms and ms.tmdb_id:
        kind = (
            "Movie"
            if ms.media_type == "movie"
            else "Series"
            if ms.media_type in ("tv", "series")
            else (ms.media_type or "Title")
        )
        label = ms.tmdb_title or ms.name
        extra = ""
        if ms.release_year:
            extra += f" · {ms.release_year}"
        if ms.vote_average:
            extra += f" · ⭐ {escape(str(ms.vote_average))}"
        return (
            f"🎬 <b>TMDB:</b> ✅ {escape(label)} · {escape(kind)}"
            f" · ID <code>{ms.tmdb_id}</code>{extra}\n"
        )
    return "🎬 <b>TMDB:</b> no match stored (will retry on next index if API enabled)\n"


def _tmdb_sug_key(file_id: int) -> str:
    return f"tmdb_sug_{file_id}"


def _tmdb_card_msgs_key(*, file_id: int | None = None, match_key: str | None = None) -> str:
    if match_key is not None:
        return f"tmdb_card_msgs_bulk_{match_key}"
    return f"tmdb_card_msgs_{file_id}"


def _tmdb_header_msg_key(*, file_id: int | None = None, match_key: str | None = None) -> str:
    if match_key is not None:
        return f"tmdb_header_msg_bulk_{match_key}"
    return f"tmdb_header_msg_{file_id}"


def _bulk_tmdb_header_match_key(
    context: ContextTypes.DEFAULT_TYPE, match_key: str
) -> str:
    """User-data key for bulk TMDB header (group id when available)."""
    group = _resolve_pending_group(context, match_key)
    if group and group.get("group_id") is not None:
        return str(group["group_id"])
    return str(match_key)


async def _clear_tmdb_suggestion_cards(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    *,
    file_id: int | None = None,
    match_key: str | None = None,
) -> None:
    """Remove poster/card messages from the chat."""
    key = _tmdb_card_msgs_key(file_id=file_id, match_key=match_key)
    for mid in context.user_data.pop(key, None) or []:
        try:
            await flood_delete_message(context.bot, chat_id, mid)
        except BadRequest:
            pass
        except Exception as e:
            logger.debug("Could not delete suggestion card %s: %s", mid, e)


def _remember_tmdb_pick_header(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    file_id: int | None = None,
    match_key: str | None = None,
) -> None:
    context.user_data[_tmdb_header_msg_key(file_id=file_id, match_key=match_key)] = (
        query.message.message_id
    )


async def _finish_tmdb_pick_success(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    file_id: int | None = None,
    match_key: str | None = None,
) -> None:
    """Delete suggestion cards and show success on the header message."""
    await _clear_tmdb_suggestion_cards(
        context, chat_id, file_id=file_id, match_key=match_key
    )
    header_id = context.user_data.pop(
        _tmdb_header_msg_key(file_id=file_id, match_key=match_key), None
    )
    if header_id:
        try:
            await flood_bot_edit_message_text(
                context.bot,
                chat_id,
                header_id,
                text,
                reply_markup=reply_markup,
            )
            return
        except BadRequest as e:
            if not is_unchanged_message_error(e):
                logger.warning("Edit TMDB header after pick failed: %s", e)
    try:
        await flood_send_message(
            context.bot,
            chat_id,
            text,
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.warning("Send TMDB pick success fallback failed: %s", e)


def _next_pending_map_target(
    *,
    skip_match_key: str | None = None,
    skip_file_id: int | None = None,
) -> dict | None:
    """Next batch group or single file to map (batches first)."""
    pending = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    if not pending:
        return None
    groups = build_pending_groups(pending, parser=parser)
    batched_ids = batched_pending_file_ids(groups)
    for group in groups:
        if group.get("deferred"):
            continue
        if skip_match_key and group["match_key"] == skip_match_key:
            continue
        return {"kind": "batch", "match_key": group["match_key"]}
    for upload in pending:
        if upload.id in batched_ids:
            continue
        if getattr(upload, "pending_deferred_at", None):
            continue
        if skip_file_id is not None and upload.id == skip_file_id:
            continue
        return {
            "kind": "file",
            "file_id": upload.id,
            "file_name": upload.file_name,
            "parsed_name": upload.parsed_name,
        }
    return None


def _refresh_pending_groups_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    pending_files = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    groups = build_pending_groups(pending_files, parser=parser)
    context.user_data["pending_groups"] = groups
    context.user_data["pending_groups_by_key"] = {g["match_key"]: g for g in groups}
    _sync_pending_bulk_map(context, groups)


async def _finish_pending_map_and_continue(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    success_text: str,
    query=None,
    from_user=None,
    file_id: int | None = None,
    match_key: str | None = None,
) -> None:
    """Show map success, then open the next pending batch/file (pending queue only)."""
    if query is not None:
        chat_id = query.message.chat_id
        from_user = getattr(query, "from_user", None)

    if context.user_data.get("remap_back_cb"):
        back_cb = context.user_data.get("remap_back_cb", "pending_menu")
        back_label = context.user_data.get("remap_back_label", "« Pending")
        await _finish_tmdb_pick_success(
            context,
            chat_id,
            success_text,
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(back_label, callback_data=back_cb)]]
            ),
            file_id=file_id,
            match_key=match_key,
        )
        return

    await _clear_tmdb_suggestion_cards(
        context, chat_id, file_id=file_id, match_key=match_key
    )
    header_id = context.user_data.pop(
        _tmdb_header_msg_key(file_id=file_id, match_key=match_key), None
    )
    if header_id is None and query is not None:
        header_id = query.message.message_id

    skip_key = match_key
    if match_key and str(match_key).isdigit():
        group = _resolve_pending_group(context, match_key)
        if group:
            skip_key = group["match_key"]

    next_target = _next_pending_map_target(
        skip_match_key=skip_key,
        skip_file_id=file_id,
    )
    remaining = db.count_pending_confirmations()

    if not next_target:
        done_text = success_text
        if remaining > 0:
            done_text += (
                f"\n\n<i>{remaining:,} file(s) still pending — open /menu → Pending.</i>"
            )
        else:
            done_text += "\n\n✅ <b>All caught up — nothing left to map!</b>"
        markup = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("« Pending list", callback_data="pending_menu")],
                [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
            ]
        )
        if header_id:
            await bot_edit_message(context, chat_id, header_id, done_text, markup)
        else:
            await flood_send_message(context.bot, chat_id, done_text, reply_markup=markup)
        return

    if header_id:
        await bot_edit_message(
            context,
            chat_id,
            header_id,
            f"{success_text}\n\n⏳ <b>Opening next pending…</b>",
            None,
        )
    else:
        msg = await flood_send_message(
            context.bot,
            chat_id,
            f"{success_text}\n\n⏳ <b>Opening next pending…</b>",
        )
        header_id = msg.message_id

    anchor = HeaderEditAnchor(context.bot, chat_id, header_id, from_user)
    _refresh_pending_groups_context(context)

    async def _open_next() -> None:
        try:
            if next_target["kind"] == "batch":
                await _run_bulk_tmdb_pick_job(anchor, context, next_target["match_key"])
            else:
                await _run_tmdb_pick_job(
                    anchor,
                    context,
                    next_target["file_id"],
                    file_name=next_target["file_name"],
                    parsed_name=next_target["parsed_name"],
                )
        except Exception as e:
            logger.exception("Auto-advance pending failed")
            await bot_edit_message(
                context,
                chat_id,
                header_id,
                f"{success_text}\n\n❌ <b>Could not open next pending</b>\n"
                f"<code>{escape(str(e))}</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
                ),
            )

    _fire_interactive_job(
        context.application,
        "Pending auto-advance",
        _open_next,
    )


def _browse_back_callback_data(context) -> str:
    if context.user_data.get("browse_scope") == "all":
        return "library_all"
    return "library_browse"


def _browse_entry_title(entry) -> str:
    """Resolve display title from browse list entry (dict or legacy str)."""
    if isinstance(entry, str):
        return entry
    return (entry or {}).get("title") or ""


def format_library_button_label(entry: dict, *, max_len: int = 64) -> str:
    """🎬 movie vs 📺 series vs 🎓 course on library buttons."""
    mt = (entry.get("media_type") or "movie").lower()
    if mt == "course":
        icon = "🎓"
    elif mt in ("tv", "series"):
        icon = "📺"
    else:
        icon = "🎬"
    title = (entry.get("title") or "?").strip()
    if len(title) > 26:
        title = title[:23] + "…"
    yr = entry.get("release_year")
    yr_s = f" ({yr})" if yr else ""
    vote_s = ""
    vote = entry.get("vote_average")
    if vote not in (None, ""):
        try:
            vote_s = f" ★{float(vote):.1f}"
        except (TypeError, ValueError):
            pass
    label = f"{icon} {title}{yr_s}{vote_s}"
    if len(label) > max_len:
        label = f"{icon} {title[:18]}…{yr_s}{vote_s}"
    return label


def _browse_entry_and_scope(context, idx: int):
    titles = context.user_data.get("browse_titles", [])
    if idx >= len(titles):
        return None
    entry = titles[idx]
    list_name = context.user_data.get("browse_list")
    channel_ids = db.get_channels_for_list(list_name) if list_name else None
    return entry, channel_ids


def _is_tv_entry(entry: dict, ct) -> bool:
    mt = (entry.get("media_type") or (ct.media_type if ct else "") or "movie").lower()
    return mt in ("tv", "series")


def _upload_stats_from_list(uploads: list) -> dict:
    watchable = filter_watchable_uploads(uploads)
    channels: dict = {}
    for u in watchable:
        gid = u.source_channel_id or u.channel_id
        channels[gid] = channels.get(gid, 0) + 1
    return {
        "total_uploads": len(watchable),
        "channels": channels,
        "unavailable": len(uploads) - len(watchable),
    }


async def send_title_hub(query, context, idx: int) -> bool:
    """Title landing: Watch, Details, optional admin remap."""
    resolved = _browse_entry_and_scope(context, idx)
    if not resolved:
        await query.answer("Title not found", show_alert=True)
        return False
    entry, channel_ids = resolved
    ct_id = entry.get("content_title_id")
    ct = db.get_content_title(ct_id) if ct_id else None
    uploads = (
        db.get_library_uploads_for_content(ct_id, channel_ids) if ct_id else []
    )
    stats = _upload_stats_from_list(uploads)
    text = build_title_hub_text(entry, ct, stats)
    if ct and getattr(ct, "catalog_excluded", False):
        text += "\n\n<i>🚫 Excluded from watch channel — will not publish catalog cards.</i>"
    back_cb = _browse_back_callback_data(context)
    back_label = "« Full library" if back_cb == "library_all" else "« Browse"
    rows = [
        [InlineKeyboardButton("▶ Watch", callback_data=f"watch_title:{idx}")],
        [InlineKeyboardButton(back_label, callback_data=back_cb)],
        [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
    ]
    uid = query.from_user.id if query.from_user else 0
    admin_user = is_admin(query.from_user.id if query.from_user else 0)
    if ct_id and uid:
        rows.insert(
            1,
            [
                InlineKeyboardButton("⭐ Favorite", callback_data=f"watch_fav:{ct_id}"),
                InlineKeyboardButton("📋 Watchlist", callback_data=f"watch_wl:{ct_id}"),
            ],
        )
    if admin_user:
        rows.insert(
            1,
            [InlineKeyboardButton("📋 File details", callback_data=f"lib_details:{idx}")],
        )
    if admin_user:
        rows.insert(
            2,
            [
                InlineKeyboardButton(
                    "✏️ Change TMDB mapping",
                    callback_data=f"remap_title:{idx}",
                )
            ],
        )
    await present_callback_ui(
        query,
        text,
        reply_markup=InlineKeyboardMarkup(rows),
    )
    return True


async def send_watch_episode_list(
    query,
    context,
    idx: int,
    uploads: list | None = None,
    *,
    reply_message=None,
    message_prefix: str | None = None,
) -> bool:
    resolved = _browse_entry_and_scope(context, idx)
    if not resolved:
        if reply_message is not None:
            await reply_message.reply_text("❌ Title not found.", parse_mode=ParseMode.HTML)
        else:
            await query.answer("Title not found", show_alert=True)
        return False
    entry, channel_ids = resolved
    ct_id = entry.get("content_title_id")
    if not ct_id:
        if reply_message is not None:
            await reply_message.reply_text(
                "❌ Title not linked to library.", parse_mode=ParseMode.HTML
            )
        else:
            await query.answer("Title not linked to library", show_alert=True)
        return False
    if uploads is None:
        uploads = db.get_library_uploads_for_content(ct_id, channel_ids)
        if not uploads:
            if reply_message is not None:
                await reply_message.reply_text(
                    "❌ No files in library.", parse_mode=ParseMode.HTML
                )
            else:
                await query.answer("No files in library", show_alert=True)
            return False
        if reply_message is None:
            uploads = await _verify_uploads_for_watch(query, uploads)
            if not uploads:
                await query.answer("No available episodes", show_alert=True)
                return False
    uploads = filter_watchable_media_uploads(uploads)
    if not uploads:
        if reply_message is not None:
            await reply_message.reply_text(
                "❌ No video files available.", parse_mode=ParseMode.HTML
            )
        else:
            await query.answer("No video files", show_alert=True)
        return False
    title = _browse_entry_title(entry)
    episodes = group_tv_episodes(uploads)
    context.user_data["watch_episode_keys"] = [ep_key for ep_key, _ in episodes]
    context.user_data["watch_ep_ct_id"] = ct_id
    text = build_episode_list_text(title)
    if message_prefix:
        text = message_prefix + text
    rows = []
    for ep_key, variants in episodes:
        season, episode = ep_key
        s_part, e_part = _ep_callback_parts(season, episode)
        label = episode_label(season, episode)
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"watch_ep:{ct_id}:{s_part}:{e_part}",
                )
            ]
        )
    if len(episodes) > 1:
        rows.append(
            [
                InlineKeyboardButton(
                    "📦 Send all episodes",
                    callback_data=f"watch_all:{ct_id}",
                )
            ]
        )
    if message_prefix:
        rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    else:
        rows.append([InlineKeyboardButton("« Title", callback_data=f"lib_idx:{idx}")])
        rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    context.user_data["watch_browse_idx"] = idx
    markup = InlineKeyboardMarkup(rows)
    if reply_message is not None:
        await reply_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif query is not None:
        await present_watch_picker_ui(query, text, reply_markup=markup)
    return True


async def send_watch_quality_list(
    query,
    context,
    *,
    idx: int | None,
    ct_id: int,
    uploads: list,
    season: int | None = None,
    episode: int | None = None,
    back_cb: str | None = None,
    back_label: str = "« Back",
    reply_message=None,
    message_prefix: str | None = None,
) -> bool:
    entry = None
    if idx is not None:
        resolved = _browse_entry_and_scope(context, idx)
        if resolved:
            entry, _ = resolved
    title = _browse_entry_title(entry) if entry else "?"
    if not title or title == "?":
        ct = db.get_content_title(ct_id)
        title = db.display_title_for_content(ct, "?")
    ep_line = None
    if season is not None or episode is not None:
        ep_line = episode_label(season, episode)
    admin_user = False
    if query is not None and query.from_user:
        admin_user = is_admin(query.from_user.id)
    elif reply_message is not None and reply_message.from_user:
        admin_user = is_admin(reply_message.from_user.id)
    uploads = filter_watchable_media_uploads(uploads)
    variants = dedupe_upload_variants(uploads)
    if not variants:
        if query is not None:
            await query.answer("No versions available", show_alert=True)
        return False

    ct = db.get_content_title(ct_id) if ct_id else None
    is_tv = ct and (ct.media_type or "movie").lower() in ("tv", "series")
    use_episode_hub = is_tv and bool(context.user_data.get("watch_episode_keys"))

    if back_cb is None:
        if use_episode_hub and idx is not None:
            back_cb = f"watch_title:{idx}"
            back_label = "« Episodes"
        elif idx is not None:
            back_cb = f"lib_idx:{idx}"
            back_label = "« Title"
        else:
            back_cb = "main_menu"

    context.user_data["watch_back_cb"] = back_cb
    context.user_data["watch_back_label"] = back_label
    context.user_data["watch_browse_idx"] = idx
    context.user_data["watch_hub_ct_id"] = ct_id
    context.user_data["watch_hub_episode"] = (season, episode)

    if use_episode_hub:
        current_key = (season, episode)
        text = build_episode_hub_text(
            title,
            episode_line=ep_line,
            simple_prompt=not admin_user,
        )
        if message_prefix:
            text = message_prefix + text
        markup = build_episode_hub_keyboard(
            variants,
            ct_id,
            context,
            current_key,
            browse_idx=idx,
            back_cb=back_cb if not message_prefix else None,
            back_label=back_label,
            admin=admin_user,
            include_favorites=not admin_user,
        )
    else:
        text = build_quality_list_text(
            title,
            episode_line=ep_line,
            variant_count=len(variants),
            simple_prompt=not admin_user,
        )
        if message_prefix:
            text = message_prefix + text
        rows = []
        for u in variants:
            rows.append(
                [
                    InlineKeyboardButton(
                        f"▶ {format_variant_button_label(u, admin=admin_user)}",
                        callback_data=f"watch_pick:{u.id}",
                    )
                ]
            )
        if not message_prefix:
            rows.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
        rows.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
        markup = InlineKeyboardMarkup(rows)

    if reply_message is not None:
        await reply_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    elif query is not None:
        await present_watch_picker_ui(query, text, reply_markup=markup)
    return True


async def _verify_uploads_for_watch(query, uploads: list) -> list:
    """On-demand Telethon check (stale rows only); returns watchable uploads."""
    if not uploads:
        return uploads
    if telethon_configured() and telethon_session_path().exists():
        await safe_edit_message(
            query,
            "⏳ <b>Checking channel posts…</b>\n\n<i>Verifying files are still in Telegram.</i>",
            reply_markup=None,
        )
        return await verify_upload_list_for_watch(uploads, db)
    return filter_watchable_uploads(uploads)


async def _remove_hub_message(bot, chat_id: int, message) -> None:
    """Delete the text picker hub so files can stack above a fresh menu."""
    if not message or not getattr(message, "text", None):
        return
    try:
        await flood_delete_message(bot, chat_id, message.message_id)
    except Exception as e:
        logger.debug("could not delete hub message: %s", e)


async def _place_watch_hub_below(
    bot,
    chat_id: int,
    *,
    old_message,
    text: str,
    reply_markup=None,
) -> None:
    """Drop the old hub and post controls under any files just delivered."""
    await _remove_hub_message(bot, chat_id, old_message)
    await flood_send_message(
        bot, chat_id, text, reply_markup=reply_markup, parse_mode=ParseMode.HTML
    )


async def send_all_episodes(query, context, ct_id: int) -> bool:
    """Deliver best quality for every episode (TV season scope)."""
    chat_id = query.message.chat_id if query.message else None
    if not chat_id:
        await query.answer("Could not send", show_alert=True)
        return False

    list_name = context.user_data.get("browse_list")
    channel_ids = db.get_channels_for_list(list_name) if list_name else None
    slot_season = context.user_data.get("watch_slot_season")
    uploads = db.get_library_uploads_for_content(
        ct_id, channel_ids, season_number=slot_season
    )
    uploads = filter_watchable_media_uploads(uploads)
    if not uploads:
        await query.answer("No episodes found", show_alert=True)
        return False

    episodes = group_tv_episodes(uploads)
    if len(episodes) <= 1:
        await query.answer("Only one episode in this list", show_alert=True)
        return False

    hub_message = query.message
    await _remove_hub_message(context.bot, chat_id, hub_message)

    ct = db.get_content_title(ct_id)
    title = db.display_title_for_content(ct, "?") if ct else "?"

    sent = 0
    failed = 0
    for _ep_key, ep_uploads in episodes:
        best = pick_best_upload(ep_uploads)
        if not best:
            failed += 1
            continue
        quality = extract_quality_label(best.file_name)
        try:
            await deliver_upload_to_chat(
                context.bot,
                chat_id,
                best,
                ct,
                quality=quality,
                reply_markup=None,
            )
            sent += 1
        except Exception as e:
            logger.warning(
                "bulk episode send failed upload_id=%s: %s", best.id, e
            )
            failed += 1
        await batch_pause(2.0)

    text = build_bulk_share_summary_text(title, sent, failed=failed)
    markup = build_bulk_share_summary_keyboard(
        ct_id,
        browse_idx=context.user_data.get("watch_browse_idx"),
        back_cb=context.user_data.get("watch_back_cb"),
        back_label=context.user_data.get("watch_back_label", "« Episodes"),
        include_favorites=True,
    )
    await flood_send_message(
        context.bot, chat_id, text, reply_markup=markup, parse_mode=ParseMode.HTML
    )
    return True


async def send_watch_pick(query, context, upload_id: int) -> bool:
    upload = db.get_file_upload(upload_id)
    if not upload:
        await query.answer("File not found", show_alert=True)
        return False
    checked = await verify_upload_list_for_watch([upload], db)
    if not checked:
        await present_callback_ui(
            query,
            "⚠️ <b>This version is no longer available.</b>\n\n"
            "Try another quality or episode.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "« Back",
                            callback_data=context.user_data.get(
                                "watch_back_cb", "main_menu"
                            ),
                        )
                    ],
                    [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
                ]
            ),
        )
        return False
    upload = checked[0]
    ct = (
        db.get_content_title(upload.content_title_id)
        if upload.content_title_id
        else None
    )
    quality = extract_quality_label(upload.file_name)
    admin_user = is_admin(query.from_user.id if query.from_user else 0)
    chat_id = query.message.chat_id if query.message else None
    if not chat_id:
        await query.answer("Could not deliver file", show_alert=True)
        return False

    mt = (ct.media_type if ct else "movie") or "movie"
    is_tv = mt in ("tv", "series")
    ct_id = upload.content_title_id

    try:
        await deliver_upload_to_chat(
            context.bot,
            chat_id,
            upload,
            ct,
            quality=quality,
            reply_markup=None,
        )
    except Exception as e:
        logger.error(
            "copy_message delivery failed upload_id=%s channel=%s msg=%s: %s",
            upload.id,
            upload.channel_id,
            upload.message_id,
            e,
        )
        hint = copy_delivery_error_hint(e)
        await present_callback_ui(
            query,
            f"❌ <b>Could not send this file.</b>\n\n{hint}",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "« Back",
                            callback_data=context.user_data.get(
                                "watch_back_cb", "main_menu"
                            ),
                        )
                    ],
                ]
            ),
        )
        return False

    rows = []
    catalog = None
    if upload.content_title_id and ct:
        mt = (ct.media_type or "movie").lower()
        sn = (
            upload.season_number
            if mt in ("tv", "series")
            else None
        )
        if mt in ("tv", "series") and sn is None:
            sn = 1
        catalog = db.get_watch_catalog_post(upload.content_title_id, sn)
    if catalog:
        wlink = channel_message_link(catalog.watch_channel_id, catalog.message_id)
        if wlink:
            rows.append([InlineKeyboardButton("📺 Catalog card", url=wlink)])
    if admin_user:
        link = message_link_for_upload(upload)
        if link:
            rows.append([InlineKeyboardButton("📎 Source channel", url=link)])
    from delivery_handoff import external_downloader_row

    ext_row = external_downloader_row(upload.id)
    if ext_row:
        rows.append(ext_row)
    await _refresh_watch_hub_after_send(
        query, context, upload, ct, quality=quality, admin_user=admin_user, is_tv=is_tv
    )
    return True


async def _refresh_watch_hub_after_send(
    query,
    context,
    upload,
    ct,
    *,
    quality: str,
    admin_user: bool,
    is_tv: bool,
) -> None:
    """Update the text hub below delivery (never rewrite the file caption)."""
    ct_id = upload.content_title_id
    current_key = (upload.season_number, upload.episode_number)
    sent_line = episode_label(
        upload.season_number, upload.episode_number, upload.episode_title
    )
    idx = context.user_data.get("watch_browse_idx")
    back_cb = context.user_data.get("watch_back_cb", "main_menu")
    back_label = context.user_data.get("watch_back_label", "« Back")
    title = db.display_title_for_content(ct, "?") if ct else "?"

    if is_tv and ct_id and context.user_data.get("watch_episode_keys"):
        list_name = context.user_data.get("browse_list")
        channel_ids = db.get_channels_for_list(list_name) if list_name else None
        slot_season = context.user_data.get("watch_slot_season")
        all_uploads = db.get_library_uploads_for_content(
            ct_id, channel_ids, season_number=slot_season
        )
        ep_uploads = [
            u
            for u in filter_watchable_media_uploads(all_uploads)
            if (u.season_number, u.episode_number) == current_key
        ]
        variants = dedupe_upload_variants(ep_uploads)
        ep_line = sent_line
        text = build_episode_hub_text(
            title,
            episode_line=ep_line,
            sent_episode_line=sent_line,
            simple_prompt=not admin_user,
            files_above=True,
        )
        markup = build_episode_hub_keyboard(
            variants,
            ct_id,
            context,
            current_key,
            browse_idx=idx,
            back_cb=back_cb,
            back_label=back_label,
            admin=admin_user,
            include_favorites=not admin_user,
        )
        chat_id = query.message.chat_id if query.message else None
        if chat_id:
            await _place_watch_hub_below(
                context.bot,
                chat_id,
                old_message=query.message,
                text=text,
                reply_markup=markup,
            )
        return

    if admin_user:
        from delivery_handoff import external_downloader_row

        rows = []
        link = message_link_for_upload(upload)
        if link:
            rows.append([InlineKeyboardButton("📎 Source channel", url=link)])
        ext_row = external_downloader_row(upload.id)
        if ext_row:
            rows.append(ext_row)
        rows.append([InlineKeyboardButton("« Back", callback_data=back_cb)])
        text = build_delivery_text(upload, ct, quality=quality, admin=True)
        text = f"{text}\n\n<i>↑ File sent above — menu below.</i>"
        markup = InlineKeyboardMarkup(rows) if rows else None
    else:
        text = f"✅ <b>{escape(sent_line)}</b> shared above."
        markup = InlineKeyboardMarkup(
            [[InlineKeyboardButton("« Menu", callback_data="main_menu")]]
        )
    chat_id = query.message.chat_id if query.message else None
    if chat_id:
        await _place_watch_hub_below(
            context.bot,
            chat_id,
            old_message=query.message,
            text=text,
            reply_markup=markup,
        )


async def send_watch_title(query, context, idx: int) -> bool:
    """Route to episode list (TV) or quality list (movie / single episode)."""
    resolved = _browse_entry_and_scope(context, idx)
    if not resolved:
        await query.answer("Title not found", show_alert=True)
        return False
    entry, channel_ids = resolved
    ct_id = entry.get("content_title_id")
    if not ct_id:
        await query.answer("Title not linked to library", show_alert=True)
        return False
    uploads = db.get_library_uploads_for_content(ct_id, channel_ids)
    if not uploads:
        await query.answer("No files in library", show_alert=True)
        return False
    uploads = await _verify_uploads_for_watch(query, uploads)
    if not uploads:
        await present_callback_ui(
            query,
            "⚠️ <b>No available files</b>\n\n"
            "Indexed posts for this title appear to have been removed from the channel.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("« Title", callback_data=f"lib_idx:{idx}")],
                    [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
                ]
            ),
        )
        return False
    uploads = filter_watchable_media_uploads(uploads)
    if not uploads:
        await query.answer("No video files available", show_alert=True)
        return False
    context.user_data[f"watch_uploads_{ct_id}"] = [u.id for u in uploads]
    ct = db.get_content_title(ct_id)
    context.user_data["watch_browse_idx"] = idx
    if _is_tv_entry(entry, ct):
        episodes = group_tv_episodes(uploads)
        context.user_data["watch_episode_keys"] = [ep_key for ep_key, _ in episodes]
        context.user_data["watch_ep_ct_id"] = ct_id
        if len(episodes) == 1:
            ep_key, ep_uploads = episodes[0]
            season, episode = ep_key
            return await send_watch_quality_list(
                query,
                context,
                idx=idx,
                ct_id=ct_id,
                uploads=ep_uploads,
                season=season,
                episode=episode,
                back_cb=f"lib_idx:{idx}",
                back_label="« Title",
            )
        return await send_watch_episode_list(query, context, idx, uploads=uploads)
    return await send_watch_quality_list(
        query,
        context,
        idx=idx,
        ct_id=ct_id,
        uploads=uploads,
        back_cb=f"lib_idx:{idx}",
        back_label="« Title",
    )


def build_library_message(movie_name: str, channel_ids=None) -> str:
    """HTML library detail text with TMDB line."""
    if channel_ids:
        stats = db.get_upload_stats_in_channels(movie_name, channel_ids)
    else:
        stats = db.get_upload_stats(movie_name)
    ct = db.get_movie_series(movie_name)
    display_header = db.display_title_for_content(ct, movie_name)
    kind_line = ""
    if ct and ct.media_type == "tv":
        kind_line = "📺 <b>TV series</b> — files grouped by episode under this show.\n"
    elif ct and ct.media_type == "movie":
        kind_line = "🎬 <b>Movie</b>"
        if ct.franchise_sequence:
            kind_line += f" · franchise #{ct.franchise_sequence}"
        kind_line += "\n"
    meta_bits = []
    if ct and ct.release_year:
        meta_bits.append(str(ct.release_year))
    if ct and ct.vote_average:
        try:
            meta_bits.append(f"★{float(ct.vote_average):.1f}")
        except (TypeError, ValueError):
            pass
    meta_line = ""
    if meta_bits:
        meta_line = f"{' · '.join(meta_bits)}\n"
    lines = [
        f"<b>📚 {escape(display_header)}</b>\n",
        kind_line,
        meta_line,
        tmdb_status_line(display_header, content_title=ct),
        f"📊 <b>{stats['total_uploads']}</b> upload(s) · <b>{len(stats['channels'])}</b> channel(s)\n",
        "<b>Files:</b>\n",
    ]
    for channel_id, channel_data in stats["channels"].items():
        channel_title = channel_data.get("channel_title") or "Unknown"
        channel_username = channel_data.get("channel_username")
        username = f"@{channel_username}" if channel_username else channel_id
        via_ingest = channel_data.get("via_ingest_title")
        if via_ingest:
            lines.append(
                f"📺 <b>Source:</b> {escape(channel_title)} ({escape(str(username))}) "
                f"— {channel_data['count']}×\n"
                f"   <i>via ingest: {escape(via_ingest)}</i>\n"
            )
        else:
            lines.append(
                f"📺 <b>{escape(channel_title)}</b> ({escape(str(username))}) — {channel_data['count']}×\n"
            )
        for upload_data in sorted(
            channel_data["uploads"],
            key=lambda x: x.get("uploaded_at") or datetime.min.replace(tzinfo=None),
            reverse=True,
        )[:5]:
            uploaded_at = upload_data.get("uploaded_at")
            date_str = uploaded_at.strftime("%Y-%m-%d") if uploaded_at else "?"
            status = "✅" if upload_data.get("is_confirmed") else "⏳"
            file_name = upload_data.get("file_name", "Unknown")
            ep_bits = []
            if upload_data.get("season_number") is not None:
                ep_bits.append(f"S{upload_data['season_number']:02d}E{upload_data.get('episode_number') or 0:02d}")
            if upload_data.get("episode_title"):
                ep_bits.append(escape(str(upload_data["episode_title"])))
            ep_label = f" ({', '.join(ep_bits)})" if ep_bits else ""
            lines.append(
                f"  {status} <code>{escape(file_name)}</code>{ep_label} ({date_str})\n"
            )
        extra = len(channel_data["uploads"]) - 5
        if extra > 0:
            lines.append(f"  <i>…and {extra} more file(s)</i>\n")
    return "".join(lines)


PENDING_PAGE_SIZE = 10
TMDB_PICK_TIMEOUT_S = 18.0


def _tmdb_sug_key_bulk(group_id: int | str) -> str:
    return f"tmdb_bulk_suggestions_{group_id}"


def _sync_pending_bulk_map(context: ContextTypes.DEFAULT_TYPE, groups: list) -> None:
    context.user_data["pending_bulk_gid"] = {
        str(g["group_id"]): g["match_key"] for g in groups
    }


def _resolve_bulk_ref(context: ContextTypes.DEFAULT_TYPE, ref: str) -> str | None:
    """Map short batch id (pg:3) or legacy match_key to show_group_key."""
    gid_map = context.user_data.get("pending_bulk_gid") or {}
    if ref.isdigit() and ref in gid_map:
        return gid_map[ref]
    group = _resolve_pending_group(context, ref)
    return group["match_key"] if group else None


def _bulk_meta_key(group_id: int | str) -> str:
    return f"tmdb_bulk_meta_{group_id}"


def _refresh_pending_groups(context: ContextTypes.DEFAULT_TYPE) -> list:
    pending_files = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    groups = build_pending_groups(pending_files, parser=parser)
    context.user_data["pending_groups"] = groups
    context.user_data["pending_groups_by_key"] = {g["match_key"]: g for g in groups}
    return groups


def _resolve_pending_group(context: ContextTypes.DEFAULT_TYPE, match_key: str) -> dict | None:
    by_key = context.user_data.get("pending_groups_by_key") or {}
    if match_key in by_key:
        return by_key[match_key]
    groups = _refresh_pending_groups(context)
    by_key = {g["match_key"]: g for g in groups}
    context.user_data["pending_groups_by_key"] = by_key
    return by_key.get(match_key)


async def send_pending_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int = 0,
    batch_page: int = 0,
    edit: bool = False,
) -> None:
    """Paginated pending files list (avoids huge messages / stuck buttons)."""
    query = update.callback_query
    target = query if edit and query else update
    total = db.count_pending_confirmations()
    pending_files = db.get_pending_confirmations(limit=Config.PENDING_SCAN_LIMIT)
    if total == 0:
        await _reply_or_edit(
            target,
            "✅ No files pending confirmation.",
            InlineKeyboardMarkup([[InlineKeyboardButton("« Main menu", callback_data="main_menu")]]),
            edit=edit,
        )
        return

    groups = build_pending_groups(pending_files, parser=parser)
    batched_ids = batched_pending_file_ids(groups)
    ungrouped = [f for f in pending_files if f.id not in batched_ids]
    n_batched = len(batched_ids)
    n_ungrouped = len(ungrouped)
    n_groups = len(groups)
    batch_ps = max(1, Config.PENDING_BATCH_PAGE_SIZE)
    batch_pages = max(1, (n_groups + batch_ps - 1) // batch_ps) if n_groups else 1
    batch_page = max(0, min(batch_page, batch_pages - 1))
    context.user_data["pending_batch_page"] = batch_page
    display_groups = groups[batch_page * batch_ps : (batch_page + 1) * batch_ps]
    pages = max(1, (n_ungrouped + PENDING_PAGE_SIZE - 1) // PENDING_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    context.user_data["pending_page"] = page
    chunk = ungrouped[page * PENDING_PAGE_SIZE : (page + 1) * PENDING_PAGE_SIZE]

    context.user_data["pending_groups"] = groups
    context.user_data["pending_groups_by_key"] = {g["match_key"]: g for g in groups}
    _sync_pending_bulk_map(context, groups)

    lines = [
        "<b>⏳ Pending confirmation</b>",
        f"<b>{total}</b> file(s) pending",
    ]
    if n_groups:
        lines.append(
            f"<b>{n_groups}</b> batch group(s)"
            + (f" · <b>{n_batched}</b> files in batches" if n_batched else "")
            + (f" · <b>{n_ungrouped}</b> singles" if n_ungrouped else "")
        )
        if batch_pages > 1:
            lines.append(f"Batches · page <b>{batch_page + 1}</b>/{batch_pages}")
    if n_ungrouped:
        lines.append(f"Singles · page <b>{page + 1}</b>/{pages}")
    if total > len(pending_files):
        lines.append(
            f"<i>Grouped from first {len(pending_files):,} rows — use Retry TMDB to refresh all.</i>"
        )
    lines.extend(
        [
            "<i>Active titles first · skipped batches/files at the end · use a fresh /menu → Pending</i>",
            "",
        ]
    )
    keyboard = []
    if tmdb_helper.enabled and total > 0:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"🔄 Retry TMDB (all {total:,} pending)",
                    callback_data="pending_retry_all",
                )
            ]
        )
        lines.append(
            "<i>Network blip? Retry TMDB re-searches every pending video/audio file.</i>"
        )
        lines.append("")
    if display_groups:
        lines.append("<b>Batch map</b> — one TMDB pick for a whole series:")
        lines.append("")
        for g in display_groups:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        g["label"],
                        callback_data=f"pg:{g['group_id']}",
                    )
                ]
            )
        batch_nav = []
        if batch_page > 0:
            batch_nav.append(
                InlineKeyboardButton(
                    "« Batches",
                    callback_data=f"pending_batch_page:{batch_page - 1}:{page}",
                )
            )
        if batch_page + 1 < batch_pages:
            batch_nav.append(
                InlineKeyboardButton(
                    "Batches »",
                    callback_data=f"pending_batch_page:{batch_page + 1}:{page}",
                )
            )
        if batch_nav:
            keyboard.append(batch_nav)
    if n_ungrouped:
        if display_groups:
            lines.append("<b>Or tap a single file:</b>")
            lines.append("")
        else:
            lines.append("Tap a file to match TMDB or set a custom title:")
    elif not display_groups:
        lines.append("Tap a file to match TMDB or set a custom title:")
    for file in chunk:
        when = file.uploaded_at.strftime("%m-%d") if file.uploaded_at else "?"
        name = file.file_name if len(file.file_name) <= 34 else file.file_name[:31] + "..."
        label = f"#{file.id} {when} · {name}"
        if len(label) > 60:
            label = label[:57] + "..."
        keyboard.append(
            [InlineKeyboardButton(f"📄 {label}", callback_data=f"confirm_file:{file.id}")]
        )
    nav = []
    if n_ungrouped and page > 0:
        nav.append(InlineKeyboardButton("« Prev", callback_data=f"pending_page:{page - 1}"))
    if n_ungrouped and page + 1 < pages:
        nav.append(InlineKeyboardButton("Next »", callback_data=f"pending_page:{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


_TMDB_BULK_RETRY_KEY = "tmdb_bulk_retry"


def _tmdb_bulk_retry_cancelled(application) -> bool:
    state = application.bot_data.get(_TMDB_BULK_RETRY_KEY) or {}
    return bool(state.get("active") and state.get("cancel"))


def _tmdb_bulk_retry_progress_keyboard(return_page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⏹ Stop retry",
                    callback_data="pending_retry_stop",
                )
            ],
        ]
    )


def request_tmdb_bulk_retry_stop(application) -> bool:
    """Request cooperative cancel of the running bulk TMDB retry."""
    state = application.bot_data.get(_TMDB_BULK_RETRY_KEY)
    if state and state.get("active") and not state.get("cancel"):
        state["cancel"] = True
        return True
    return False


async def run_retry_all_pending_tmdb(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    """Admin: re-run TMDB lookup for every pending file (inline progress)."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("❌ Admin only.", show_alert=True)
        return
    if not tmdb_helper.enabled:
        if update.callback_query:
            await update.callback_query.answer("TMDB API is not configured.", show_alert=True)
        return

    app = context.application
    if (app.bot_data.get(_TMDB_BULK_RETRY_KEY) or {}).get("active"):
        if update.callback_query:
            await update.callback_query.answer(
                "TMDB retry already running.", show_alert=True
            )
        return
    if await bot_busy.reject_if_exclusive_busy(update, context):
        return

    query = update.callback_query
    return_page = int(context.user_data.get("pending_page", 0))
    wait_text = (
        "⏳ <b>Please wait</b>\n\n"
        "🔄 <b>Retrying TMDB for all pending files…</b>\n\n"
        "<i>Re-parses filenames and searches TMDB again. "
        "Strong matches are auto-confirmed.</i>"
    )
    progress_kb = _tmdb_bulk_retry_progress_keyboard(return_page)
    if edit and query:
        status = query.message
        await safe_edit_callback_message(
            query, wait_text, parse_mode=ParseMode.HTML, reply_markup=progress_kb
        )
    else:
        status = await update.message.reply_text(
            wait_text, parse_mode=ParseMode.HTML, reply_markup=progress_kb
        )

    async def _job() -> None:
        app.bot_data[_TMDB_BULK_RETRY_KEY] = {
            "active": True,
            "cancel": False,
            "return_page": return_page,
        }
        stats = {
            "total": 0,
            "scanned": 0,
            "matched": 0,
            "still_pending": 0,
            "api_errors": 0,
            "errors": 0,
        }

        async def _progress(force: bool = False) -> None:
            if not force and stats["scanned"] % 10 != 0 and stats["scanned"] != stats["total"]:
                return
            try:
                remaining = await asyncio.to_thread(db.count_pending_confirmations)
                lines = [
                    "⏳ <b>Retrying TMDB for pending files…</b>",
                    "",
                    f"Progress: <b>{stats['scanned']}</b> / <b>{stats['total']}</b>",
                    f"Auto-matched: <b>{stats['matched']}</b>",
                    f"Still pending: <b>{remaining}</b>",
                ]
                if stats["api_errors"]:
                    lines.append(
                        f"TMDB errors (likely network): <b>{stats['api_errors']}</b>"
                    )
                if stats["errors"]:
                    lines.append(f"Other errors: <b>{stats['errors']}</b>")
                await bot_edit_message(
                    context,
                    status.chat_id,
                    status.message_id,
                    "\n".join(lines),
                    progress_kb,
                )
            except Exception:
                pass

        stopped = False
        try:
            pending = await asyncio.to_thread(
                db.get_pending_confirmations, Config.PENDING_SCAN_LIMIT
            )
            stats["total"] = len(pending)
            if not pending:
                await bot_edit_message(
                    context,
                    status.chat_id,
                    status.message_id,
                    "✅ <b>No pending files</b> — nothing to retry.",
                    InlineKeyboardMarkup(
                        [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
                    ),
                )
                return

            for upload in pending:
                if _tmdb_bulk_retry_cancelled(app):
                    stopped = True
                    break
                stats["scanned"] += 1
                try:
                    meta = await asyncio.to_thread(
                        build_index_metadata,
                        upload.file_name,
                        parser=parser,
                        tmdb_helper=tmdb_helper,
                        db=db,
                    )
                    api_err = bool(tmdb_helper._last_api_error) and meta.get(
                        "needs_tmdb_pick"
                    )
                    outcome = await asyncio.to_thread(
                        db.refresh_pending_upload_from_meta, upload.id, meta
                    )
                    if outcome == "matched":
                        stats["matched"] += 1
                    elif outcome == "still_pending":
                        stats["still_pending"] += 1
                        if api_err:
                            stats["api_errors"] += 1
                except Exception:
                    stats["errors"] += 1
                    logger.exception(
                        "retry_all_pending failed for upload #%s", upload.id
                    )
                await _progress()
                await asyncio.sleep(0.05)

            await _progress(force=True)
            remaining = await asyncio.to_thread(
                db.count_pending_confirmations
            )
            if stopped:
                lines = [
                    "<b>⏹ TMDB retry stopped</b>",
                    "",
                    f"Scanned before stop: <b>{stats['scanned']}</b> / <b>{stats['total']}</b>",
                    f"Auto-matched: <b>{stats['matched']}</b>",
                    f"Still need confirmation: <b>{remaining}</b>",
                ]
                if stats["api_errors"]:
                    lines.append(
                        f"\nTMDB errors (likely network): <b>{stats['api_errors']}</b>"
                    )
            else:
                lines = [
                    "<b>✅ TMDB retry complete</b>",
                    "",
                    f"Scanned: <b>{stats['scanned']}</b>",
                    f"Auto-matched: <b>{stats['matched']}</b>",
                    f"Still need confirmation: <b>{remaining}</b>",
                ]
                if stats["api_errors"]:
                    lines.append(
                        f"\nTMDB could not be reached for <b>{stats['api_errors']}</b> "
                        "file(s) — try again later if that was a network issue."
                    )
            if stats["errors"]:
                lines.append(f"\nErrors: <b>{stats['errors']}</b> (see bot.log)")
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "« Pending list",
                            callback_data=f"pending_page:{return_page}",
                        )
                    ],
                    [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
                ]
            )
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                "\n".join(lines),
                keyboard,
            )
        except Exception as e:
            logger.exception("run_retry_all_pending_tmdb failed")
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                f"❌ Retry failed:\n\n<code>{escape(str(e))}</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
                ),
            )
        finally:
            app.bot_data.pop(_TMDB_BULK_RETRY_KEY, None)

    _fire_background_job(app, "Retry all pending TMDB", _job, exclusive=True)


async def _load_pick_metadata(file_name: str) -> dict:
    """Run TMDB search in a worker thread so the bot stays responsive."""
    return await asyncio.wait_for(
        asyncio.to_thread(
            build_pick_metadata,
            file_name,
            parser=parser,
            tmdb_helper=tmdb_helper,
            db=db,
        ),
        timeout=TMDB_PICK_TIMEOUT_S,
    )


async def _run_tmdb_pick_job(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    file_id: int,
    *,
    file_name: str,
    parsed_name: str | None,
    remap: bool = False,
    search_query_override: str | None = None,
) -> None:
    try:
        await send_tmdb_pick_ui(
            query,
            context,
            file_id,
            file_name=file_name,
            parsed_name=parsed_name,
            remap=remap,
            search_query_override=search_query_override,
        )
    except asyncio.TimeoutError:
        logger.warning("TMDB pick timed out for file %s", file_id)
        parsed = parser.parse_name(file_name)
        await reply_or_edit_query(
            query,
            context,
            "<b>⏱ TMDB search timed out</b>\n\n"
            "Use <b>✏️ Custom title</b> from Pending, or tap <b>Retry</b> on a fresh file.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
            ),
        )
    except Exception as e:
        logger.error("TMDB pick job failed for file %s: %s", file_id, e, exc_info=True)
        await reply_or_edit_query(
            query,
            context,
            f"❌ <b>Could not open TMDB picker</b>\n\n<code>{escape(str(e))}</code>",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
            ),
        )


def _tmdb_pick_extra_rows(
    *,
    gid: int | None = None,
    file_id: int | None = None,
) -> list[list[InlineKeyboardButton]]:
    """Search TMDB (manual query) + Skip for now (defer in pending queue)."""
    rows: list[list[InlineKeyboardButton]] = []
    if tmdb_helper.enabled:
        if gid is not None:
            rows.append(
                [InlineKeyboardButton("🔍 Search TMDB", callback_data=f"bts:{gid}")]
            )
        elif file_id is not None:
            rows.append(
                [InlineKeyboardButton("🔍 Search TMDB", callback_data=f"tsi:{file_id}")]
            )
    if gid is not None:
        rows.append(
            [InlineKeyboardButton("⏭ Skip for now", callback_data=f"bdf:{gid}")]
        )
    elif file_id is not None:
        rows.append(
            [InlineKeyboardButton("⏭ Skip for now", callback_data=f"dfr:{file_id}")]
        )
    return rows


async def _run_bulk_tmdb_pick_job(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    match_key: str,
    *,
    search_query_override: str | None = None,
) -> None:
    try:
        await send_bulk_tmdb_pick_ui(
            query, context, match_key, search_query_override=search_query_override
        )
    except asyncio.TimeoutError:
        await reply_or_edit_query(
            query,
            context,
            "<b>⏱ TMDB search timed out</b>\n\nTry again from Pending.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
            ),
        )
    except Exception as e:
        logger.error("Bulk TMDB pick failed for %s: %s", match_key, e, exc_info=True)
        await reply_or_edit_query(
            query,
            context,
            f"❌ <b>Batch lookup failed</b>\n\n<code>{escape(str(e))}</code>",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
            ),
        )


async def send_bulk_tmdb_pick_ui(
    query,
    context,
    match_key: str,
    *,
    search_query_override: str | None = None,
) -> None:
    """TMDB picker for a batch of pending files (same series)."""
    group = _resolve_pending_group(context, match_key)
    if not group:
        await reply_or_edit_query(
            query,
            context,
            "No pending files in this batch — open <b>/menu → Pending</b> again.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
            ),
        )
        return

    file_ids = group["file_ids"]
    show_name = group.get("show_name") or "Series"
    media_type = group.get("media_type") or "tv"
    first_name = group["files"][0]["file_name"]
    gid = group["group_id"]
    parsed_first = parser.parse_name(first_name)
    if search_query_override:
        meta = context.user_data.get(_bulk_meta_key(gid)) or {}
        meta.setdefault("parsed", parsed_first)
        meta["media_type"] = media_type
        meta["bulk_file_ids"] = file_ids
        meta["bulk_match_key"] = match_key
        meta["bulk_group_id"] = gid
        meta["search_name"] = search_query_override
        meta["local_name"] = search_query_override
        meta["manual_search_query"] = search_query_override
        if tmdb_helper.enabled:
            await _apply_tmdb_pick_page_to_meta(
                meta,
                search_query_override,
                media_type=media_type,
                parsed=meta.get("parsed"),
            )
        else:
            meta["suggestions"] = []
            meta["tmdb_unreachable"] = False
            meta["pick_has_more"] = False
        display_show = search_query_override
    else:
        try:
            meta = await _load_pick_metadata(first_name)
        except asyncio.TimeoutError:
            meta = build_pick_metadata(
                first_name, parser=parser, tmdb_helper=tmdb_helper, db=db
            )
        meta["bulk_file_ids"] = file_ids
        meta["bulk_match_key"] = match_key
        meta["bulk_group_id"] = gid
        meta["media_type"] = media_type
        parsed = meta.get("parsed") or {}
        search_show = parsed.get("show_name") or show_name
        search_show, _emb = split_title_year(search_show)
        meta["search_name"] = search_show or show_name
        meta["local_name"] = search_show or show_name
        display_show = search_show or show_name
        if parsed.get("year"):
            display_show = f"{display_show} ({parsed['year']})"
        if tmdb_helper.enabled and not search_query_override:
            q = meta.get("search_name") or show_name
            if q:
                await _apply_tmdb_pick_page_to_meta(
                    meta,
                    q,
                    media_type=media_type,
                    parsed=meta.get("parsed"),
                )
    show_name = display_show

    suggestions = list(meta.get("suggestions") or [])
    context.user_data[_tmdb_sug_key_bulk(gid)] = suggestions
    context.user_data[_bulk_meta_key(gid)] = meta

    n = len(file_ids)
    preview = _format_batch_files_preview(group)
    year_hint = _parsed_release_year(meta.get("parsed"))

    if search_query_override:
        lines = [
            "<b>🔍 TMDB search results</b>",
            f"Query: <code>{escape(search_query_override)}</code>"
            + (f" · <b>{year_hint}</b>" if year_hint else ""),
            f"Applies to <b>{n}</b> file(s) in this batch.",
            "",
        ]
        if suggestions:
            lines.append(
                f"<b>{len(suggestions)} match(es)</b> below (TV + movies) — "
                "scroll and tap <b>Select this title</b>."
            )
            if meta.get("pick_has_more"):
                lines.append("Tap <b>Load more results</b> for the next page.")
        elif meta.get("tmdb_unreachable"):
            lines.append(
                "Could not reach TMDB (network). Wait a moment, then tap "
                "<b>Retry TMDB search</b>."
            )
        else:
            lines.append(
                "No TMDB matches for that spelling. Try again — e.g. "
                "<code>Tron Ares</code> instead of <code>tron area</code>."
            )
        lines.extend(["", "<i>Files:</i>", preview, ""])
    else:
        lines = [
            f"<b>📦 Batch map — {escape(show_name)}</b>",
            f"<b>{n}</b> pending file(s) → one TMDB series/movie.",
            "",
            "<i>Episode numbers (E01, E07, …) stay per file.</i>",
            "",
            "<b>Files in batch:</b>",
            preview,
            "",
        ]
        if not tmdb_helper.enabled:
            lines.append("TMDB is not configured.")
        elif suggestions:
            lines.append(
                f"<b>{len(suggestions)} TMDB match(es)</b> (TV + movies) — scroll; each has poster, plot, and "
                "<b>Select this title</b>."
            )
            if meta.get("pick_has_more"):
                lines.append("Tap <b>Load more results</b> for the next page.")
        elif meta.get("tmdb_unreachable"):
            lines.append("Could not reach TMDB (network).")
        else:
            lines.append(f"No TMDB matches for <b>{escape(show_name)}</b>.")

    keyboard = []
    if media_type == "tv" and show_name and not search_query_override:
        btn = show_name if len(show_name) <= 30 else show_name[:27] + "..."
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"✅ Use parsed: {btn}",
                    callback_data=f"bpp:{gid}",
                )
            ]
        )
    if tmdb_helper.enabled:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔄 Retry TMDB search",
                    callback_data=f"brt:{gid}",
                )
            ]
        )
    keyboard.extend(_tmdb_pick_extra_rows(gid=gid))
    load_more = _tmdb_load_more_row(meta, gid=gid)
    if load_more:
        keyboard.append(load_more)
    keyboard.append(
        [
            InlineKeyboardButton(
                "✏️ Custom title (all)", callback_data=f"bpc:{gid}"
            ),
            InlineKeyboardButton(
                "📚 Custom, no card", callback_data=f"bpn:{gid}"
            ),
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                "🚫 Skip watch catalog (all)",
                callback_data=f"scb:{gid}",
            )
        ]
    )
    keyboard.append([InlineKeyboardButton("« Pending", callback_data="pending_menu")])
    await reply_or_edit_query(query, context, "\n".join(lines), InlineKeyboardMarkup(keyboard))
    if suggestions:
        await _send_tmdb_suggestion_cards(
            query,
            context,
            suggestions,
            lambda i: f"tpb:{gid}:{i}",
            match_key=str(gid),
        )


async def send_tmdb_pick_ui(
    query,
    context,
    file_id: int,
    *,
    file_name: str,
    parsed_name: str | None = None,
    remap: bool = False,
    search_query_override: str | None = None,
):
    """Show TMDB suggestions (or parsed/custom) for a pending or indexed file."""
    if search_query_override:
        parsed = parser.parse_name(file_name)
        media_type = parsed.get("media_type") or "movie"
        meta = context.user_data.get(f"tmdb_meta_{file_id}") or {
            "parsed": parsed,
            "media_type": media_type,
            "show_group_key": show_group_key(parsed, file_name),
        }
        meta["search_name"] = search_query_override
        meta["local_name"] = search_query_override
        meta["manual_search_query"] = search_query_override
        if tmdb_helper.enabled:
            await _apply_tmdb_pick_page_to_meta(
                meta,
                search_query_override,
                media_type=media_type,
                parsed=parsed,
            )
        else:
            meta["suggestions"] = []
            meta["tmdb_unreachable"] = False
            meta["pick_has_more"] = False
    else:
        try:
            meta = await _load_pick_metadata(file_name)
        except asyncio.TimeoutError:
            parsed = parser.parse_name(file_name)
            meta = {
                "parsed": parsed,
                "media_type": parsed.get("media_type") or "movie",
                "search_name": parsed.get("show_name") or parsed.get("name"),
                "local_name": parsed.get("show_name") or parsed.get("name"),
                "show_group_key": show_group_key(parsed, file_name),
                "suggestions": [],
            }
        if tmdb_helper.enabled:
            q = meta.get("search_name") or meta.get("local_name")
            parsed0 = meta.get("parsed") or {}
            mt0 = meta.get("media_type") or "movie"
            if q:
                await _apply_tmdb_pick_page_to_meta(
                    meta, q, media_type=mt0, parsed=parsed0
                )
    suggestions = list(meta.get("suggestions") or [])
    context.user_data[_tmdb_sug_key(file_id)] = suggestions
    context.user_data[f"tmdb_meta_{file_id}"] = meta

    parsed = meta.get("parsed") or {}
    media_type = meta.get("media_type") or "movie"
    show_name = meta.get("local_name") or parsed.get("show_name") or parsed.get("name")
    search_label = meta.get("search_name") or parsed_name or show_name or "N/A"
    yr = parsed.get("year")
    if yr and not search_query_override:
        search_label = f"{search_label} ({yr})"
    season = parsed.get("season")
    episode = parsed.get("episode")
    episode_title = parsed.get("episode_title")
    safe_file = escape(_truncate_for_telegram(file_name, 200))
    year_hint = _parsed_release_year(parsed)

    if search_query_override:
        lines = [
            "<b>🔍 TMDB search results</b>",
            f"Query: <code>{escape(search_query_override)}</code>"
            + (f" · <b>{year_hint}</b>" if year_hint else ""),
            f"File: <code>{safe_file}</code>",
            "",
        ]
        if suggestions:
            lines.append(
                f"<b>{len(suggestions)} match(es)</b> below (TV + movies) — "
                "tap <b>Select this title</b>."
            )
            if meta.get("pick_has_more"):
                lines.append("Tap <b>Load more results</b> for the next page.")
        elif meta.get("tmdb_unreachable"):
            lines.append(
                "Could not reach TMDB (network). Wait, then tap <b>Retry TMDB search</b>."
            )
        else:
            lines.append(
                "No matches. Try a closer spelling (e.g. <code>Tron Ares</code>)."
            )
    else:
        header = "✏️ Remap TMDB title" if remap else "🎬 Match TMDB title"
        lines = [
            f"<b>{header}</b>",
            "",
            f"File: <code>{safe_file}</code>",
            "",
        ]
        if media_type == "tv" and show_name:
            lines.append(f"📺 <b>Show:</b> {escape(show_name)}")
            if season is not None:
                ep_bits = [f"<b>Season {season}</b>"]
                if episode is not None:
                    ep_bits.append(f"Episode {episode}")
                lines.append(f"📅 {' · '.join(ep_bits)}")
            if episode_title:
                lines.append(f"📝 {escape(episode_title)}")
            lines.append("")
        else:
            lines.append(f"<b>Title:</b> {escape(search_label)}\n")

        if not tmdb_helper.enabled:
            lines.append("TMDB is not configured — use the buttons below.")
        elif suggestions:
            lines.append(
                f"<b>{len(suggestions)} TMDB match(es)</b> below (TV + movies) — poster, plot, "
                "<b>Select this title</b>."
            )
            if meta.get("pick_has_more"):
                lines.append("Tap <b>Load more results</b> for the next page.")
        elif meta.get("tmdb_unreachable"):
            lines.append(
                "Could not reach TMDB (network) — tap <b>Retry search</b> or use <b>Custom title</b>."
            )
        else:
            lines.append(
                f"No TMDB matches for <b>{escape(search_label if media_type != 'tv' else (show_name or 'N/A'))}</b> — "
                "tap <b>Retry</b>, <b>Search TMDB</b>, or <b>Custom title</b>."
            )

    keyboard = []
    if media_type == "tv" and show_name and not search_query_override:
        season_label = f" (Season {season})" if season is not None else ""
        btn_show = show_name if len(show_name) <= 28 else show_name[:25] + "..."
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"✅ {btn_show}{season_label}",
                    callback_data=f"tmdb_detected:{file_id}",
                )
            ]
        )

    if tmdb_helper.enabled:
        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔄 Retry TMDB search",
                    callback_data=f"tmdb_retry:{file_id}",
                )
            ]
        )

    keyboard.extend(_tmdb_pick_extra_rows(file_id=file_id))
    load_more = _tmdb_load_more_row(meta, file_id=file_id)
    if load_more:
        keyboard.append(load_more)

    keyboard.append(
        [
            InlineKeyboardButton(
                "✏️ Custom title", callback_data=f"confirm_custom:{file_id}"
            ),
            InlineKeyboardButton(
                "📚 Custom (no card)",
                callback_data=f"confirm_custom_nc:{file_id}",
            ),
        ]
    )
    keyboard.append(
        [
            InlineKeyboardButton(
                "🚫 Skip watch catalog",
                callback_data=f"skip_catalog:{file_id}",
            )
        ]
    )
    back_cb = context.user_data.get("remap_back_cb", "pending_menu")
    back_label = context.user_data.get("remap_back_label", "« Pending")
    keyboard.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
    text = "\n".join(lines)
    markup = InlineKeyboardMarkup(keyboard)
    await reply_or_edit_query(query, context, text, markup)
    if suggestions:
        await _send_tmdb_suggestion_cards(
            query,
            context,
            suggestions,
            lambda i: f"tmdb_pick:{file_id}:{i}",
            file_id=file_id,
        )


async def send_remap_files_menu(
    query,
    context,
    movie_name: str,
    *,
    channel_ids=None,
    back_cb: str,
    back_label: str,
) -> None:
    """List indexed files under a title so admin can remap TMDB per file."""
    if channel_ids:
        stats = db.get_upload_stats_in_channels(movie_name, channel_ids)
    else:
        stats = db.get_upload_stats(movie_name)
    uploads: list[dict] = []
    for channel_data in stats.get("channels", {}).values():
        uploads.extend(channel_data.get("uploads") or [])
    uploads.sort(
        key=lambda x: x.get("uploaded_at") or datetime.min.replace(tzinfo=None),
        reverse=True,
    )
    lines = [
        "<b>✏️ Change TMDB mapping</b>",
        f"Library title: <b>{escape(movie_name)}</b>",
        "",
        "Pick a file to search TMDB again (fixes wrong movie with same name):",
    ]
    keyboard = []
    for u in uploads[:12]:
        fn = u.get("file_name") or "?"
        label = fn if len(fn) <= 52 else fn[:49] + "..."
        keyboard.append(
            [InlineKeyboardButton(f"📄 {label}", callback_data=f"remap_tmdb:{u['id']}")]
        )
    if not uploads:
        lines.append("\n<i>No files found for this title.</i>")
    keyboard.append([InlineKeyboardButton(back_label, callback_data=back_cb)])
    await reply_or_edit_query(query, context, "\n".join(lines), InlineKeyboardMarkup(keyboard))


def _meta_for_bulk_file(file_name: str, selection: dict) -> dict:
    """Lightweight per-file meta for batch apply (no TMDB search per file)."""
    parsed = parser.parse_name(file_name)
    media_type = selection.get("media_type") or parsed.get("media_type") or "tv"
    show = parsed.get("show_name") or parsed.get("name") or selection.get("title")
    return {
        "parsed": parsed,
        "media_type": media_type,
        "search_name": show,
        "local_name": show,
        "show_group_key": show_group_key(parsed, file_name),
    }


def _apply_tmdb_selection(
    file_id: int,
    selection: dict,
    meta: dict,
    *,
    details: dict | None = None,
    save_hint: bool = True,
) -> FileUpload | None:
    """Persist TMDB pick (or parsed-only) for a file."""
    parsed = meta.get("parsed") or {}
    media_type = selection.get("media_type") or meta.get("media_type") or "movie"
    tmdb_id = selection.get("tmdb_id")
    tmdb_title = selection.get("title")
    if details is None:
        details = {}
        if tmdb_id and tmdb_helper.enabled:
            if media_type in ("tv", "series"):
                details = tmdb_helper.fetch_tv_details(tmdb_id) or {}
            else:
                details = tmdb_helper.fetch_movie_details(tmdb_id) or {}
    tmdb_title = tmdb_title or details.get("tmdb_title")

    local_name = meta.get("local_name") or meta.get("search_name")
    if tmdb_title:
        local_name = tmdb_title
    if media_type == "tv":
        display = episode_display_name(
            tmdb_title or local_name or "",
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("episode_title"),
        )
    else:
        display = tmdb_title or local_name or meta.get("parsed_name")

    upload = db.apply_tmdb_pick(
        file_id,
        tmdb_id=tmdb_id,
        tmdb_title=tmdb_title,
        media_type="tv" if media_type in ("tv", "series") else "movie",
        local_name=local_name,
        parsed_name=display,
        season_number=parsed.get("season"),
        episode_number=parsed.get("episode"),
        episode_title=parsed.get("episode_title"),
        release_year=details.get("release_year"),
        poster_path=details.get("poster_path"),
        overview=details.get("overview"),
        vote_average=details.get("vote_average"),
        genres=details.get("genres"),
        library_visible=bool(tmdb_id),
        catalog_excluded=False,
    )
    if save_hint and upload and tmdb_id:
        match_key = meta.get("show_group_key")
        if match_key:
            db.save_title_hint(
                match_key,
                tmdb_id=tmdb_id,
                tmdb_title=tmdb_title,
                media_type="tv" if media_type in ("tv", "series") else "movie",
            )
    return upload


def schedule_watch_publish(
    context: ContextTypes.DEFAULT_TYPE,
    upload_id: int | None,
    *,
    library_visible: bool,
) -> None:
    if not upload_id or not library_visible:
        return
    upload = db.get_file_upload(upload_id)
    if not upload or not db.is_catalog_publishable(upload.content_title_id):
        return

    async def _job() -> None:
        await maybe_auto_publish_watch(
            context.bot,
            db,
            upload_id,
            library_visible=True,
            bot_username=context.bot.username,
        )

    _fire_background_job(
        context.application, "Auto-publish watch card", _job, exclusive=False
    )


def _apply_tmdb_bulk(file_ids: list[int], selection: dict) -> int:
    """Apply the same TMDB series/movie to many pending files (per-file episode metadata)."""
    media_type = selection.get("media_type") or "tv"
    tmdb_id = selection.get("tmdb_id")
    details: dict = {}
    if tmdb_id and tmdb_helper.enabled:
        if media_type in ("tv", "series"):
            details = tmdb_helper.fetch_tv_details(tmdb_id) or {}
        else:
            details = tmdb_helper.fetch_movie_details(tmdb_id) or {}

    applied = 0
    hint_key: str | None = None
    for fid in file_ids:
        upload = db.get_file_upload(fid)
        if not upload:
            continue
        meta = _meta_for_bulk_file(upload.file_name, selection)
        if not hint_key:
            hint_key = meta.get("show_group_key")
        if _apply_tmdb_selection(
            fid, selection, meta, details=details, save_hint=False
        ):
            applied += 1

    if applied and tmdb_id and hint_key:
        db.save_title_hint(
            hint_key,
            tmdb_id=tmdb_id,
            tmdb_title=selection.get("title") or details.get("tmdb_title"),
            media_type="tv" if media_type in ("tv", "series") else "movie",
        )
    return applied


def _apply_parsed_bulk(file_ids: list[int], show_name: str, *, media_type: str = "tv") -> int:
    """Confirm batch using parsed/local show name (no TMDB link)."""
    applied = 0
    for fid in file_ids:
        upload = db.get_file_upload(fid)
        if not upload:
            continue
        parsed = parser.parse_name(upload.file_name)
        if media_type == "tv":
            display = episode_display_name(
                show_name,
                parsed.get("season"),
                parsed.get("episode"),
                parsed.get("episode_title"),
            )
        else:
            display = show_name
        if db.apply_tmdb_pick(
            fid,
            local_name=show_name,
            parsed_name=display,
            media_type=media_type,
            season_number=parsed.get("season"),
            episode_number=parsed.get("episode"),
            episode_title=parsed.get("episode_title"),
            library_visible=False,
            catalog_excluded=True,
        ):
            applied += 1
    return applied


def _apply_custom_bulk(
    file_ids: list[int],
    title: str,
    *,
    media_type: str = "tv",
    catalog_excluded: bool = False,
) -> int:
    """Apply a custom show/movie title to all files in a batch."""
    applied = 0
    for fid in file_ids:
        upload = db.get_file_upload(fid)
        if not upload:
            continue
        parsed = parser.parse_name(upload.file_name)
        if media_type == "tv":
            display = episode_display_name(
                title,
                parsed.get("season"),
                parsed.get("episode"),
                parsed.get("episode_title"),
            )
        else:
            display = title
        if db.apply_tmdb_pick(
            fid,
            local_name=title,
            parsed_name=display,
            media_type=media_type,
            season_number=parsed.get("season"),
            episode_number=parsed.get("episode"),
            episode_title=parsed.get("episode_title"),
            library_visible=True,
            catalog_excluded=catalog_excluded,
        ):
            applied += 1
    return applied


def _apply_skip_catalog_file(file_id: int, *, library_only: bool):
    """Confirm without TMDB; never publish a watch-channel poster card."""
    upload = db.get_file_upload(file_id)
    if not upload:
        return None
    parsed = parser.parse_name(upload.file_name)
    mt = (parsed.get("media_type") or "movie").lower()
    if mt in ("series", "show"):
        mt = "tv"
    local = (
        parsed.get("show_name")
        or parsed.get("name")
        or upload.parsed_name
        or upload.file_name
    )
    if mt == "tv":
        display = episode_display_name(
            local,
            parsed.get("season"),
            parsed.get("episode"),
            parsed.get("episode_title"),
        )
    else:
        display = local
    return db.apply_tmdb_pick(
        file_id,
        local_name=str(local)[:200],
        parsed_name=display,
        media_type=mt,
        season_number=parsed.get("season"),
        episode_number=parsed.get("episode"),
        episode_title=parsed.get("episode_title"),
        library_visible=library_only,
        catalog_excluded=True,
        indexed_only=True,
    )


def _apply_skip_catalog_bulk(file_ids: list[int], *, library_only: bool) -> int:
    n = 0
    for fid in file_ids:
        if _apply_skip_catalog_file(fid, library_only=library_only):
            n += 1
    return n


async def _reply_or_edit(target, text, reply_markup=None, *, edit=False):
    """Send or edit a message from a command update or callback query."""
    if edit and hasattr(target, "edit_message_text"):
        if not await safe_edit_message(target, text, reply_markup=reply_markup):
            return
    elif hasattr(target, "message") and target.message:
        await target.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await target.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def send_unavailable_posts_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False
):
    """Admin: indexed posts confirmed removed from channels."""
    query = update.callback_query
    target = query if edit and query else update
    rows = db.get_unavailable_uploads(limit=30)
    lines = [
        "<b>⚠️ Unavailable posts</b>",
        "",
        "These files were indexed but the channel message is gone.",
        "They are hidden from <b>Watch</b> for users.",
        "",
    ]
    keyboard = []
    if not rows:
        lines.append("<i>None marked unavailable yet. Run verify sweep below.</i>")
    else:
        for u in rows[:20]:
            title = ""
            if u.content_title and u.content_title.tmdb_title:
                title = u.content_title.tmdb_title
            elif u.confirmed_name:
                title = u.confirmed_name
            ep = ""
            if u.season_number is not None or u.episode_number is not None:
                ep = f" · {episode_label(u.season_number, u.episode_number)}"
            ch = upload_channel_label(u)
            fn = u.file_name if len(u.file_name) <= 28 else u.file_name[:25] + "…"
            lines.append(f"• <code>{escape(fn)}</code>{ep}\n  {escape(title or '?')} · {escape(ch)}")
        if len(rows) > 20:
            lines.append(f"\n<i>…and {len(rows) - 20} more</i>")
    keyboard.append(
        [InlineKeyboardButton("🔍 Verify channel posts", callback_data="verify_posts_run")]
    )
    keyboard.append([InlineKeyboardButton("« Channels", callback_data="channels_menu")])
    keyboard.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def run_verify_posts_sweep(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False
):
    """Admin: periodic Telethon sweep for deleted channel posts."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        if update.callback_query:
            await update.callback_query.answer("❌ Admin only.", show_alert=True)
        return

    app = context.application
    if await bot_busy.reject_if_exclusive_busy(update, context):
        return

    query = update.callback_query
    if edit and query:
        status = query.message
        await safe_edit_callback_message(
            query,
            "⏳ <b>Please wait</b>\n\n🔍 <b>Verifying channel posts…</b>\n\n"
            "<i>Uses your Telethon session. This may take several minutes.</i>",
            parse_mode=ParseMode.HTML,
        )
    else:
        status = await update.message.reply_text(
            "⏳ <b>Please wait</b>\n\n🔍 <b>Verifying channel posts…</b>\n\n"
            "<i>Uses your Telethon session (same as forward ingest).</i>",
            parse_mode=ParseMode.HTML,
        )

    async def _job() -> None:
        try:
            if not telethon_configured() or not telethon_session_path().exists():
                raise RuntimeError(
                    "Set API_ID/API_HASH in .env and run: python telethon_login.py"
                )

            async def progress(done: int, total: int) -> None:
                try:
                    await bot_edit_message(
                        context,
                        status.chat_id,
                        status.message_id,
                        "⏳ <b>Verifying channel posts…</b>\n\n"
                        f"Progress: <b>{done}</b> / <b>{total}</b>",
                    )
                except Exception:
                    pass

            checked, available, unavailable, skipped = await run_verify_sweep(
                db, limit=500, stale_hours=24, force=False, progress_callback=progress
            )
            n_bad = db.count_unavailable_uploads()
            lines = [
                "<b>✅ Verification complete</b>",
                "",
                f"Checked: <b>{checked}</b>",
                f"Still in channel: <b>{available}</b>",
                f"Removed: <b>{unavailable}</b>",
                f"Could not check: <b>{skipped}</b>",
                "",
                f"Total unavailable in index: <b>{n_bad}</b>",
            ]
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⚠️ View unavailable",
                            callback_data="unavailable_posts_menu",
                        )
                    ],
                    [InlineKeyboardButton("« Channels", callback_data="channels_menu")],
                ]
            )
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                "\n".join(lines),
                keyboard,
            )
        except Exception as e:
            logger.exception("verify_posts_run failed")
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                f"❌ Verification failed:\n\n<code>{escape(str(e))}</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Channels", callback_data="channels_menu")]]
                ),
            )
    _fire_background_job(app, "Verifying channel posts", _job, exclusive=True)


async def send_channels_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int = 0,
    query: str | None = None,
    edit: bool = False,
) -> None:
    """Searchable paginated channel list (connected channels)."""
    from channel_picker import build_channel_picker

    target = update.callback_query if edit and update.callback_query else update
    channels = sorted(
        db.get_all_channels_registered(active_only=False),
        key=lambda c: (not c.is_active, (c.channel_title or "").lower()),
    )
    index_stats = db.get_channel_index_stats()

    def _channel_label(ch) -> str:
        is_ingest = getattr(ch, "is_ingest_channel", False)
        count = db.get_channel_upload_count(ch.channel_id, is_ingest=is_ingest)
        st = index_stats.get(str(ch.channel_id), {})
        prefix = "⏸ " if not ch.is_active else ""
        return prefix + channel_list_label_with_status(
            ch,
            live_count=st.get("live", 0),
            backfill_count=st.get("backfill", 0),
            file_count=count,
            label_fn=channel_button_label,
            max_len=56,
        )

    title = (
        "<b>🔍 Browse connected channels</b>\n\n"
        "<i>📥 ingest · 🤖 live · 📡 member watch · 📜 historical · 👤📜 user-only · ⏳ not ingested</i>"
    )
    text, markup = build_channel_picker(
        channels,
        page=page,
        query=query,
        callback_prefix="chpick",
        pick_prefix="channel_info",
        label_fn=_channel_label,
        back_callback="channels_menu",
        back_label="« Connected channels",
        search_callback="chpick_search",
        title_line=title,
    )
    await _reply_or_edit(target, text, markup, edit=edit)


async def send_channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Connected channels hub with selectable channel buttons (admin)."""
    query = update.callback_query
    target = query if edit and query else update
    if update.effective_user and not is_admin(update.effective_user.id):
        await watch_features.send_user_main_menu(update, context, edit=edit)
        return

    channels = db.get_all_channels_registered(active_only=False)
    active = [c for c in channels if c.is_active]
    inactive = [c for c in channels if not c.is_active]

    ingest = db.get_ingest_channel()
    lines = [
        "<b>📺 Connected channels</b>",
        "",
        f"Active: <b>{len(active)}</b> · Inactive: <b>{len(inactive)}</b>",
    ]
    if ingest:
        lines.append(
            f"\n📥 <b>Ingest sink:</b> {escape(channel_button_label(ingest))} "
            f"(<i>change in Library setup</i>)"
        )
    else:
        lines.append("\n📥 <b>Ingest sink:</b> not set — <b>⚙️ Library setup</b>")
    lines.extend(
        [
            "",
            "<b>Icons</b>",
            "📥 ingest sink · 🤖 bot live posts · 📜 historical import",
            "👤📜 historical only (your Telethon account, bot not in source)",
            "⏳ registered, not historically ingested yet",
            "",
            "Tap a channel for details and actions.",
        ]
    )
    if not channels:
        lines.extend(
            [
                "",
                "<b>No channels in the database yet.</b>",
                "",
                "The Bot API cannot list every channel the bot is in.",
                "Tap <b>Discover bot channels</b> to scan (uses your Telethon login).",
                "Or: post once in a channel, register @username, or forward a post here.",
            ]
        )

    index_stats = db.get_channel_index_stats()
    keyboard = []
    for channel in active:
        is_ingest = getattr(channel, "is_ingest_channel", False)
        count = db.get_channel_upload_count(
            channel.channel_id, is_ingest=is_ingest
        )
        st = index_stats.get(str(channel.channel_id), {})
        label = channel_list_label_with_status(
            channel,
            live_count=st.get("live", 0),
            backfill_count=st.get("backfill", 0),
            file_count=count,
            label_fn=channel_button_label,
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"channel_info:{channel.channel_id}",
                )
            ]
        )
    if inactive:
        keyboard.append(
            [InlineKeyboardButton("── Inactive (tap to restore) ──", callback_data="noop")]
        )
        for channel in inactive[:15]:
            count = db.get_channel_upload_count(channel.channel_id)
            st = index_stats.get(str(channel.channel_id), {})
            label = channel_list_label_with_status(
                channel,
                live_count=st.get("live", 0),
                backfill_count=st.get("backfill", 0),
                file_count=count,
                label_fn=channel_button_label,
            )
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"⏸ {label}",
                        callback_data=f"channel_info:{channel.channel_id}",
                    )
                ]
            )

    keyboard.append(
        [InlineKeyboardButton("🔍 Search / browse channels", callback_data="chpick_search")]
    )
    keyboard.append(
        [
            InlineKeyboardButton("📂 Channel index", callback_data="channel_index_menu"),
            InlineKeyboardButton("📋 New list", callback_data="create_list_start"),
        ]
    )
    if update.effective_user and is_admin(update.effective_user.id):
        keyboard.append(
            [
                InlineKeyboardButton("➕ Register channel", callback_data="add_channel_menu"),
                InlineKeyboardButton("➖ Remove channel", callback_data="remove_channel_menu"),
            ]
        )
        keyboard.append([InlineKeyboardButton("📚 Historical ingest setup", callback_data="backfill_menu")])
        if db.get_ingest_channel():
            keyboard.append(
                [InlineKeyboardButton("▶️ Start historical ingestion", callback_data="backfill_start_menu")]
            )
        keyboard.append(
            [InlineKeyboardButton("🔍 Discover bot channels", callback_data="discover_channels_run")]
        )
        n_unavail = db.count_unavailable_uploads()
        unavail_label = f"⚠️ Unavailable posts ({n_unavail})" if n_unavail else "⚠️ Unavailable posts"
        keyboard.append(
            [
                InlineKeyboardButton("🔍 Verify channel posts", callback_data="verify_posts_run"),
                InlineKeyboardButton(unavail_label, callback_data="unavailable_posts_menu"),
            ]
        )
    keyboard.append([InlineKeyboardButton("🔄 Refresh", callback_data="channels_menu")])

    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_add_channel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Pick inactive channel to restore, or register by @username / forward."""
    query = update.callback_query
    target = query if edit and query else update

    inactive = [c for c in db.get_all_channels_registered(active_only=False) if not c.is_active]
    lines = [
        "<b>➕ Register / restore channel</b>",
        "",
        "• Tap an <b>inactive</b> channel to monitor it again.",
        "• Or register by <b>@username</b> (bot must already be admin).",
        "• Or <b>forward any post</b> from the channel to this bot.",
    ]
    keyboard = []
    for channel in inactive[:20]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"⏸ {channel_button_label(channel)}",
                    callback_data=f"add_channel_activate:{channel.channel_id}",
                )
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("✏️ Enter @username", callback_data="add_channel_username_prompt")]
    )
    keyboard.append([InlineKeyboardButton("« Back to channels", callback_data="channels_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_remove_channel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Pick an active channel to stop monitoring."""
    query = update.callback_query
    target = query if edit and query else update

    active = db.get_all_channels()
    if not active:
        await _reply_or_edit(
            target,
            "📭 No active channels to remove.",
            InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="channels_menu")]]),
            edit=edit,
        )
        return

    lines = ["<b>➖ Remove channel</b>", "", "Tap a channel to stop monitoring (data stays in the library)."]
    keyboard = []
    for channel in active:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📺 {channel_button_label(channel)}",
                    callback_data=f"remove_channel_do:{channel.channel_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Back to channels", callback_data="channels_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def start_create_list_ui(update: Update, context: ContextTypes.DEFAULT_TYPE, list_name: str):
    """Channel picker for a new custom list (toggle buttons)."""
    existing = db.get_custom_list(list_name)
    if existing:
        await update.message.reply_text(
            f"❌ List '{list_name}' already exists. Use a different name.",
            parse_mode=ParseMode.HTML,
        )
        return

    channels = db.get_all_channels()
    if not channels:
        await update.message.reply_text(
            "❌ No channels available yet.\n\n"
            "Add the bot as admin to channels first — use /channels to check.",
            parse_mode=ParseMode.HTML,
        )
        return

    key = f"selected_channels_{list_name}"
    context.user_data[key] = []

    message = (
        f"<b>📋 Create list: {escape(list_name)}</b>\n\n"
        "Tap channels to include (toggle), then press <b>Create list</b>."
    )
    keyboard = []
    for channel in channels:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📺 {channel_button_label(channel)}",
                    callback_data=f"toggle_list_channel:{channel.channel_id}:{list_name}",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton("✅ Create list", callback_data=f"create_list_final:{list_name}"),
            InlineKeyboardButton("❌ Cancel", callback_data="channels_menu"),
        ]
    )
    await update.message.reply_text(
        message,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=ParseMode.HTML,
    )


def build_tracking_entries(
    filter_kind: str = "all", completion: str = "all"
) -> list[dict]:
    """Build admin tracking list: TV shows, TMDB collections, multipart movies."""
    from portal.tracking_service import list_tracking_entries

    items, _, _ = list_tracking_entries(
        filter_kind,
        completion=completion,
        page=1,
        page_size=500,
        fetch_tmdb=True,
        fetch_page_tmdb=True,
    )
    for entry in items:
        kind = entry.get("kind")
        if kind == "tv" and entry.get("content_title_id"):
            entry["callback"] = f"tracking_tv:{entry['content_title_id']}"
        elif kind == "multipart" and entry.get("content_title_id"):
            entry["callback"] = f"tracking_mp:{entry['content_title_id']}"
        elif kind == "collection" and entry.get("collection_id"):
            entry["callback"] = f"tracking_col:{entry['collection_id']}"
    return items


async def send_tracking_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int = 0,
    filter_kind: str = "all",
    completion: str = "all",
    edit=False,
):
    """Admin: TV / franchise upload progress vs TMDB."""
    query = update.callback_query
    target = query if edit and query else update
    entries = build_tracking_entries(filter_kind, completion)
    context.user_data["tracking_entries"] = entries
    context.user_data["tracking_filter"] = filter_kind
    context.user_data["tracking_completion"] = completion

    lines = [
        "<b>📊 Tracking</b>",
        "",
        "See what is indexed vs TMDB totals — TV seasons/episodes and movie franchises.",
        "",
    ]
    if not tmdb_helper.enabled:
        lines.append("<i>TMDB not configured — totals show indexed counts only.</i>\n")
    if not entries:
        lines.append(
            "<i>No trackable titles yet. Index TV shows or franchise movies with TMDB links.</i>"
        )
    else:
        tv_n = sum(1 for e in entries if e["kind"] == "tv")
        fr_n = len(entries) - tv_n
        lines.append(f"<b>{len(entries)}</b> title(s) · 📺 {tv_n} · 🎬 {fr_n}")
        lines.append("\nTap a row for season/episode or franchise breakdown.")

    keyboard = build_tracking_list_keyboard(
        entries,
        page=page,
        page_size=12,
        filter_kind=filter_kind,
        completion=completion,
    )
    await _reply_or_edit(target, "\n".join(lines), keyboard, edit=edit)


async def send_tracking_tv_detail(
    query, context: ContextTypes.DEFAULT_TYPE, content_title_id: int
) -> None:
    ct = db.get_content_title(content_title_id)
    title = db.display_title_for_content(ct, "?")
    stats = db.get_indexed_episode_stats(content_title_id)
    tmdb_data = None
    if ct and ct.tmdb_id and tmdb_helper.enabled:
        tmdb_data = tmdb_helper.fetch_tv_tracking(int(ct.tmdb_id))
    text = format_tv_tracking_detail(title, stats, tmdb_data)
    filt = context.user_data.get("tracking_filter", "all")
    comp = context.user_data.get("tracking_completion", "all")
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "« Tracking", callback_data=f"tracking_page:0:{filt}:{comp}"
                )
            ],
            [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
        ]
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def send_tracking_collection_detail(
    query, context: ContextTypes.DEFAULT_TYPE, collection_id: int
) -> None:
    coll = tmdb_helper.fetch_collection_by_id(collection_id)
    if not coll:
        await query.answer("Collection not found on TMDB", show_alert=True)
        return
    indexed_ids = db.get_indexed_movie_tmdb_ids()
    text = format_collection_tracking_detail(
        coll["name"], coll["parts"], indexed_ids
    )
    filt = context.user_data.get("tracking_filter", "all")
    comp = context.user_data.get("tracking_completion", "all")
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "« Tracking", callback_data=f"tracking_page:0:{filt}:{comp}"
                )
            ],
            [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
        ]
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def send_tracking_multipart_detail(
    query, context: ContextTypes.DEFAULT_TYPE, content_title_id: int
) -> None:
    entry = next(
        (
            e
            for e in context.user_data.get("tracking_entries", [])
            if e.get("kind") == "multipart"
            and e.get("content_title_id") == content_title_id
        ),
        None,
    )
    if not entry:
        for row in db.get_tracking_multipart_movies(limit=200):
            if row["content_title_id"] == content_title_id:
                entry = {
                    "title": row["title"],
                    "part_set": row["indexed_parts"],
                    "total_parts": row.get("total_parts"),
                }
                break
    if not entry:
        await query.answer("Title not found", show_alert=True)
        return
    text = format_multipart_tracking_detail(
        entry["title"],
        entry.get("part_set") or set(),
        entry.get("total_parts"),
    )
    filt = context.user_data.get("tracking_filter", "all")
    comp = context.user_data.get("tracking_completion", "all")
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "« Tracking", callback_data=f"tracking_page:0:{filt}:{comp}"
                )
            ],
            [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
        ]
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Route to user or admin home menu (always shows buttons, even during heavy jobs)."""
    prefix = ""
    user = update.effective_user
    if (
        user
        and is_admin(user.id)
        and bot_busy.is_busy(context.application)
    ):
        prefix = bot_busy.busy_banner_html(context.application)
    if user and is_admin(user.id):
        await send_admin_main_menu(update, context, edit=edit, prefix=prefix)
    else:
        await watch_features.send_user_main_menu(update, context, edit=edit, prefix=prefix)


async def send_admin_main_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit=False,
    prefix: str = "",
):
    """Indexer admin home — channel management, pending review, publish."""
    query = update.callback_query
    target = query if edit and query else update
    summary = db.get_index_summary()
    tmdb_line = "✅ enabled" if tmdb_helper.enabled else "❌ not configured"
    text = (
        (prefix + "\n\n" if prefix else "")
        + "<b>📚 Index Bot</b> <i>(admin)</i>\n\n"
        f"Indexed files: <b>{summary['total_uploads']}</b> · "
        f"Library titles: <b>{summary['unique_titles']}</b> · "
        f"Pending review: <b>{summary['pending']}</b>\n"
        f"TMDB: {tmdb_line}\n\n"
        "Use the buttons below — no need to type channel or list names."
    )
    keyboard = [
        [InlineKeyboardButton("⚙️ Library setup", callback_data="setup_hub")],
        [
            InlineKeyboardButton("🔍 Search library", callback_data="search_menu"),
            InlineKeyboardButton("📖 Browse titles", callback_data="library_browse"),
        ],
        [InlineKeyboardButton("📚 Full library (all channels)", callback_data="library_all")],
        [
            InlineKeyboardButton("📋 Lists", callback_data="lists_menu"),
            InlineKeyboardButton("📺 Channels", callback_data="channels_menu"),
        ],
        [InlineKeyboardButton("📂 Channel index", callback_data="channel_index_menu")],
        [InlineKeyboardButton("📺 Watch library", callback_data="watch_hub")],
        [
            InlineKeyboardButton("▶️ Historical ingest", callback_data="backfill_start_menu"),
            InlineKeyboardButton("⏳ Pending", callback_data="pending_menu"),
        ],
        [InlineKeyboardButton("📊 Tracking", callback_data="tracking_menu")],
        [InlineKeyboardButton("📤 Upload pipeline", callback_data="up_hub")],
    ]
    dup_n = db.count_duplicate_holds()
    if dup_n:
        text += f"\n\n⚠️ <b>{dup_n}</b> duplicate(s) need review — Upload pipeline."
    await _reply_or_edit(target, text, InlineKeyboardMarkup(keyboard), edit=edit)


async def send_library_browse_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    list_name: str | None = None,
    all_channels: bool = False,
    edit=False,
):
    """Show recent indexed titles as tappable buttons."""
    query = update.callback_query
    target = query if edit and query else update
    channel_ids = None
    if all_channels:
        list_name = None
        list_label = "entire index (all channels)"
        context.user_data["browse_scope"] = "all"
    elif list_name:
        channel_ids = db.get_channels_for_list(list_name)
        if channel_ids is None:
            await _reply_or_edit(target, f"❌ List not found: {escape(list_name)}", edit=edit)
            return
        list_label = list_name
        context.user_data["browse_scope"] = "list"
    else:
        list_name = context.user_data.get("browse_list")
        if list_name and not all_channels:
            channel_ids = db.get_channels_for_list(list_name)
            list_label = list_name
            context.user_data["browse_scope"] = "list"
        else:
            list_label = "recent titles (all channels)"
            context.user_data["browse_scope"] = "default"

    limit = 40 if all_channels or context.user_data.get("browse_scope") == "all" else 20
    titles = db.get_library_browse_entries(limit=limit, channel_ids=channel_ids)
    context.user_data["browse_titles"] = titles
    context.user_data["browse_list"] = list_name

    heading = "📚 Full library" if all_channels else "📖 Browse library"
    lines = [
        f"<b>{heading}</b>",
        f"Scope: <b>{escape(list_label)}</b>",
        "",
    ]
    keyboard = []
    if not titles:
        lines.append(
            "No library titles yet.\n\n"
            "Items without TMDB stay in <b>⏳ Pending</b> until you pick a TMDB match "
            "or enter a custom title."
        )
    else:
        lines.append(
            "TMDB / approved titles — tap to watch:\n"
            "<i>🎬 movie · 📺 series · 🎓 course · year · ★ rating</i>"
        )
        for i, entry in enumerate(titles):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        format_library_button_label(entry),
                        callback_data=f"lib_idx:{i}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    if list_name:
        keyboard.insert(-1, [InlineKeyboardButton("« Lists", callback_data="lists_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_lists_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Pick a list, then browse titles in that list (admin channel groups)."""
    query = update.callback_query
    target = query if edit and query else update
    if update.effective_user and not is_admin(update.effective_user.id):
        await watch_features.send_user_main_menu(update, context, edit=edit)
        return
    lists = db.get_all_custom_lists()
    if not lists:
        await _reply_or_edit(
            target,
            "📋 No lists yet.\n\nUse /create_list to make one (channel picker, no typing @names).",
            InlineKeyboardMarkup([[InlineKeyboardButton("« Main menu", callback_data="main_menu")]]),
            edit=edit,
        )
        return

    context.user_data["list_names"] = [lst.list_name for lst in lists]
    lines = ["<b>📋 Lists</b>", "", "Tap a list to browse its indexed titles:"]
    keyboard = []
    for i, lst in enumerate(lists):
        if lst.is_default or not lst.channel_ids:
            scope = "all active channels"
        else:
            scope = f"{len(lst.channel_ids.split(','))} channel(s)"
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{'🔵' if lst.is_default else '📌'} {lst.list_name}",
                    callback_data=f"list_idx:{i}",
                )
            ]
        )
        lines.append(f"• <b>{escape(lst.list_name)}</b> — {scope}")
    keyboard.append(
        [
            InlineKeyboardButton("➕ New list", callback_data="create_list_start"),
            InlineKeyboardButton("« Main menu", callback_data="main_menu"),
        ]
    )
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_search_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Search help + quick picks from recent titles."""
    query = update.callback_query
    target = query if edit and query else update
    titles = db.get_library_browse_entries(limit=12)
    context.user_data["browse_titles"] = titles
    lines = [
        "<b>🔍 Search</b>",
        "",
        "Send: <code>/search Inception</code>",
        "Or tap a recent title below:",
        "<i>🎬 movie · 📺 series</i>",
    ]
    keyboard = []
    for i, entry in enumerate(titles):
        keyboard.append(
            [
                InlineKeyboardButton(
                    format_library_button_label(entry),
                    callback_data=f"lib_idx:{i}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def watch_help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slash commands for watch channel users (use in bot chat)."""
    bot_user = context.bot.username or "bot"
    await update.message.reply_text(
        "<b>📺 Watch library commands</b>\n\n"
        f"Use these in @{bot_user}:\n"
        "/watch — browse & open the watch channel\n"
        "/favorites — your starred titles\n"
        "/watchlist — your saved lists\n"
        "/portal — open web library (browser / TV)\n"
        "/request — ask for a title to be uploaded (TMDB)\n"
        "/menu — full bot menu\n\n"
        "<i>On each channel card, buttons open this bot for Watch, "
        "Watchlist, and Favorites.</i>",
        parse_mode=ParseMode.HTML,
    )


async def request_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["awaiting_upload_request"] = True
    await update.message.reply_text(
        "<b>➕ Request a title</b>\n\nSend the movie or series name to search TMDB.",
        parse_mode=ParseMode.HTML,
    )


async def favorites_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await watch_features.send_favorites_menu(update, context)


async def watchlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await watch_features.send_watchlists_menu(update, context)


async def portal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from portal_bot import portal_cmd as _portal_cmd

    await _portal_cmd(update, context)


async def watch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and is_admin(update.effective_user.id):
        await watch_features.send_watch_hub_menu(update, context)
    else:
        await watch_features.send_user_main_menu(update, context)


async def tracking_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: open tracking menu (/tracking)."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    await send_tracking_menu(update, context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    name = escape(user.first_name or "")
    args = context.args or []
    if args:
        payload = args[0]
        if await watch_features.handle_start_payload(update, context):
            return
        if payload == "request":
            context.user_data["awaiting_upload_request"] = True
            await update.message.reply_text(
                "<b>➕ Request a title</b>\n\n"
                "Send the <b>movie or series name</b> to match on TMDB.",
                parse_mode=ParseMode.HTML,
            )
            return
        if payload.startswith("title_"):
            try:
                ct_id = int(payload.split("_", 1)[1])
            except ValueError:
                ct_id = None
            if ct_id:
                entries = db.get_library_browse_entries(limit=80)
                idx = next(
                    (i for i, e in enumerate(entries) if e.get("content_title_id") == ct_id),
                    None,
                )
                if idx is None:
                    ct = db.get_content_title(ct_id)
                    entries = [
                        {
                            "title": db.display_title_for_content(ct, "?"),
                            "content_title_id": ct_id,
                            "media_type": (ct.media_type if ct else "movie") or "movie",
                        }
                    ]
                    idx = 0
                context.user_data["browse_titles"] = entries
                await update.message.reply_text(
                    "Opening library title…",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("▶ Open", callback_data=f"lib_idx:{idx}")]]
                    ),
                )
                return
    if user and is_admin(user.id):
        await send_main_menu(update, context, edit=False)
    else:
        await watch_features.handle_user_start(update, context)


async def channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse connected channels with inline selection (admin)."""
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text(
            "❌ Admin only. Use /menu for your personal library menu."
        )
        return
    await send_channels_menu(update, context)


async def run_channel_discovery(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False,
) -> None:
    """Scan user-visible dialogs and register every chat where Index Bot is admin."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        text = "❌ Admin only."
        if edit and update.callback_query:
            await update.callback_query.answer(text, show_alert=True)
        elif update.message:
            await update.message.reply_text(text)
        return

    app = context.application
    if await bot_busy.reject_if_exclusive_busy(update, context):
        return

    if edit and update.callback_query:
        query = update.callback_query
        status = query.message
        await safe_edit_callback_message(
            query,
            "⏳ <b>Please wait</b>\n\n🔍 <b>Discovering channels…</b>\n\n"
            "Scanning your Telegram account for chats where <b>Index Bot</b> is admin.\n"
            "Requires Telethon login: <code>python telethon_login.py</code>\n\n"
            "<i>This may take several minutes.</i>",
            parse_mode=ParseMode.HTML,
        )
    else:
        status = await update.message.reply_text(
            "⏳ <b>Please wait</b>\n\n🔍 <b>Discovering channels…</b>\n\n"
            "Scanning your Telegram account for chats where <b>Index Bot</b> is admin.\n"
            "Requires Telethon login on your PC first: "
            "<code>python telethon_login.py</code> in the project folder.\n\n"
            "<i>This may take several minutes.</i>",
            parse_mode=ParseMode.HTML,
        )

    async def _job() -> None:
        try:
            from discover_bot_channels import discover_bot_admin_channels

            session_name = os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session")
            session_path = Path(session_name)
            if not session_path.is_absolute():
                session_path = Path(__file__).resolve().parent / session_path

            async def progress(scanned: int, found_admin: int, registered: int) -> None:
                try:
                    await bot_edit_message(
                        context,
                        status.chat_id,
                        status.message_id,
                        "⏳ <b>Discovering channels…</b>\n\n"
                        f"Checked: <b>{scanned}</b> channel/group dialogs\n"
                        f"Bot is admin in: <b>{found_admin}</b>\n"
                        f"Saved to database: <b>{registered}</b>",
                    )
                except Exception:
                    pass

            if not Config.API_ID or not Config.API_HASH:
                raise RuntimeError(
                    "Set API_ID and API_HASH in .env (from my.telegram.org/apps)."
                )

            registered, scanned, found_admin = await discover_bot_admin_channels(
                api_id=int(str(Config.API_ID).strip()),
                api_hash=str(Config.API_HASH).strip(),
                session_path=session_path,
                bot_token=Config.BOT_TOKEN,
                progress_callback=progress,
            )

            lines = [
                "<b>✅ Discovery complete</b>",
                "",
                f"Dialogs scanned: <b>{scanned}</b>",
                f"Bot is admin in: <b>{found_admin}</b>",
                f"Registered in database: <b>{len(registered)}</b>",
                "",
                "<b>Channels:</b>",
            ]
            for ch in registered[:25]:
                ingest = " 📥" if getattr(ch, "is_ingest_channel", False) else ""
                lines.append(f"• {escape(channel_button_label(ch))}{ingest}")
            if len(registered) > 25:
                lines.append(f"… and {len(registered) - 25} more — use /channels")

            lines.append("")
            lines.append(
                "<i>Scans your Telegram dialogs plus re-checks known channel ids via the bot. "
                "Private archives you are not in will not appear until you join them.</i>"
            )

            back_cb = (
                "setup_hub"
                if context.user_data.get("setup_return") == "setup_hub"
                else "channels_menu"
            )
            back_label = (
                "« Library setup" if back_cb == "setup_hub" else "📺 Open channel list"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(back_label, callback_data=back_cb)]]
            )
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                "\n".join(lines),
                keyboard,
            )

        except RuntimeError as e:
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                f"❌ <b>Discovery failed</b>\n\n{escape(str(e))}",
            )
        except Exception as e:
            logger.error("Channel discovery failed: %s", e, exc_info=True)
            await bot_edit_message(
                context,
                status.chat_id,
                status.message_id,
                f"❌ Error: {escape(str(e))}",
            )
    _fire_background_job(app, "Discovering channels", _job, exclusive=True)


async def discover_channels_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: scan for all channels where the bot is administrator."""
    await run_channel_discovery(update, context)


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel to monitor (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await send_add_channel_menu(update, context)
        return
    
    channel_username = context.args[0].lstrip('@')
    
    try:
        # Try to get channel info
        bot = context.bot
        chat = await bot.get_chat(f"@{channel_username}")
        
        if chat.type not in _MONITORABLE_CHAT_TYPES:
            await update.message.reply_text("❌ This is not a channel or group.")
            return
        
        existing = db.get_channel(str(chat.id))
        if existing and existing.is_active:
            await update.message.reply_text(f"✅ Channel @{channel_username} is already being monitored.")
            return
        
        channel = register_chat_channel(chat, log_source="add_channel")
        if not channel:
            await update.message.reply_text("❌ Could not register this channel.")
            return

        from bot_channel_access import verify_bot_can_post

        if await verify_bot_can_post(bot, str(chat.id)):
            db.set_channel_bot_can_post(str(chat.id), True)

        await update.message.reply_text(
            f"✅ Channel @{channel_username} ({chat.title}) has been added to monitoring.\n\n"
            f"Make sure the bot is added as an admin to the channel with read permissions."
        )
        
        logger.info(f"Channel {channel_username} added by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        await update.message.reply_text(f"❌ Error adding channel: {str(e)}")


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a channel from monitoring (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await send_remove_channel_menu(update, context)
        return
    
    channel_username = context.args[0].lstrip('@')
    
    try:
        session = db.get_session()
        channel = session.query(Channel).filter_by(channel_username=channel_username).first()
        
        if channel:
            db.set_channel_active(channel.channel_id, False)
            await update.message.reply_text(f"✅ Channel @{channel_username} has been removed from monitoring.")
        else:
            await update.message.reply_text(f"❌ Channel @{channel_username} is not being monitored.")
        session.close()
        
    except Exception as e:
        logger.error(f"Error removing channel: {e}")
        await update.message.reply_text(f"❌ Error removing channel: {str(e)}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List connected channels (interactive menu)."""
    await send_channels_menu(update, context)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for movies/series"""
    if not context.args:
        await send_search_menu(update, context)
        return
    
    # Parse arguments for optional list filter
    args = context.args
    list_name = None
    search_terms = []
    
    i = 0
    while i < len(args):
        if args[i] == '--list' and i + 1 < len(args):
            list_name = args[i + 1]
            i += 2
        else:
            search_terms.append(args[i])
            i += 1
    
    if not search_terms:
        await update.message.reply_text("Usage: /search <movie/series name> [--list <list_name>]")
        return
    
    search_term = ' '.join(search_terms)
    
    # Get channel IDs for list if specified
    channel_ids = None
    if list_name:
        channel_ids = db.get_channels_for_list(list_name)
        if channel_ids is None:
            await update.message.reply_text(f"❌ List '{list_name}' not found. Use /lists to see available lists.")
            return
    
    # Search in specific channels or all
    if channel_ids:
        results = db.search_files_in_channels(search_term, channel_ids)
    else:
        results = db.search_files(search_term)
    
    if not results:
        await update.message.reply_text(f"❌ No results found for '{search_term}'")
        return
    
    # Group results by confirmed/parsed name
    grouped = {}
    for result in results:
        name = result.confirmed_name or result.parsed_name or result.file_name
        if name not in grouped:
            grouped[name] = []
        grouped[name].append(result)
    
    message = f"🔍 **Search Results for '{search_term}':**\n\n"
    
    # If multiple results, show buttons for selection
    if len(grouped) > 1:
        message += "Select a movie/series to view details:\n\n"
        
        store_title_pick_list(context, list(grouped.keys())[:10])
        keyboard = build_title_pick_rows(grouped, max_items=10, label_max=35)
        if len(grouped) > 10:
            message += f"... and {len(grouped) - 10} more result(s)"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        # Single result, show details directly
        name = list(grouped.keys())[0]
        if channel_ids:
            stats = db.get_upload_stats_in_channels(name, channel_ids)
        else:
            stats = db.get_upload_stats(name)
        
        total = stats['total_uploads']
        channels_count = len(stats['channels'])
        
        message += f"**{name}**\n"
        message += f"📊 Uploaded {total} time(s) across {channels_count} channel(s)\n"
        
        # Show channel breakdown
        for channel_id, channel_data in stats['channels'].items():
            count = channel_data['count']
            channel_title = channel_data.get('channel_title') or 'Unknown'
            channel_username = channel_data.get('channel_username')
            username = f"@{channel_username}" if channel_username else channel_id
            message += f"  • {channel_title} ({username}): {count} time(s)\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View files pending admin confirmation with interactive buttons (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    await send_pending_menu(update, context, page=0, edit=False)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm file name (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /confirm <file_id> <correct_name>")
        return
    
    try:
        file_id = int(context.args[0])
        confirmed_name = ' '.join(context.args[1:])
        
        upload = db.confirm_file_name(file_id, confirmed_name)
        
        if upload:
            await update.message.reply_text(
                f"✅ File name confirmed!\n\n"
                f"File: `{upload.file_name}`\n"
                f"Confirmed Name: **{confirmed_name}**"
            )
        else:
            await update.message.reply_text(f"❌ File with ID {file_id} not found.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid file ID. Please provide a number.")
    except Exception as e:
        logger.error(f"Error confirming file: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def library(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View detailed library information for a movie/series"""
    if not context.args:
        await send_library_browse_menu(update, context)
        return
    
    # Parse arguments for optional list filter
    args = context.args
    list_name = None
    name_terms = []
    
    i = 0
    while i < len(args):
        if args[i] == '--list' and i + 1 < len(args):
            list_name = args[i + 1]
            i += 2
        else:
            name_terms.append(args[i])
            i += 1
    
    if not name_terms:
        await update.message.reply_text("Usage: /library <movie/series name> [--list <list_name>]")
        return
    
    movie_name = ' '.join(name_terms)
    
    # Get channel IDs for list if specified
    channel_ids = None
    if list_name:
        channel_ids = db.get_channels_for_list(list_name)
        if channel_ids is None:
            await update.message.reply_text(f"❌ List '{list_name}' not found. Use /lists to see available lists.")
            return
    
    # First, try to find exact match
    uploads = db.get_library_view(movie_name, channel_ids)
    
    if not uploads:
        # Try searching for similar names
        if channel_ids:
            search_results = db.search_files_in_channels(movie_name, channel_ids)
        else:
            search_results = db.search_files(movie_name)
        
        if search_results:
            # Group by name
            grouped = {}
            for result in search_results:
                name = result.confirmed_name or result.parsed_name
                if name and name not in grouped:
                    grouped[name] = []
                if name:
                    grouped[name].append(result)
            
            if len(grouped) == 1:
                # Only one match, show it
                movie_name = list(grouped.keys())[0]
                uploads = db.get_library_view(movie_name, channel_ids)
            else:
                # Multiple matches, show list
                message = f"🔍 **Multiple matches found:**\n\n"
                for name in list(grouped.keys())[:10]:
                    if channel_ids:
                        stats = db.get_upload_stats_in_channels(name, channel_ids)
                    else:
                        stats = db.get_upload_stats(name)
                    message += f"• **{name}** ({stats['total_uploads']} uploads)\n"
                message += "\nUse /library <exact_name> to view details"
                await update.message.reply_text(message, parse_mode='Markdown')
                return
    
    if not uploads:
        await update.message.reply_text(f"❌ No library information found for '{movie_name}'")
        return
    
    # Get stats with channel filter if list specified
    if channel_ids:
        stats = db.get_upload_stats_in_channels(movie_name, channel_ids)
    else:
        stats = db.get_upload_stats(movie_name)
    
    message = f"📚 **Library: {movie_name}**\n\n"
    message += f"📊 Total Uploads: {stats['total_uploads']}\n"
    message += f"📺 Channels: {len(stats['channels'])}\n\n"
    message += "**Upload Details:**\n\n"
    
    # Group by channel and show uploads
    for channel_id, channel_data in stats['channels'].items():
        channel_title = channel_data.get('channel_title') or 'Unknown'
        channel_username = channel_data.get('channel_username')
        channel_uploads = channel_data['uploads']
        username = f"@{channel_username}" if channel_username else channel_id
        
        message += f"📺 **{channel_title}** ({username})\n"
        message += f"   Uploaded {len(channel_uploads)} time(s):\n"
        
        # Sort by uploaded_at (extracted as datetime)
        for upload_data in sorted(channel_uploads, key=lambda x: x.get('uploaded_at') or datetime.min.replace(tzinfo=None), reverse=True):
            uploaded_at = upload_data.get('uploaded_at')
            date_str = uploaded_at.strftime("%Y-%m-%d %H:%M") if uploaded_at else "Unknown"
            status = "✅" if upload_data.get('is_confirmed') else "⏳"
            file_name = upload_data.get('file_name', 'Unknown')
            message += f"   {status} `{file_name}` ({date_str})\n"
        
        message += "\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def create_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a custom list of channels with interactive selection"""
    if not context.args:
        context.user_data["awaiting_list_name"] = True
        await update.message.reply_text(
            "<b>📋 New custom list</b>\n\n"
            "Send the list name in your next message (e.g. <code>MyMovies</code>).\n"
            "You will then pick channels from buttons — no @usernames needed.",
            parse_mode=ParseMode.HTML,
        )
        return
    
    await start_create_list_ui(update, context, context.args[0])


async def delete_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a custom list"""
    if not context.args:
        await update.message.reply_text("Usage: /delete_list <list_name>")
        return
    
    list_name = context.args[0]
    
    try:
        if db.delete_custom_list(list_name):
            await update.message.reply_text(f"✅ List '{list_name}' deleted successfully.")
        else:
            await update.message.reply_text(
                f"❌ List '{list_name}' not found or cannot be deleted.\n"
                f"(Default 'All Channels' list cannot be deleted)"
            )
    except Exception as e:
        logger.error(f"Error deleting list: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def list_lists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all custom lists (interactive menu)."""
    await send_lists_menu(update, context)


async def channel_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View index for a specific channel with interactive selection"""
    if not context.args:
        channels = db.get_all_channels()
        if not channels:
            await update.message.reply_text(
                "📭 No channels available.\n\nUse /channels after adding the bot as admin.",
                parse_mode=ParseMode.HTML,
            )
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    f"📺 {channel_button_label(ch)}",
                    callback_data=f"select_channel:{ch.channel_id}:view",
                )
            ]
            for ch in channels
        ]
        keyboard.append([InlineKeyboardButton("« All channels", callback_data="channels_menu")])
        await update.message.reply_text(
            "<b>📂 Channel index</b>\n\nTap a channel:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
        return
    
    # Legacy support: if channel username provided, use it
    channel_username = context.args[0].lstrip('@')
    
    try:
        bot = context.bot
        chat = await bot.get_chat(f"@{channel_username}" if not channel_username.startswith('-') else channel_username)
        channel_id = str(chat.id)
        
        # Get all files from this channel
        results = db.search_files_in_channels("", [channel_id])  # Empty search = all files
        
        if not results:
            await update.message.reply_text(f"📭 No files indexed from @{channel_username} yet.")
            return
        
        # Group by movie/series name
        grouped = {}
        for result in results:
            name = result.confirmed_name or result.parsed_name or result.file_name
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(result)
        
        message = f"📺 **Channel Index: {chat.title}** (@{channel_username})\n\n"
        message += f"📊 Total Files: {len(results)}\n"
        message += f"🎬 Unique Movies/Series: {len(grouped)}\n\n"
        message += "**Select a movie/series to view details:**\n\n"
        
        store_title_pick_list(context, list(grouped.keys())[:20])
        keyboard = build_title_pick_rows(grouped, max_items=20)
        if len(grouped) > 20:
            message += f"... and {len(grouped) - 20} more"
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error getting channel index: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def test_channel_detection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot can detect channels (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    message = "🔍 **Channel Detection Test**\n\n"
    
    # Check if bot is receiving channel updates
    message += "**Bot Status:**\n"
    message += "✅ Bot is running\n"
    message += "✅ Channel message handler registered\n\n"
    
    # List all registered channels
    channels = db.get_all_channels()
    message += f"**Registered Channels:** {len(channels)}\n"
    if channels:
        for ch in channels[:10]:  # Show first 10
            username = f"@{ch.channel_username}" if ch.channel_username else f"ID: {ch.channel_id}"
            status = "✅ Active" if ch.is_active else "❌ Inactive"
            message += f"• {ch.channel_title or 'Unknown'} ({username}) - {status}\n"
        if len(channels) > 10:
            message += f"... and {len(channels) - 10} more\n"
    else:
        message += "📭 No channels registered yet\n\n"
        message += "**To test auto-detection:**\n"
        message += "1. Add bot as admin to a channel\n"
        message += "2. Upload a file to that channel\n"
        message += "3. Check logs for 'Auto-registered channel'\n"
        message += "4. Run /list_channels to verify"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def test_tmdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test TMDB lookup (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /test_tmdb <movie/series name>")
        return
    
    if not tmdb_helper.enabled:
        await update.message.reply_text("❌ TMDB API is not configured or not available.")
        return
    
    search_term = ' '.join(context.args)
    result = tmdb_helper.search(search_term)
    
    if result:
        message = f"""
✅ **TMDB Lookup Result:**

**Title:** {result['title']}
**Type:** {result['type'].upper()}
**Year:** {result.get('year', 'N/A')}
**TMDB ID:** {result['id']}
"""
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ No results found for '{search_term}' in TMDB")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View indexing statistics"""
    session = db.get_session()
    try:
        total_files = session.query(FileUpload).count()
        confirmed_files = session.query(FileUpload).filter_by(is_confirmed=True).count()
        pending_files = session.query(FileUpload).filter_by(needs_confirmation=True).count()
        total_channels = session.query(Channel).filter_by(is_active=True).count()
        
        tmdb_status = "✅ Enabled" if tmdb_helper.enabled else "❌ Disabled"
        
        message = f"""
📊 **Indexing Statistics:**

📁 Total Files: {total_files}
✅ Confirmed: {confirmed_files}
⏳ Pending: {pending_files}
📺 Channels: {total_channels}
🎬 TMDB API: {tmdb_status}
"""
        await update.message.reply_text(message, parse_mode='Markdown')
    finally:
        session.close()


async def send_set_ingest_channel_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit=False,
    back_callback: str = "backfill_menu",
):
    """Pick which channel is the dedicated historical ingest channel."""
    query = update.callback_query
    target = query if edit and query else update
    back_label = (
        "« Library setup" if back_callback == "setup_hub" else "« Back to backfill guide"
    )

    channels = db.get_channels_bot_can_post(active_only=True)
    if not channels:
        await _reply_or_edit(
            target,
            "📭 No channels where the bot can post yet.\n\n"
            "Create your ingest channel, add Index bot as <b>admin</b>, post once there, "
            "or run <b>Discover bot channels</b>.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton(back_label, callback_data=back_callback)]]
            ),
            edit=edit,
        )
        return

    lines = [
        "<b>📥 Set historical ingest channel</b>",
        "",
        "Choose the channel used <b>only</b> for old uploads (forwards from archives).",
        "Other library channels stay separate.",
    ]
    keyboard = []
    for ch in channels:
        marker = "✅ " if getattr(ch, "is_ingest_channel", False) else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{marker}📥 {channel_button_label(ch)}",
                    callback_data=f"set_ingest_channel:{ch.channel_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton(back_label, callback_data=back_callback)])
    await _reply_or_edit(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_backfill_guide(update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False):
    """Step-by-step historical ingest setup for admins."""
    query = update.callback_query
    target = query if edit and query else update

    ingest = db.get_ingest_channel()
    if ingest:
        ingest_line = (
            f"✅ Registered in bot: <b>{escape(channel_button_label(ingest))}</b>"
        )
        dest_hint = (
            f"@{(ingest.channel_username)}"
            if ingest.channel_username
            else ingest.channel_id
        )
    else:
        ingest_line = "⚠️ <b>Not registered yet</b> — complete step 4 below."
        dest_hint = "@YourIngestChannel"

    text = (
        "<b>📚 Historical library setup</b>\n\n"
        "Use this when you want to index <b>old</b> uploads. "
        "New uploads in normal channels are handled automatically.\n\n"
        "<b>1.</b> Create a new Telegram channel (e.g. <i>Historical Ingestion</i>).\n"
        "    Use a <b>private</b> channel if you prefer — only admins need access.\n\n"
        "<b>2.</b> Add <b>Index Bot</b> to that channel as <b>admin</b> "
        "(permission to read posts is enough).\n\n"
        "<b>3.</b> Do <b>not</b> use this channel for normal day-to-day uploads. "
        "It is only the destination for forwarded old files.\n\n"
        "<b>4.</b> Set the ingest channel under <b>⚙️ Library setup</b> on the admin menu:\n"
        f"    {ingest_line}\n\n"
        "<b>5.</b> Start historical ingestion from a <b>source</b> channel — "
        "forwards old files into the ingest channel; the bot indexes each forward.\n"
        "    Use the button below (requires Telethon login on your PC).\n\n"
        "<b>📡 Member watch</b> — for channels where <b>you</b> are a member but the "
        "bot is not admin (e.g. Primeroom), new uploads are polled automatically via "
        "Telethon every few minutes. Old posts still need step 5.\n\n"
        "<b>6.</b> Optional CLI dry run:\n"
        f"    <code>python forward_ingest.py @SourceChannel {escape(dest_hint)} --dry-run</code>\n\n"
        "Need API_ID / API_HASH in <code>.env</code> — see HOW_TO_RUN.md."
    )
    keyboard = [
        [InlineKeyboardButton("⚙️ Set channels (Library setup)", callback_data="setup_hub")],
    ]
    if ingest:
        keyboard.append(
            [InlineKeyboardButton("▶️ Start historical ingestion", callback_data="backfill_start_menu")]
        )
    keyboard.append([InlineKeyboardButton("📺 Connected channels", callback_data="channels_menu")])
    await _reply_or_edit(target, text, InlineKeyboardMarkup(keyboard), edit=edit)


def _backfill_source_channels() -> list:
    ingest_id = _ingest_channel_id_str()
    channels = [
        ch
        for ch in db.get_all_channels_registered(active_only=False)
        if not getattr(ch, "is_ingest_channel", False)
        and str(ch.channel_id) != ingest_id
    ]
    return sorted(
        channels,
        key=lambda c: (not c.is_active, (c.channel_title or "").lower()),
    )


async def send_backfill_source_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    page: int = 0,
    query: str | None = None,
    edit: bool = False,
) -> None:
    """Searchable paginated source channel list for historical ingest."""
    from channel_picker import build_channel_picker

    target = update.callback_query if edit and update.callback_query else update
    ingest = db.get_ingest_channel()
    if not ingest:
        await send_start_backfill_menu(update, context, edit=edit)
        return
    sources = _backfill_source_channels()
    title = (
        "<b>▶️ Start historical ingestion</b>\n\n"
        f"Destination (ingest): <b>{escape(channel_button_label(ingest))}</b>\n\n"
        "Pick a <b>source</b> channel (ingest channel excluded).\n"
        "<i>Missing a channel? Run <b>Discover bot channels</b> first (Library setup).</i>\n"
        "<i>Uses your Telethon user — same account as telethon_login.py.</i>"
    )
    index_stats = db.get_channel_index_stats()

    def _backfill_source_label(ch) -> str:
        st = index_stats.get(str(ch.channel_id), {})
        prefix = "⏸ " if not ch.is_active else ""
        return prefix + channel_list_label_with_status(
            ch,
            live_count=st.get("live", 0),
            backfill_count=st.get("backfill", 0),
            file_count=None,
            label_fn=channel_button_label,
            max_len=56,
        )

    text, markup = build_channel_picker(
        sources,
        page=page,
        query=query,
        callback_prefix="bfch",
        pick_prefix="backfill_pick",
        label_fn=_backfill_source_label,
        back_callback="backfill_menu",
        back_label="« Back to backfill guide",
        search_callback="bfch_search",
        title_line=title,
    )
    await _reply_or_edit(target, text, markup, edit=edit)


async def send_start_backfill_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit=False,
) -> None:
    """Pick a source channel to backfill into the ingest channel."""
    query = update.callback_query
    target = query if edit and query else update

    ingest = db.get_ingest_channel()
    if not ingest:
        await _reply_or_edit(
            target,
            "⚠️ <b>Ingest channel not set</b>\n\n"
            "Register your ingest channel first, then start historical ingestion.",
            InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⚙️ Library setup", callback_data="setup_hub")],
                    [InlineKeyboardButton("« Back", callback_data="backfill_menu")],
                ]
            ),
            edit=edit,
        )
        return
    
    sources = _backfill_source_channels()
    if not sources:
        await _reply_or_edit(
            target,
            "⚠️ <b>No source channels registered.</b>\n\n"
            "Use /discover_channels or post once in a channel.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Back to backfill guide", callback_data="backfill_menu")]]
            ),
            edit=edit,
        )
        return
    await send_backfill_source_picker(update, context, edit=edit)


async def send_backfill_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channel_id: str,
    *,
    edit=False,
) -> None:
    """Confirm backfill for one source channel."""
    query = update.callback_query
    target = query if edit and query else update

    ingest = db.get_ingest_channel()
    source = db.get_channel(channel_id)
    if not ingest:
        await send_start_backfill_menu(update, context, edit=edit)
        return
    if not source or getattr(source, "is_ingest_channel", False):
        await _reply_or_edit(target, "❌ Source channel not found.", edit=edit)
        return

    text = (
        "<b>▶️ Historical ingestion</b>\n\n"
        f"<b>Source:</b> {escape(channel_button_label(source))}\n"
        f"<b>Destination:</b> {escape(channel_button_label(ingest))}\n\n"
        "• <b>Dry run</b> — count indexable + duplicate report\n"
        "• <b>Start</b> — forward all indexable media\n"
        "• <b>Start (skip dupes)</b> — skip files already in the library\n\n"
        "<i>Keep the bot running so forwards get indexed.</i>"
    )
    keyboard = [
        [
            InlineKeyboardButton(
                "🔍 Dry run",
                callback_data=f"backfill_run:{channel_id}:dry",
            ),
        ],
        [
            InlineKeyboardButton(
                "▶️ Start forwarding",
                callback_data=f"backfill_run:{channel_id}:live",
            ),
            InlineKeyboardButton(
                "▶️ Skip duplicates",
                callback_data=f"backfill_run:{channel_id}:live_skip",
            ),
        ],
        [InlineKeyboardButton("« Choose another source", callback_data="backfill_start_menu")],
    ]
    await _reply_or_edit(target, text, InlineKeyboardMarkup(keyboard), edit=edit)


async def run_historical_ingest(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    channel_id: str,
    *,
    dry_run: bool = False,
    skip_duplicates: bool = False,
    edit: bool = False,
) -> None:
    """Forward old media from source channel into ingest channel (Telethon)."""
    user_id = update.effective_user.id if update.effective_user else 0
    if not is_admin(user_id):
        text = "❌ Admin only."
        if edit and update.callback_query:
            await safe_answer_callback(update.callback_query, text, show_alert=True)
        elif update.message:
            await update.message.reply_text(text)
        return

    ingest = db.get_ingest_channel()
    source = db.get_channel(channel_id)
    if not ingest:
        if edit and update.callback_query:
            await safe_answer_callback(
                update.callback_query, "Set ingest channel first", show_alert=True
            )
        return
    if not source or getattr(source, "is_ingest_channel", False):
        if edit and update.callback_query:
            await safe_answer_callback(
                update.callback_query, "Invalid source channel", show_alert=True
            )
        return

    if context.user_data.get("backfill_running") or bot_busy.is_busy(context.application):
        msg = "⏳ Historical ingestion already running. Wait for it to finish."
        if edit and update.callback_query:
            await safe_answer_callback(update.callback_query, msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(msg)
        return

    if dry_run:
        mode_label = "Dry run"
    elif skip_duplicates:
        mode_label = "Live (skip duplicates)"
    else:
        mode_label = "Live forwarding"
    source_name = channel_button_label(source)
    ingest_name = channel_button_label(ingest)

    chat_id: int | None = None
    message_id: int | None = None
    if edit and update.callback_query:
        query = update.callback_query
        await safe_answer_callback(query, f"▶️ {mode_label} started")
        chat_id = query.message.chat_id
        message_id = query.message.message_id
    elif update.message:
        status_msg = await update.message.reply_text(
            format_backfill_progress(
                mode_label=mode_label,
                source_label=source_name,
                ingest_label=ingest_name,
                phase="Starting…",
                scanned=0,
                forwarded=0,
                skipped=0,
                elapsed_s=0,
            ),
            parse_mode=ParseMode.HTML,
        )
        chat_id = status_msg.chat_id
        message_id = status_msg.message_id

    if chat_id is None or message_id is None:
        return

    progress_text = format_backfill_progress(
        mode_label=mode_label,
        source_label=source_name,
        ingest_label=ingest_name,
        phase="Connecting to Telegram…",
        scanned=0,
        forwarded=0,
        skipped=0,
        elapsed_s=0,
    )
    if edit and update.callback_query:
        await safe_edit_callback_message(
            update.callback_query,
            "⏳ <b>Please wait</b>\n\n" + progress_text,
            parse_mode=ParseMode.HTML,
        )
    else:
        await bot_edit_message(context, chat_id, message_id, progress_text)

    context.user_data["backfill_running"] = True
    source_ref = channel_telegram_ref(source)

    async def backfill_job() -> None:
        from forward_ingest import resolve_ingest_dest, run_forward

        start = time.monotonic()
        last_ui = 0.0
        phase = "Connecting to Telegram…"
        counts = {"scanned": 0, "forwarded": 0, "skipped": 0, "duplicates": 0}
        heartbeat_stop = asyncio.Event()

        async def refresh_ui(force: bool = False) -> None:
            nonlocal last_ui
            now = time.monotonic()
            if not force and now - last_ui < 3:
                return
            last_ui = now
            await bot_edit_message(
                context,
                chat_id,
                message_id,
                format_backfill_progress(
                    mode_label=mode_label,
                    source_label=source_name,
                    ingest_label=ingest_name,
                    phase=phase,
                    scanned=counts["scanned"],
                    forwarded=counts["forwarded"],
                    skipped=counts["skipped"],
                    elapsed_s=now - start,
                    duplicates=counts["duplicates"],
                ),
            )

        async def heartbeat() -> None:
            while not heartbeat_stop.is_set():
                await asyncio.sleep(8)
                if not heartbeat_stop.is_set():
                    await refresh_ui(force=True)

        async def progress(scanned: int, forwarded: int, skipped: int, duplicates: int = 0) -> None:
            nonlocal phase
            counts["scanned"] = scanned
            counts["forwarded"] = forwarded
            counts["skipped"] = skipped
            counts["duplicates"] = duplicates
            if scanned == 0:
                phase = "Connected — starting scan…"
            else:
                phase = "Scanning channel history…"
            await refresh_ui()

        hb_task = asyncio.create_task(heartbeat())
        try:
            session_name = os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session")
            session_path = Path(session_name)
            if not session_path.is_absolute():
                session_path = Path(__file__).resolve().parent / session_path

            if not Config.API_ID or not Config.API_HASH:
                raise RuntimeError("Set API_ID and API_HASH in .env (from my.telegram.org/apps).")

            dest = resolve_ingest_dest()
            phase = "Scanning channel history…"
            await refresh_ui(force=True)

            scanned, forwarded, skipped, duplicates = await run_forward(
                source=source_ref,
                dest=dest,
                session_path=session_path,
                api_id=int(str(Config.API_ID).strip()),
                api_hash=str(Config.API_HASH).strip(),
                limit=None,
                batch_size=15,
                delay_s=2.0,
                dry_run=dry_run,
                skip_duplicates=skip_duplicates,
                progress_callback=progress,
                source_peer_id=source.channel_id,
                dest_peer_id=ingest.channel_id,
                source_label=source.channel_title,
                dest_label=ingest.channel_title,
            )

            if dry_run:
                new_est = max(0, forwarded - duplicates)
                summary = (
                    "<b>✅ Dry run complete</b>\n\n"
                    f"Source: <b>{escape(source_name)}</b>\n"
                    f"Messages scanned: <b>{scanned:,}</b>\n"
                    f"Indexable media: <b>{forwarded:,}</b>\n"
                    f"Already in library: <b>{duplicates:,}</b>\n"
                    f"Would forward (new): <b>{new_est:,}</b>\n"
                    f"Skipped (no media): <b>{skipped:,}</b>\n\n"
                    "Choose how to forward when ready."
                )
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "▶️ Forward all",
                                callback_data=f"backfill_run:{channel_id}:live",
                            ),
                            InlineKeyboardButton(
                                "▶️ Skip dupes",
                                callback_data=f"backfill_run:{channel_id}:live_skip",
                            ),
                        ],
                        [InlineKeyboardButton("« Back", callback_data="backfill_start_menu")],
                    ]
                )
            else:
                await asyncio.to_thread(
                    db.mark_channel_historical_ingest,
                    channel_id,
                    imported_count=forwarded,
                )
                summary = (
                    "<b>✅ Historical ingestion finished</b>\n\n"
                    f"Source: <b>{escape(source_name)}</b>\n"
                    f"Messages scanned: <b>{scanned:,}</b>\n"
                    f"Forwarded: <b>{forwarded:,}</b>\n"
                    f"Duplicates skipped: <b>{duplicates:,}</b>\n"
                    f"Skipped (no media): <b>{skipped:,}</b>\n\n"
                    "Marked as <b>📜 historically ingested</b> in Connected channels.\n"
                    "Check your ingest channel — the bot should index new forwards."
                )
                keyboard = InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "▶️ Backfill another channel",
                                callback_data="backfill_start_menu",
                            )
                        ],
                        [InlineKeyboardButton("📺 Channels", callback_data="channels_menu")],
                    ]
                )
            await bot_edit_message(context, chat_id, message_id, summary, keyboard)

        except RuntimeError as e:
            await bot_edit_message(
                context,
                chat_id,
                message_id,
                f"❌ <b>Historical ingestion failed</b>\n\n{escape(str(e))}",
            )
        except Exception as e:
            logger.error("Historical ingestion failed: %s", e, exc_info=True)
            await bot_edit_message(
                context,
                chat_id,
                message_id,
                f"❌ <b>Error:</b> {escape(str(e))}",
            )
        finally:
            heartbeat_stop.set()
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
            context.user_data.pop("backfill_running", None)

    _fire_background_job(
        context.application, "Historical ingestion", backfill_job, exclusive=True
    )


async def start_backfill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: pick a source channel and start historical ingestion."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    await send_start_backfill_menu(update, context)


async def backfill_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Historical ingest setup guide (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    await send_backfill_guide(update, context)


async def set_ingest_channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mark one channel as the historical ingest channel (admin only)."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    if context.args:
        username = context.args[0].lstrip("@")
        try:
            chat = await context.bot.get_chat(f"@{username}")
            existing = db.get_channel(str(chat.id))
            if not existing:
                db.add_channel(str(chat.id), chat.username, chat.title)
            channel = db.set_ingest_channel(str(chat.id))
            if channel:
                await update.message.reply_text(
                    f"✅ Historical ingest channel set to:\n<b>{escape(channel_button_label(channel))}</b>\n\n"
                    "Use /backfill for the full setup checklist.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await update.message.reply_text("❌ Could not set ingest channel.")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return
    await send_set_ingest_channel_menu(update, context)


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-register when the bot is added to or removed from a channel/group."""
    cm = update.my_chat_member
    if not cm or cm.new_chat_member.user.id != context.bot.id:
        return

    chat = cm.chat
    if chat.type not in _MONITORABLE_CHAT_TYPES:
        return

    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status
    logger.info(
        "my_chat_member %s (%s): %s -> %s",
        chat.title or chat.id,
        chat.id,
        old_status,
        new_status,
    )

    if new_status in _JOIN_STATUSES:
        can_post = new_status in (
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.OWNER,
        )
        register_chat_channel(chat, log_source="my_chat_member", bot_can_post=can_post)
        if can_post:
            db.set_telethon_watch_enabled(str(chat.id), False)
    elif new_status in _LEFT_STATUSES:
        db.set_channel_active(str(chat.id), False)
        db.set_channel_bot_can_post(str(chat.id), False)
        logger.info("Deactivated channel %s (bot removed)", chat.id)


async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from monitored channels - auto-detects channels"""
    if update.channel_post is None:
        logger.debug("Received update but channel_post is None")
        return
    
    chat = update.channel_post.chat
    message = update.channel_post
    
    logger.info(f"Received message from channel: {chat.id} ({chat.title or 'Unknown'})")
    
    channel = db.get_channel(str(chat.id))
    if not channel or not channel.is_active:
        channel = register_chat_channel(chat, log_source="channel_post")
        if not channel:
            return
    else:
        logger.debug(f"Channel {chat.id} already registered and active")

    if channel and not getattr(channel, "bot_can_post", False):
        from bot_channel_access import verify_bot_can_post

        if await verify_bot_can_post(context.bot, str(chat.id)):
            db.set_channel_bot_can_post(str(chat.id), True)
            channel = db.get_channel(str(chat.id))
    
    if not channel.is_active:
        return
    
    extracted = extract_message_file(message)
    if not extracted:
        return
    file_name = extracted["file_name"]

    if not is_indexable_filename(file_name):
        logger.debug("Skipping subtitle/non-media file: %s", file_name)
        return

    source_channel_id = resolve_forward_source_channel(message)

    # Check if file already exists
    if db.file_exists(str(chat.id), message.message_id):
        return

    from fingerprint import compute_content_fingerprint
    from pipeline_router import (
        schedule_pipeline_route,
        try_complete_route_on_bucket_post,
    )

    fp = compute_content_fingerprint(
        file_name,
        extracted.get("file_size"),
        file_unique_id=extracted.get("file_unique_id"),
    )
    if try_complete_route_on_bucket_post(
        db,
        channel_id=str(chat.id),
        message_id=message.message_id,
        fingerprint=fp,
    ):
        logger.info(
            "Attached routed upload for %s in %s (msg %s)",
            file_name,
            chat.title,
            message.message_id,
        )
        return

    chat_id_s = str(chat.id)
    chat_title = chat.title or "Unknown"
    msg_id = message.message_id

    async def _ingest_file() -> None:
        import functools

        from bot_busy import wait_while_upload_active

        await wait_while_upload_active(context.application)

        try:
            from bot_busy import upload_job_active

            upload, info = await asyncio.to_thread(
                functools.partial(
                    index_channel_upload,
                    db,
                    parser,
                    tmdb_helper,
                    channel_id=chat_id_s,
                    message_id=msg_id,
                    source_channel_id=source_channel_id,
                    extracted=extracted,
                    refresh_job_on_link=not upload_job_active(
                        context.application
                    ),
                ),
            )
            if info.get("status") == "duplicate_hold":
                dup_of = getattr(upload, "duplicate_of_upload_id", None) if upload else None
                logger.info(
                    "Duplicate hold: %s (matches existing #%s)",
                    file_name,
                    dup_of or "?",
                )
                return
            upload_id = upload.id if upload else None
            meta = info.get("meta") or {}
            if meta.get("tmdb_result"):
                logger.info(
                    "TMDB validated: %s -> content_title_id=%s",
                    file_name,
                    meta.get("content_title_id"),
                )
            elif meta.get("needs_tmdb_pick"):
                logger.info("TMDB pick needed for %s", file_name)
            if upload_id:
                from tmdb_ingest_retry import schedule_tmdb_ingest_retry, should_queue_tmdb_retry

                if should_queue_tmdb_retry(meta, tmdb_helper=tmdb_helper):
                    schedule_tmdb_ingest_retry(
                        context.application,
                        upload_id,
                        db=db,
                        parser=parser,
                        tmdb_helper=tmdb_helper,
                    )
                if meta.get("library_visible"):
                    schedule_watch_publish(
                        context, upload_id, library_visible=True
                    )
                route = info.get("route") or {}
                if route.get("queued") and route.get("upload_id"):
                    schedule_pipeline_route(
                        context.application, int(route["upload_id"])
                    )
            src_note = f" (source {source_channel_id})" if source_channel_id else ""
            logger.info(
                "Indexed file: %s -> %s in %s%s",
                file_name,
                meta.get("parsed_name"),
                chat_title,
                src_note,
            )
        except Exception as e:
            logger.error("Error indexing file: %s", e)

    async def _enqueue() -> None:
        await enqueue_ingest(
            context.application,
            f"index:{file_name[:48]}",
            _ingest_file,
        )

    context.application.create_task(_enqueue())


async def handle_forwarded_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Register a channel when an admin forwards a post from it (admin only)."""
    if not update.message or not is_admin(update.effective_user.id):
        return
    chat = _forward_source_chat(update.message)
    if not chat:
        await update.message.reply_text(
            "❌ Could not read which channel this forward came from.\n\n"
            "Forward a post that still shows the <b>channel name</b> at the top "
            "(not a hidden-user forward).\n"
            "Or use <b>Register channel → Enter @username</b> if the channel is public.",
            parse_mode=ParseMode.HTML,
        )
        return
    if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP):
        return
    try:
        channel = register_chat_channel(chat, log_source="forwarded_message")
        if not channel:
            return
        label = channel_button_label(channel)
        await update.message.reply_text(
            f"✅ Channel registered and monitoring:\n<b>{escape(label)}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Error registering forwarded channel: {e}")
        await update.message.reply_text(f"❌ Could not register channel: {e}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for custom name input)"""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id if update.effective_user else 0
    if bot_busy.is_busy(context.application) and is_admin(user_id):
        # Admins: offer the menu instead of a dead-end while a heavy job runs.
        # Upload planning (folder scan / job name) must keep working during ▶️ upload.
        awaiting = any(
            k.startswith("awaiting_") and context.user_data.get(k)
            for k in context.user_data
        )
        upload_planning = bool(context.user_data.get("upload_wizard"))
        if not awaiting and not upload_planning:
            await send_main_menu(update, context, edit=False)
            return

    text = (update.message.text or "").strip()

    if await watch_features.handle_watch_text(update, context, user_id):
        return

    if await vault_features.handle_vault_search_text(update, context, text):
        return

    if await archive_browse.handle_archive_search_text(update, context, text):
        return

    if await upload_features.handle_upload_admin_text(update, context, text, user_id):
        return

    if context.user_data.pop("awaiting_list_name", None):
        await start_create_list_ui(update, context, update.message.text.strip())
        return

    if context.user_data.pop("awaiting_upload_csv", None):
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        text = update.message.text or ""
        if update.message.document and update.message.document.file_name:
            try:
                f = await update.message.document.get_file()
                raw = await f.download_as_bytearray()
                text = raw.decode("utf-8", errors="replace")
            except Exception as e:
                await update.message.reply_text(f"❌ Could not read file: {e}")
                return
        wiz = context.user_data.pop("upload_wizard", {}) or {}
        lane = wiz.get("lane")
        ok, msg, job_id = await upload_features.import_csv_job(
            text, user_id, lane=lane
        )
        markup = None
        if ok and job_id:
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Open job", callback_data=f"up_job:{job_id}")]]
            )
        await update.message.reply_text(
            msg if ok else f"❌ {msg}",
            parse_mode=ParseMode.HTML if ok else None,
            reply_markup=markup,
        )
        return

    if context.user_data.pop("awaiting_add_channel_username", None):
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        username = update.message.text.strip().lstrip("@")
        if not username:
            await update.message.reply_text("❌ Send a channel @username.")
            return
        context.args = [username]
        await add_channel(update, context)
        return

    channel_search = context.user_data.pop("awaiting_channel_search", None)
    if channel_search == "backfill":
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        q = update.message.text.strip()
        await send_backfill_source_picker(update, context, page=0, query=q, edit=False)
        return
    if channel_search == "channels":
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        q = update.message.text.strip()
        await send_channels_picker(update, context, page=0, query=q, edit=False)
        return

    # Manual TMDB search query (batch)
    bulk_search_key = context.user_data.pop("bulk_tmdb_search_match_key", None)
    if bulk_search_key:
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        query_text = update.message.text.strip()
        if not query_text:
            context.user_data["bulk_tmdb_search_match_key"] = bulk_search_key
            await update.message.reply_text("❌ Send a non-empty title to search on TMDB.")
            return

        chat_id = update.message.chat_id
        hdr_key = _bulk_tmdb_header_match_key(context, bulk_search_key)
        header_id = context.user_data.get(_tmdb_header_msg_key(match_key=hdr_key))
        searching = (
            f"⏳ <b>Searching TMDB for</b> <code>{escape(query_text)}</code>…"
        )
        if header_id:
            await bot_edit_message(context, chat_id, header_id, searching, None)
            anchor = HeaderEditAnchor(
                context.bot, chat_id, header_id, update.effective_user
            )
        else:
            status_msg = await update.message.reply_text(
                searching, parse_mode=ParseMode.HTML
            )
            context.user_data[_tmdb_header_msg_key(match_key=hdr_key)] = (
                status_msg.message_id
            )
            anchor = HeaderEditAnchor(
                context.bot,
                chat_id,
                status_msg.message_id,
                update.effective_user,
            )
        _fire_interactive_job(
            context.application,
            f"TMDB search batch {query_text[:28]}",
            lambda: _run_bulk_tmdb_pick_job(
                anchor,
                context,
                bulk_search_key,
                search_query_override=query_text,
            ),
        )
        return

    # Manual TMDB search query (single file)
    tmdb_search_file_id = context.user_data.pop("pending_tmdb_search_file_id", None)
    if tmdb_search_file_id:
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        query_text = update.message.text.strip()
        if not query_text:
            context.user_data["pending_tmdb_search_file_id"] = tmdb_search_file_id
            await update.message.reply_text("❌ Send a non-empty title to search on TMDB.")
            return
        upload = db.get_file_upload(int(tmdb_search_file_id))
        if not upload:
            await update.message.reply_text("❌ File not found — open Pending again.")
            return

        chat_id = update.message.chat_id
        fid = int(tmdb_search_file_id)
        header_id = context.user_data.get(_tmdb_header_msg_key(file_id=fid))
        searching = (
            f"⏳ <b>Searching TMDB for</b> <code>{escape(query_text)}</code>…"
        )
        if header_id:
            await bot_edit_message(context, chat_id, header_id, searching, None)
            anchor = HeaderEditAnchor(
                context.bot, chat_id, header_id, update.effective_user
            )
        else:
            status_msg = await update.message.reply_text(
                searching, parse_mode=ParseMode.HTML
            )
            context.user_data[_tmdb_header_msg_key(file_id=fid)] = (
                status_msg.message_id
            )
            anchor = HeaderEditAnchor(
                context.bot,
                chat_id,
                status_msg.message_id,
                update.effective_user,
            )
        _fire_interactive_job(
            context.application,
            f"TMDB search file {tmdb_search_file_id}",
            lambda: _run_tmdb_pick_job(
                anchor,
                context,
                fid,
                file_name=upload.file_name,
                parsed_name=upload.parsed_name,
                search_query_override=query_text,
            ),
        )
        return

    if context.user_data.pop("pending_strip_rule_add", False):
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        pattern = update.message.text.replace("\r", "").replace("\n", "")
        if not pattern.strip():
            await update.message.reply_text("❌ Prefix cannot be empty.")
            return
        from name_parser import invalidate_filename_strip_rules_cache

        row = db.add_filename_strip_rule(pattern)
        invalidate_filename_strip_rules_cache()
        await update.message.reply_text(
            f"✅ Prefix saved:\n<code>{escape(pattern)}</code>\n\n"
            "Open <b>Library setup → Filename prefix rules</b> to review or test.",
            parse_mode=ParseMode.HTML,
        )
        return

    if context.user_data.pop("pending_strip_rule_test", False):
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        sample = update.message.text.strip()
        if not sample:
            await update.message.reply_text("❌ Send a filename to test.")
            return
        from name_parser import apply_filename_strip_rules

        context.user_data["strip_preview_sample"] = sample
        stripped = apply_filename_strip_rules(sample)
        parsed = parser.parse_name(sample)
        title = parsed.get("show_name") or parsed.get("name") or "?"
        await update.message.reply_text(
            "🧪 <b>Filename preview</b>\n\n"
            f"File: <code>{escape(sample[:200])}</code>\n"
            f"After strip: <code>{escape(stripped[:200])}</code>\n"
            f"Parsed title: <b>{escape(title)}</b>\n\n"
            "<i>Library setup → Filename prefix rules for the full list.</i>",
            parse_mode=ParseMode.HTML,
        )
        return
    
    # Batch custom title for pending series group
    if context.user_data.get("bulk_custom_match_key"):
        match_key = context.user_data.pop("bulk_custom_match_key")
        no_catalog = bool(context.user_data.pop("bulk_custom_no_catalog", False))
        custom_name = update.message.text.strip()
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await update.message.reply_text(
                "❌ Batch expired. Open <b>/menu → Pending</b> and try again.",
                parse_mode=ParseMode.HTML,
            )
            return
        mt = group.get("media_type") or "tv"
        file_ids = group["file_ids"]
        try:
            match = None
            if tmdb_helper.enabled:
                suggestions = tmdb_helper.get_suggestions(
                    custom_name, media_type=mt, limit=6
                )
                match = (
                    tmdb_helper.pick_best_match(suggestions, custom_name, media_type=mt)
                    if suggestions
                    else None
                )
            if match and titles_match(custom_name, match.get("title", "")) and not no_catalog:
                n = _apply_tmdb_bulk(file_ids, match)
                title_line = match.get("title") or custom_name
                note = ""
            elif no_catalog:
                n = _apply_custom_bulk(
                    file_ids, custom_name, media_type=mt, catalog_excluded=True
                )
                title_line = custom_name
                note = "\n\n<i>🚫 Not for watch channel — library browse only.</i>"
            else:
                n = _apply_custom_bulk(file_ids, custom_name, media_type=mt)
                title_line = custom_name
                note = ""
            await _finish_pending_map_and_continue(
                context,
                chat_id=update.effective_chat.id,
                success_text=(
                    f"✅ <b>Batch saved ({n} files)</b>\n\n"
                    f"Title: <b>{escape(title_line)}</b>{note}"
                ),
                match_key=match_key,
            )
        except Exception as e:
            logger.error("Bulk custom title failed: %s", e)
            await update.message.reply_text(f"❌ Error: {str(e)}")
        return

    # Check if user is entering custom name for file confirmation
    if 'pending_confirm_file_id' in context.user_data:
        file_id = context.user_data['pending_confirm_file_id']
        no_catalog = bool(context.user_data.pop("pending_custom_no_catalog", False))
        custom_name = update.message.text.strip()
        
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            del context.user_data['pending_confirm_file_id']
            return
        
        try:
            session = db.get_session()
            try:
                file_upload = session.query(FileUpload).filter_by(id=file_id).first()
                if not file_upload:
                    await update.message.reply_text(f"❌ File with ID {file_id} not found.")
                    return
                meta = build_index_metadata(
                    file_upload.file_name,
                    parser=parser,
                    tmdb_helper=tmdb_helper,
                    db=db,
                )
                mt = meta.get("media_type") or "movie"
                suggestions = []
                if tmdb_helper.enabled:
                    suggestions = tmdb_helper.get_suggestions(
                        custom_name,
                        media_type=mt,
                        limit=6,
                    )
                match = (
                    tmdb_helper.pick_best_match(suggestions, custom_name, media_type=mt)
                    if suggestions
                    else None
                )
                upload = None
                note = ""
                if (
                    not no_catalog
                    and match
                    and titles_match(custom_name, match.get("title", ""))
                ):
                    upload = _apply_tmdb_selection(file_id, match, meta)
                    if upload:
                        schedule_watch_publish(
                            context, upload.id, library_visible=bool(match.get("tmdb_id"))
                        )
                else:
                    parsed = meta.get("parsed") or {}
                    if mt == "tv":
                        display = episode_display_name(
                            custom_name,
                            parsed.get("season"),
                            parsed.get("episode"),
                            parsed.get("episode_title"),
                        )
                    else:
                        display = custom_name
                    upload = db.apply_tmdb_pick(
                        file_id,
                        local_name=custom_name,
                        parsed_name=display,
                        media_type="tv" if mt == "tv" else "movie",
                        season_number=parsed.get("season"),
                        episode_number=parsed.get("episode"),
                        episode_title=parsed.get("episode_title"),
                        library_visible=True,
                        catalog_excluded=no_catalog,
                    )
                    if no_catalog:
                        note = "\n\n<i>🚫 Not for watch channel — library browse only.</i>"
                    elif upload and not match:
                        schedule_watch_publish(context, upload.id, library_visible=True)
                if upload:
                    await _finish_pending_map_and_continue(
                        context,
                        chat_id=update.effective_chat.id,
                        success_text=(
                            f"✅ <b>Title saved</b>\n\n"
                            f"<code>{escape(upload.file_name)}</code>\n"
                            f"Title: <b>{escape(upload.confirmed_name or custom_name)}</b>{note}"
                        ),
                        file_id=file_id,
                    )
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Error confirming file: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            del context.user_data['pending_confirm_file_id']


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    error = context.error
    
    # Handle Conflict errors (409) - another bot instance is running
    if isinstance(error, Exception) and ("409" in str(error) or "Conflict" in str(error) or "terminated by other getUpdates" in str(error)):
        logger.error(
            "⚠️ CONFLICT ERROR: Another bot instance is running or webhook is active!\n"
            "This error means:\n"
            "1. Another instance of this bot is running (check other terminals/processes)\n"
            "2. A webhook is still active for this bot\n"
            "3. The bot was stopped incorrectly and Telegram still has pending updates\n\n"
            "Solutions:\n"
            "- Stop all other bot instances\n"
            "- Wait a few minutes for Telegram to clear the conflict\n"
            "- Or use webhooks instead of polling"
        )
        # Don't try to fix it automatically - it will just keep failing
        # The user needs to stop the other instance
        return
    
    if isinstance(error, BadRequest):
        if _is_stale_callback_error(error) or is_unchanged_message_error(error):
            logger.debug("Benign Telegram API response: %s", error)
        return

    from telegram.error import NetworkError, TimedOut

    if isinstance(error, (TimedOut, NetworkError)):
        logger.warning("Transient Telegram API error (update not lost): %s", error)
        return

    # Log other errors
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries for interactive buttons"""
    query = update.callback_query
    if not query:
        return

    data = query.data or ""
    # Upload start/stop answer in upload_features (alerts + queue feedback).
    defer_answer = data.startswith("up_job_run:") or data.startswith("up_job_stop:")
    query_fresh = True if defer_answer else await safe_answer_callback(query)

    if not query.data:
        return

    data = query.data
    user_id = query.from_user.id
    
    if await library_setup.handle_setup_callback(data, update, context, user_id):
        return

    if await vault_features.handle_vault_callback(data, update, context, user_id):
        return

    if await upload_features.handle_upload_callback(data, update, context, user_id):
        return

    if await watch_features.handle_watch_callback(data, update, context, user_id):
        return
    
    # Handle file confirmation — TMDB pick flow
    if data.startswith("confirm_file:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await safe_edit_message(query, "❌ You don't have permission to use this.")
            return
        if not query_fresh:
            await safe_edit_message(
                query,
                "⏱ This button expired.\n\nOpen <b>⏳ Pending</b> from /menu and tap the file again.",
            )
            return
        
        await safe_edit_message(
            query,
            "⏳ <b>Looking up TMDB…</b>\n\n<i>Please wait a few seconds.</i>",
            reply_markup=None,
        )
        session = db.get_session()
        try:
            file_upload = session.query(FileUpload).filter_by(id=file_id).first()
            if not file_upload:
                await reply_or_edit_query(query, context, "❌ File not found.")
                return
            fid = file_upload.id
            fname = file_upload.file_name
            pname = file_upload.parsed_name
        finally:
            session.close()
        _fire_interactive_job(
            context.application,
            f"TMDB pick file {fid}",
            lambda: _run_tmdb_pick_job(
                query, context, fid, file_name=fname, parsed_name=pname
            ),
        )
        return

    elif data.startswith("tpml:"):
        parts = data.split(":")
        if len(parts) < 3:
            await safe_answer_callback(query, "Invalid action", show_alert=True)
            return
        kind, ref_s = parts[1], parts[2]
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        await safe_answer_callback(query, "Loading more…")
        if kind == "g":
            gid = int(ref_s)
            meta = context.user_data.get(_bulk_meta_key(gid), {})
            q = (
                meta.get("pick_query")
                or meta.get("manual_search_query")
                or meta.get("search_name")
                or ""
            )
            if not q or not tmdb_helper.enabled:
                await safe_answer_callback(query, "No search query", show_alert=True)
                return
            page = int(meta.get("pick_page") or 1) + 1
            ft = meta.get("pick_filter") or "all"
            pick = await _fetch_tmdb_pick_page(
                q,
                media_type=meta.get("media_type") or "tv",
                parsed=meta.get("parsed"),
                page=page,
                filter_type=ft,
            )
            suggestions = list(context.user_data.get(_tmdb_sug_key_bulk(gid), []))
            new_items = pick.get("items") or []
            old_len = len(suggestions)
            suggestions.extend(new_items)
            context.user_data[_tmdb_sug_key_bulk(gid)] = suggestions
            meta["suggestions"] = suggestions
            meta["pick_page"] = page
            meta["pick_has_more"] = bool(pick.get("has_more"))
            context.user_data[_bulk_meta_key(gid)] = meta
            if new_items:
                await _send_tmdb_suggestion_cards(
                    query,
                    context,
                    new_items,
                    lambda i: f"tpb:{gid}:{i}",
                    match_key=str(gid),
                    start_index=old_len,
                    clear_existing=False,
                )
        elif kind == "f":
            file_id = int(ref_s)
            meta = context.user_data.get(f"tmdb_meta_{file_id}", {})
            q = (
                meta.get("pick_query")
                or meta.get("manual_search_query")
                or meta.get("search_name")
                or ""
            )
            if not q or not tmdb_helper.enabled:
                await safe_answer_callback(query, "No search query", show_alert=True)
                return
            page = int(meta.get("pick_page") or 1) + 1
            ft = meta.get("pick_filter") or "all"
            pick = await _fetch_tmdb_pick_page(
                q,
                media_type=meta.get("media_type") or "movie",
                parsed=meta.get("parsed"),
                page=page,
                filter_type=ft,
            )
            suggestions = list(context.user_data.get(_tmdb_sug_key(file_id), []))
            new_items = pick.get("items") or []
            old_len = len(suggestions)
            suggestions.extend(new_items)
            context.user_data[_tmdb_sug_key(file_id)] = suggestions
            meta["suggestions"] = suggestions
            meta["pick_page"] = page
            meta["pick_has_more"] = bool(pick.get("has_more"))
            context.user_data[f"tmdb_meta_{file_id}"] = meta
            if new_items:
                await _send_tmdb_suggestion_cards(
                    query,
                    context,
                    new_items,
                    lambda i: f"tmdb_pick:{file_id}:{i}",
                    file_id=file_id,
                    start_index=old_len,
                    clear_existing=False,
                )
        else:
            await safe_answer_callback(query, "Invalid action", show_alert=True)
        return

    elif data.startswith("tmdb_pick:"):
        _, file_id_s, idx_s = data.split(":", 2)
        file_id, idx = int(file_id_s), int(idx_s)
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        suggestions = context.user_data.get(_tmdb_sug_key(file_id), [])
        meta = context.user_data.get(f"tmdb_meta_{file_id}", {})
        if idx >= len(suggestions):
            await safe_answer_callback(query, "Suggestion not found", show_alert=True)
            return
        selection = suggestions[idx]
        upload = _apply_tmdb_selection(file_id, selection, meta)
        if upload:
            schedule_watch_publish(
                context, upload.id, library_visible=bool(selection.get("tmdb_id"))
            )
            context.user_data[f"tmdb_last_pick_{file_id}"] = selection
            await _finish_pending_map_and_continue(
                context,
                query=query,
                chat_id=query.message.chat_id,
                success_text=(
                    f"✅ <b>TMDB linked</b>\n\n"
                    f"<code>{escape(upload.file_name)}</code>\n"
                    f"Title: <b>{escape(upload.confirmed_name or '')}</b>"
                ),
                file_id=file_id,
            )
        else:
            await safe_edit_message(query, "❌ File not found.")

    elif data.startswith("tmdb_apply_siblings:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        selection = context.user_data.get(f"tmdb_last_pick_{file_id}")
        if not selection:
            await safe_answer_callback(query, "Link this file to TMDB first.", show_alert=True)
            return
        upload = db.get_file_upload(file_id)
        if not upload:
            await safe_edit_message(query, "❌ File not found.")
            return
        pending = db.get_pending_confirmations(limit=500)
        parsed = parser.parse_name(upload.file_name)
        sib_ids = sibling_pending_ids(
            pending,
            parser=parser,
            anchor_file_id=file_id,
            anchor_parsed=parsed,
            anchor_file_name=upload.file_name,
        )
        n = _apply_tmdb_bulk(sib_ids, selection)
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"✅ <b>Applied to {n} similar file(s)</b>\n\n"
                f"Same TMDB: <b>{escape(selection.get('title') or '')}</b>"
            ),
            file_id=file_id,
        )

    elif data.startswith("pg:") or data.startswith("pending_group:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref)
        if not match_key:
            await safe_edit_message(
                query,
                "⏱ Batch expired — open <b>/menu → Pending</b> again.",
            )
            return
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        if not query_fresh:
            await safe_edit_message(
                query,
                "⏱ Button expired — open <b>Pending</b> from /menu again.",
            )
            return
        await safe_edit_message(
            query,
            "⏳ <b>Looking up TMDB for batch…</b>",
            reply_markup=None,
        )
        _fire_interactive_job(
            context.application,
            f"TMDB batch {match_key[:32]}",
            lambda: _run_bulk_tmdb_pick_job(query, context, match_key),
        )
        return

    elif data.startswith("tpb:") or data.startswith("tmdb_pick_bulk:"):
        parts = data.split(":")
        if len(parts) < 3:
            await safe_answer_callback(query, "Invalid action", show_alert=True)
            return
        ref, idx_s = parts[1], parts[2]
        idx = int(idx_s)
        match_key = _resolve_bulk_ref(context, ref) or ref
        gid = ref if ref.isdigit() else None
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        meta_key = gid if gid is not None else match_key
        suggestions = context.user_data.get(_tmdb_sug_key_bulk(meta_key), [])
        meta = context.user_data.get(_bulk_meta_key(meta_key), {})
        file_ids = meta.get("bulk_file_ids") or []
        if idx >= len(suggestions) or not file_ids:
            await safe_answer_callback(query, "Suggestion not found", show_alert=True)
            return
        await safe_answer_callback(query, "Linking…")
        selection = suggestions[idx]
        try:
            n = await asyncio.to_thread(_apply_tmdb_bulk, file_ids, selection)
        except Exception as e:
            logger.error("Batch TMDB apply failed: %s", e, exc_info=True)
            await _finish_tmdb_pick_success(
                context,
                query.message.chat_id,
                f"❌ <b>Batch link failed</b>\n\n<code>{escape(str(e))}</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Pending", callback_data="pending_menu")]]
                ),
                match_key=str(meta_key),
            )
            return
        title = escape(selection.get("title") or "")
        note = ""
        if n > 0 and selection.get("tmdb_id") and tmdb_helper._last_api_error:
            note = (
                "\n<i>TMDB network glitch — files linked; metadata may be minimal. "
                "Retry from Browse if needed.</i>"
            )
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"✅ <b>Batch linked ({n} files)</b>\n\nTMDB: <b>{title}</b>{note}"
            ),
            match_key=str(meta_key),
        )

    elif data.startswith("bpp:") or data.startswith("bulk_parsed:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        show_name = group.get("show_name") or "Series"
        mt = group.get("media_type") or "tv"
        n = _apply_parsed_bulk(group["file_ids"], show_name, media_type=mt)
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"✅ <b>Saved {n} file(s)</b> as <b>{escape(show_name)}</b>\n\n"
                "<i>Not linked to TMDB — won’t appear in library browse until TMDB is set.</i>"
            ),
            match_key=str(group.get("group_id", ref)),
        )

    elif data.startswith("bts:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        if not tmdb_helper.enabled:
            await safe_edit_message(query, "TMDB is not configured.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        context.user_data["bulk_tmdb_search_match_key"] = match_key
        _remember_tmdb_pick_header(
            query,
            context,
            match_key=_bulk_tmdb_header_match_key(context, match_key),
        )
        n = len(group["file_ids"])
        show = escape(group.get("show_name") or "Batch")
        preview = _format_batch_files_preview(group)
        await safe_edit_message(
            query,
            "🔍 <b>Search TMDB (batch)</b>\n\n"
            f"<b>Mapping:</b> {show} · <b>{n}</b> file(s)\n\n"
            f"<b>Files in batch:</b>\n{preview}\n\n"
            "Send the <b>title to search</b> on TMDB — not the full filename.\n"
            "Example: <code>Boundless</code> or <code>Fight Club</code>",
            reply_markup=None,
        )
        return

    elif data.startswith("tsi:"):
        file_id = int(data.split(":", 1)[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        if not tmdb_helper.enabled:
            await safe_edit_message(query, "TMDB is not configured.")
            return
        upload = db.get_file_upload(file_id)
        if not upload:
            await safe_edit_message(query, "❌ File not found — open Pending again.")
            return
        context.user_data["pending_tmdb_search_file_id"] = file_id
        _remember_tmdb_pick_header(query, context, file_id=file_id)
        fname = escape(_truncate_for_telegram(upload.file_name, 200))
        await safe_edit_message(
            query,
            f"🔍 <b>Search TMDB</b> (file #{file_id})\n\n"
            f"<b>Mapping:</b>\n• <code>{fname}</code>\n\n"
            "Send the <b>title to search</b> on TMDB — not the full filename.\n"
            "Example: <code>Fight Club</code>",
            reply_markup=None,
        )
        return

    elif data.startswith("bdf:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        n = db.defer_pending_files(group["file_ids"])
        label = escape(group.get("show_name") or "Batch")
        await safe_answer_callback(query, "Skipped")
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"⏭ <b>Skipped for now</b> — <b>{n}</b> file(s)\n\n"
                f"<b>{label}</b> moved to the end of Pending."
            ),
            match_key=str(ref),
        )
        return

    elif data.startswith("dfr:"):
        file_id = int(data.split(":", 1)[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        n = db.defer_pending_files([file_id])
        if not n:
            await safe_edit_message(query, "❌ File not found or already confirmed.")
            return
        await safe_answer_callback(query, "Skipped")
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"⏭ <b>Skipped for now</b> (file #{file_id})\n\n"
                "Moved to the end of Pending."
            ),
            file_id=file_id,
        )
        return

    elif data.startswith("bpc:") or data.startswith("bulk_custom:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        context.user_data["bulk_custom_match_key"] = match_key
        n = len(group["file_ids"])
        await safe_edit_message(
            query,
            f"✏️ <b>Custom title for batch ({n} files)</b>\n\n"
            f"Send the <b>show or movie name</b> (e.g. <code>{escape(group.get('show_name') or 'Dhahanam')}</code>).\n"
            "Episode numbers stay from each filename.",
            reply_markup=None,
        )

    elif data.startswith("brt:") or data.startswith("tmdb_retry_bulk:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        await safe_edit_message(query, "⏳ <b>Retrying TMDB…</b>", reply_markup=None)
        _fire_interactive_job(
            context.application,
            f"TMDB batch retry {match_key[:32]}",
            lambda: _run_bulk_tmdb_pick_job(query, context, match_key),
        )
        return

    elif data.startswith("tmdb_detected:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        meta = context.user_data.get(f"tmdb_meta_{file_id}", {})
        suggestions = gather_tmdb_suggestions(meta, tmdb_helper=tmdb_helper, db=db)
        context.user_data[_tmdb_sug_key(file_id)] = suggestions
        show_name = meta.get("local_name") or (meta.get("parsed") or {}).get("show_name")
        upload = None
        if suggestions:
            match = tmdb_helper.pick_best_match(suggestions, show_name or "", media_type="tv")
            if match:
                upload = _apply_tmdb_selection(file_id, match, meta)
                if upload:
                    schedule_watch_publish(
                        context, upload.id, library_visible=bool(match.get("tmdb_id"))
                    )
        if not upload and show_name:
            parsed = meta.get("parsed") or {}
            display = episode_display_name(
                show_name,
                parsed.get("season"),
                parsed.get("episode"),
                parsed.get("episode_title"),
            )
            upload = db.apply_tmdb_pick(
                file_id,
                local_name=show_name,
                parsed_name=display,
                media_type="tv",
                season_number=parsed.get("season"),
                episode_number=parsed.get("episode"),
                episode_title=parsed.get("episode_title"),
                library_visible=False,
            )
        if upload:
            await _finish_pending_map_and_continue(
                context,
                query=query,
                chat_id=query.message.chat_id,
                success_text=(
                    f"✅ <b>Title saved</b>\n\n"
                    f"<code>{escape(upload.file_name)}</code>\n"
                    f"<b>{escape(upload.confirmed_name or '')}</b>"
                ),
                file_id=file_id,
            )
        else:
            await safe_edit_message(query, "❌ Could not save title.")

    elif data.startswith("tmdb_retry:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        await safe_edit_message(
            query,
            "⏳ <b>Retrying TMDB search…</b>",
            reply_markup=None,
        )
        session = db.get_session()
        try:
            file_upload = session.query(FileUpload).filter_by(id=file_id).first()
            if not file_upload:
                await reply_or_edit_query(query, context, "❌ File not found.")
                return
            fid, fname, pname = file_upload.id, file_upload.file_name, file_upload.parsed_name
        finally:
            session.close()
        _fire_interactive_job(
            context.application,
            f"TMDB retry file {fid}",
            lambda: _run_tmdb_pick_job(
                query, context, fid, file_name=fname, parsed_name=pname
            ),
        )
        return
    
    elif data.startswith("skip_catalog:"):
        file_id = int(data.split(":", 1)[1])
        if not is_admin(user_id):
            await safe_edit_message(query, "❌ You don't have permission.")
            return
        upload = _apply_skip_catalog_file(file_id, library_only=False)
        if upload:
            await _finish_pending_map_and_continue(
                context,
                query=query,
                chat_id=query.message.chat_id,
                success_text=(
                    f"✅ <b>Skipped watch catalog</b>\n\n"
                    f"<code>{escape(upload.file_name)}</code>\n"
                    f"Grouped as: <b>{escape(upload.confirmed_name or '?')}</b>\n\n"
                    "<i>Indexed only — not in library browse or watch channel.</i>"
                ),
                file_id=file_id,
            )
        else:
            await safe_edit_message(query, "❌ File not found.")
        return

    elif data.startswith("scb:") or data.startswith("skip_catalog_bulk:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await safe_edit_message(query, "❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        n = _apply_skip_catalog_bulk(group["file_ids"], library_only=False)
        await _finish_pending_map_and_continue(
            context,
            query=query,
            chat_id=query.message.chat_id,
            success_text=(
                f"✅ <b>Skipped watch catalog ({n} files)</b>\n\n"
                "<i>Indexed only — not in library browse or watch channel.</i>"
            ),
            match_key=str(group.get("group_id", ref)),
        )
        return

    elif data.startswith("confirm_custom_nc:"):
        file_id = int(data.split(":", 1)[1])
        if not is_admin(user_id):
            await safe_edit_message(query, "❌ You don't have permission.")
            return
        context.user_data["pending_confirm_file_id"] = file_id
        context.user_data["pending_custom_no_catalog"] = True
        meta = context.user_data.get(f"tmdb_meta_{file_id}", {})
        parsed = meta.get("parsed") or {}
        hint = ""
        if meta.get("media_type") == "tv" and parsed.get("season") is not None:
            hint = (
                f"\n\nSeason <b>{parsed['season']}</b> and episode are taken from the filename."
            )
        await safe_edit_message(
            query,
            f"📚 <b>Custom title (library only)</b>\n\n"
            f"Send the show or movie name.\n"
            f"<i>No watch-channel poster card will be published.</i>{hint}",
            reply_markup=None,
        )
        return

    elif data.startswith("bpn:") or data.startswith("bulk_custom_nc:"):
        ref = data.split(":", 1)[1]
        match_key = _resolve_bulk_ref(context, ref) or ref
        if not is_admin(user_id):
            await safe_edit_message(query, "❌ You don't have permission.")
            return
        group = _resolve_pending_group(context, match_key)
        if not group:
            await safe_edit_message(query, "Batch not found — open Pending again.")
            return
        context.user_data["bulk_custom_match_key"] = match_key
        context.user_data["bulk_custom_no_catalog"] = True
        n = len(group["file_ids"])
        await safe_edit_message(
            query,
            f"📚 <b>Custom title — no watch card ({n} files)</b>\n\n"
            "Send the <b>show or movie name</b>.\n"
            "<i>Files stay in library browse; never published to the watch channel.</i>",
            reply_markup=None,
        )
        return

    # Enter custom name (prompt user)
    elif data.startswith("confirm_custom:"):
        file_id = int(data.split(":", 1)[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        
        context.user_data["pending_confirm_file_id"] = file_id
        context.user_data.pop("pending_custom_no_catalog", None)
        meta = context.user_data.get(f"tmdb_meta_{file_id}", {})
        parsed = meta.get("parsed") or {}
        hint = ""
        if meta.get("media_type") == "tv" and parsed.get("season") is not None:
            hint = (
                f"\n\nSeason <b>{parsed['season']}</b> and episode are taken from the filename."
            )
        await query.edit_message_text(
            f"✏️ <b>Enter show or movie title</b>\n\n"
            f"File ID: {file_id}\n"
            f"Example: <code>Billions</code> (not the full episode name).\n"
            f"<i>May publish a watch-channel card if TMDB matches.</i>{hint}",
            parse_mode=ParseMode.HTML,
        )
    
    # Select channel for operations
    elif data.startswith("select_channel:"):
        channel_id = data.split(":")[1]
        operation = data.split(":")[2] if ":" in data.split(":")[2:] else "view"
        
        channel = db.get_channel(channel_id)
        if channel:
            if operation == "view":
                # Show channel index
                results = db.search_files_in_channels("", [channel_id])
                if results:
                    grouped = {}
                    for result in results:
                        name = result.confirmed_name or result.parsed_name or result.file_name
                        if name not in grouped:
                            grouped[name] = []
                        grouped[name].append(result)
                    
                    message = f"📺 **Channel Index: {channel.channel_title}**\n\n"
                    message += f"📊 Total Files: {len(results)}\n"
                    message += f"🎬 Unique Movies/Series: {len(grouped)}\n\n"
                    
                    store_title_pick_list(context, list(grouped.keys())[:20])
                    keyboard = build_title_pick_rows(grouped, max_items=20)
                    keyboard.append(
                        [InlineKeyboardButton("« Channels", callback_data="channels_menu")]
                    )
                    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
                else:
                    await query.edit_message_text(
                        "📭 No files indexed from this channel yet.",
                        reply_markup=InlineKeyboardMarkup(
                            [[InlineKeyboardButton("« Channels", callback_data="channels_menu")]]
                        ),
                    )
    
    elif data.startswith("title_pick:"):
        try:
            idx = int(data.split(":", 1)[1])
        except (IndexError, ValueError):
            await query.answer("Invalid selection", show_alert=True)
            return
        movie_name = resolve_title_pick(context, idx)
        if not movie_name:
            await query.answer("List expired — open channel index or search again", show_alert=True)
            return
        uploads = db.get_library_view(movie_name)
        if uploads:
            text = build_library_message(movie_name)
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("« Browse", callback_data="library_browse")],
                        [InlineKeyboardButton("« Channels", callback_data="channels_menu")],
                    ]
                ),
            )
        else:
            await query.edit_message_text(
                f"❌ No library information found for '{escape(movie_name)}'",
                parse_mode=ParseMode.HTML,
            )

    # Cancel operation
    elif data == "cancel":
        await query.edit_message_text("❌ Operation cancelled.")

    elif data == "noop":
        await query.answer()

    elif data == "main_menu":
        await send_main_menu(update, context, edit=True)

    elif data == "library_browse":
        await send_library_browse_menu(update, context, edit=True)

    elif data == "library_all":
        await send_library_browse_menu(update, context, all_channels=True, edit=True)

    elif data == "lists_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_lists_menu(update, context, edit=True)

    elif data == "search_menu":
        await send_search_menu(update, context, edit=True)

    elif data.startswith("list_idx:"):
        idx = int(data.split(":", 1)[1])
        names = context.user_data.get("list_names", [])
        if idx < len(names):
            await send_library_browse_menu(update, context, list_name=names[idx], edit=True)
        else:
            await query.answer("List not found", show_alert=True)

    elif data.startswith("lib_idx:"):
        idx = int(data.split(":", 1)[1])
        await send_title_hub(query, context, idx)

    elif data.startswith("lib_details:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        idx = int(data.split(":", 1)[1])
        titles = context.user_data.get("browse_titles", [])
        if idx >= len(titles):
            await query.answer("Title not found", show_alert=True)
            return
        movie_name = _browse_entry_title(titles[idx])
        list_name = context.user_data.get("browse_list")
        channel_ids = db.get_channels_for_list(list_name) if list_name else None
        text = build_library_message(movie_name, channel_ids)
        rows = [
            [InlineKeyboardButton("▶ Watch", callback_data=f"watch_title:{idx}")],
            [InlineKeyboardButton("« Title", callback_data=f"lib_idx:{idx}")],
            [InlineKeyboardButton("« Main menu", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(rows)
        )

    elif data.startswith("watch_title:"):
        idx = int(data.split(":", 1)[1])
        await send_watch_title(query, context, idx)

    elif data.startswith("watch_ep:"):
        parts = data.split(":")
        if len(parts) < 4:
            await query.answer("Invalid episode", show_alert=True)
            return
        ct_id = int(parts[1])
        season, episode = parse_ep_callback_parts(int(parts[2]), int(parts[3]))
        list_name = context.user_data.get("browse_list")
        channel_ids = db.get_channels_for_list(list_name) if list_name else None
        slot_season = context.user_data.get("watch_slot_season")
        uploads = db.get_library_uploads_for_content(
            ct_id, channel_ids, season_number=slot_season
        )
        media_uploads = filter_watchable_media_uploads(uploads)
        context.user_data["watch_episode_keys"] = [
            ep_key for ep_key, _ in group_tv_episodes(media_uploads)
        ]
        context.user_data["watch_ep_ct_id"] = ct_id
        ep_uploads = [
            u
            for u in media_uploads
            if (u.season_number, u.episode_number) == (season, episode)
        ]
        if not ep_uploads:
            await query.answer("Episode not found", show_alert=True)
            return
        ep_uploads = await _verify_uploads_for_watch(query, ep_uploads)
        if not ep_uploads:
            await query.answer("This episode was removed from the channel", show_alert=True)
            return
        idx = context.user_data.get("watch_browse_idx")
        await send_watch_quality_list(
            query,
            context,
            idx=idx,
            ct_id=ct_id,
            uploads=ep_uploads,
            season=season,
            episode=episode,
            back_cb=f"watch_title:{idx}" if idx is not None else None,
            back_label="« Episodes",
        )

    elif data.startswith("watch_all:"):
        ct_id = int(data.split(":", 1)[1])
        await send_all_episodes(query, context, ct_id)

    elif data.startswith("watch_pick:"):
        upload_id = int(data.split(":", 1)[1])
        await send_watch_pick(query, context, upload_id)

    elif data.startswith("remap_title:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        idx = int(data.split(":")[1])
        titles = context.user_data.get("browse_titles", [])
        if idx >= len(titles):
            await query.answer("Title not found", show_alert=True)
            return
        movie_name = _browse_entry_title(titles[idx])
        list_name = context.user_data.get("browse_list")
        channel_ids = db.get_channels_for_list(list_name) if list_name else None
        back_cb = f"lib_idx:{idx}"
        context.user_data["remap_back_cb"] = back_cb
        context.user_data["remap_back_label"] = "« Back to title"
        await send_remap_files_menu(
            query,
            context,
            movie_name,
            channel_ids=channel_ids,
            back_cb=back_cb,
            back_label="« Back to title",
        )

    elif data.startswith("remap_tmdb:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        upload = db.get_file_upload(file_id)
        if not upload:
            await reply_or_edit_query(query, context, "❌ File not found.")
            return
        await safe_edit_message(
            query,
            "⏳ <b>Loading TMDB options…</b>",
            reply_markup=None,
        )
        _fire_interactive_job(
            context.application,
            f"TMDB remap file {file_id}",
            lambda: _run_tmdb_pick_job(
                query,
                context,
                file_id,
                file_name=upload.file_name,
                parsed_name=upload.confirmed_name or upload.parsed_name,
                remap=True,
            )
        )
        return

    elif data == "pending_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_pending_menu(update, context, page=0, edit=True)

    elif data == "pending_retry_all":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await query.answer()
        await run_retry_all_pending_tmdb(update, context, edit=True)

    elif data == "pending_retry_stop":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        if request_tmdb_bulk_retry_stop(context.application):
            await query.answer("Stopping after current file…")
        else:
            await query.answer("No TMDB retry is running.", show_alert=True)

    elif data.startswith("pending_page:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        page = int(data.split(":", 1)[1])
        batch_page = int(context.user_data.get("pending_batch_page", 0))
        await send_pending_menu(
            update, context, page=page, batch_page=batch_page, edit=True
        )

    elif data.startswith("pending_batch_page:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        parts = data.split(":")
        batch_page = int(parts[1])
        singles_page = int(parts[2]) if len(parts) > 2 else 0
        await send_pending_menu(
            update,
            context,
            page=singles_page,
            batch_page=batch_page,
            edit=True,
        )

    elif data == "channels_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_channels_menu(update, context, edit=True)

    elif data == "chpick_search":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        context.user_data["awaiting_channel_search"] = "channels"
        await query.answer()
        await safe_edit_message(
            query,
            "🔍 <b>Search connected channels</b>\n\n"
            "Reply with part of the channel name or @username.",
        )

    elif data.startswith("chpick_page:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        from channel_picker import parse_picker_page_callback

        parsed = parse_picker_page_callback(data, "chpick")
        if not parsed:
            return
        page, q = parsed
        await send_channels_picker(update, context, page=page, query=q, edit=True)

    elif data == "unavailable_posts_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_unavailable_posts_menu(update, context, edit=True)

    elif data == "verify_posts_run":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await run_verify_posts_sweep(update, context, edit=True)

    elif data == "tracking_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_tracking_menu(update, context, edit=True)

    elif data.startswith("tracking_page:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        parts = data.split(":")
        page = int(parts[1])
        filt = parts[2] if len(parts) > 2 else "all"
        comp = parts[3] if len(parts) > 3 else context.user_data.get("tracking_completion", "all")
        await send_tracking_menu(
            update, context, page=page, filter_kind=filt, completion=comp, edit=True
        )

    elif data.startswith("tracking_filter:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        parts = data.split(":")
        filt = parts[1] if len(parts) > 1 else "all"
        comp = parts[2] if len(parts) > 2 else "all"
        await send_tracking_menu(
            update, context, page=0, filter_kind=filt, completion=comp, edit=True
        )

    elif data.startswith("tracking_tv:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        ct_id = int(data.split(":", 1)[1])
        await send_tracking_tv_detail(query, context, ct_id)

    elif data.startswith("tracking_col:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        coll_id = int(data.split(":", 1)[1])
        await send_tracking_collection_detail(query, context, coll_id)

    elif data.startswith("tracking_mp:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        ct_id = int(data.split(":", 1)[1])
        await send_tracking_multipart_detail(query, context, ct_id)

    elif data == "discover_channels_run":
        await run_channel_discovery(update, context, edit=True)

    elif data == "backfill_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_backfill_guide(update, context, edit=True)

    elif data == "set_ingest_channel_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        back = "setup_hub" if context.user_data.get("setup_return") else "backfill_menu"
        await send_set_ingest_channel_menu(
            update, context, edit=True, back_callback=back
        )

    elif data == "backfill_start_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_start_backfill_menu(update, context, edit=True)

    elif data == "bfch_search":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        context.user_data["awaiting_channel_search"] = "backfill"
        await query.answer()
        await safe_edit_message(
            query,
            "🔍 <b>Search source channels</b>\n\n"
            "Reply with part of the channel name or @username.",
        )

    elif data.startswith("bfch_page:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        from channel_picker import parse_picker_page_callback

        parsed = parse_picker_page_callback(data, "bfch")
        if not parsed:
            return
        page, q = parsed
        await send_backfill_source_picker(
            update, context, page=page, query=q, edit=True
        )

    elif data.startswith("backfill_pick:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        channel_id = data.split(":", 1)[1]
        source = db.get_channel(channel_id)
        if source:
            await safe_answer_callback(
                query,
                f"Selected: {source.channel_title or channel_id}",
            )
        await safe_edit_message(
            query,
            "⏳ <b>Loading source channel…</b>\n\n"
            "<i>Preparing dry run / start options.</i>",
        )
        await send_backfill_confirm(update, context, channel_id, edit=True)

    elif data.startswith("backfill_run:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        parts = data.split(":")
        if len(parts) < 3:
            await query.answer("Invalid action", show_alert=True)
            return
        channel_id = parts[1]
        mode = parts[2]
        await run_historical_ingest(
            update,
            context,
            channel_id,
            dry_run=(mode == "dry"),
            skip_duplicates=(mode == "live_skip"),
            edit=True,
        )

    elif data.startswith("set_ingest_channel:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        channel_id = data.split(":", 1)[1]
        channel = db.set_ingest_channel(channel_id)
        if channel:
            await query.answer("✅ Ingest channel saved")
            if context.user_data.get("setup_return") == "setup_hub":
                await library_setup.send_library_setup_hub(update, context, edit=True)
            else:
                await send_backfill_guide(update, context, edit=True)
        else:
            await query.answer("❌ Channel not found", show_alert=True)

    elif data == "add_channel_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_add_channel_menu(update, context, edit=True)

    elif data == "remove_channel_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await send_remove_channel_menu(update, context, edit=True)

    elif data == "channel_index_menu":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        channels = db.get_all_channels()
        if not channels:
            await query.edit_message_text(
                "📭 No channels available.",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Back", callback_data="channels_menu")]]
                ),
            )
            return
        keyboard = [
            [
                InlineKeyboardButton(
                    f"📺 {channel_button_label(ch)}",
                    callback_data=f"select_channel:{ch.channel_id}:view",
                )
            ]
            for ch in channels
        ]
        keyboard.append([InlineKeyboardButton("« Back", callback_data="channels_menu")])
        await query.edit_message_text(
            "<b>📂 Channel index</b>\n\nTap a channel:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )

    elif data == "create_list_start":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        context.user_data["awaiting_list_name"] = True
        await query.edit_message_text(
            "<b>📋 New custom list</b>\n\n"
            "Send the list name in your next message (e.g. <code>MyMovies</code>).",
            parse_mode=ParseMode.HTML,
        )

    elif data == "add_channel_username_prompt":
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        context.user_data["awaiting_add_channel_username"] = True
        await query.edit_message_text(
            "<b>✏️ Register by @username</b>\n\n"
            "Send the channel username (e.g. <code>@MyChannel</code>).\n"
            "The bot must already be an <b>admin</b> there.",
            parse_mode=ParseMode.HTML,
        )

    elif data.startswith("add_channel_activate:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        channel_id = data.split(":", 1)[1]
        channel = db.set_channel_active(channel_id, True)
        if channel:
            await query.answer("✅ Channel restored")
            await send_channels_menu(update, context, edit=True)
        else:
            await query.answer("❌ Channel not found", show_alert=True)

    elif data.startswith("remove_channel_do:"):
        if not is_admin(user_id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        channel_id = data.split(":", 1)[1]
        channel = db.set_channel_active(channel_id, False)
        if channel:
            name = channel_button_label(channel)
            await query.edit_message_text(
                f"✅ Stopped monitoring:\n<b>{escape(name)}</b>\n\n"
                "Indexed files are kept. Use /channels to restore.",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Channels", callback_data="channels_menu")]]
                ),
            )
        else:
            await query.answer("❌ Channel not found", show_alert=True)

    elif data.startswith("channel_info:"):
        channel_id = data.split(":", 1)[1]
        channel = db.get_channel(channel_id)
        if not channel:
            await query.answer("Channel not found", show_alert=True)
            return
        uploads = db.get_channel_upload_count(
            channel_id, is_ingest=getattr(channel, "is_ingest_channel", False)
        )
        st = db.get_channel_index_stats().get(str(channel_id), {})
        live_n = st.get("live", 0)
        backfill_n = st.get("backfill", 0)
        username = f"@{channel.channel_username}" if channel.channel_username else "—"
        status = "✅ Active" if channel.is_active else "⏸ Inactive"
        status_block = channel_status_lines(
            channel,
            live_count=live_n,
            backfill_count=backfill_n,
            historical_ingested_at=getattr(channel, "historical_ingested_at", None),
        )
        from content_lanes import LANE_LABELS, normalize_lane

        lane = normalize_lane(getattr(channel, "content_lane", None))
        text = (
            f"<b>{escape(channel.channel_title or 'Unknown')}</b>\n\n"
            f"Username: <code>{escape(username)}</code>\n"
            f"ID: <code>{escape(channel.channel_id)}</code>\n"
            f"Status: {status}\n"
            f"Staging default: <b>{escape(LANE_LABELS.get(lane, lane))}</b> "
            f"<i>(optional — only if channel is single-type uploads)</i>\n"
            f"Indexed files (display count): <b>{uploads}</b>\n\n"
            + "\n".join(status_block)
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "📂 View index",
                    callback_data=f"select_channel:{channel_id}:view",
                )
            ],
        ]
        if is_admin(user_id):
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "⚙️ Staging default",
                        callback_data=f"setup_lane_ch:{channel_id}",
                    )
                ]
            )
            if not getattr(channel, "is_ingest_channel", False):
                if db.get_ingest_channel():
                    keyboard.append(
                        [
                            InlineKeyboardButton(
                                "▶️ Start historical ingestion",
                                callback_data=f"backfill_pick:{channel_id}",
                            )
                        ]
                    )
            if channel.is_active:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "➖ Stop monitoring",
                            callback_data=f"remove_channel_do:{channel_id}",
                        )
                    ]
                )
            else:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            "➕ Restore monitoring",
                            callback_data=f"add_channel_activate:{channel_id}",
                        )
                    ]
                )
        keyboard.append([InlineKeyboardButton("« Back", callback_data="channels_menu")])
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    
    # Toggle channel for list creation
    elif data.startswith("toggle_list_channel:"):
        parts = data.split(":")
        channel_id = parts[1]
        list_name = parts[2] if len(parts) > 2 else None
        
        # Initialize selected channels for this list
        key = f'selected_channels_{list_name}'
        if key not in context.user_data:
            context.user_data[key] = []
        
        # Toggle selection
        if channel_id in context.user_data[key]:
            context.user_data[key].remove(channel_id)
            await query.answer("❌ Removed from selection")
        else:
            context.user_data[key].append(channel_id)
            await query.answer("✅ Added to selection")
        
        channels = db.get_all_channels()
        selected = context.user_data.get(key, [])
        message = (
            f"<b>📋 Create list: {escape(list_name)}</b>\n\n"
            f"Selected: <b>{len(selected)}</b> channel(s)\n"
            "Tap channels to toggle:"
        )
        keyboard = []
        for channel in channels:
            is_selected = str(channel.channel_id) in selected
            prefix = "✅ " if is_selected else "📺 "
            keyboard.append(
                [
                InlineKeyboardButton(
                        f"{prefix}{channel_button_label(channel)}",
                        callback_data=f"toggle_list_channel:{channel.channel_id}:{list_name}",
                    )
                ]
            )
        keyboard.append(
            [
                InlineKeyboardButton("✅ Create list", callback_data=f"create_list_final:{list_name}"),
                InlineKeyboardButton("❌ Cancel", callback_data="channels_menu"),
            ]
        )
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.HTML,
        )
    
    # Finalize list creation
    elif data.startswith("create_list_final:"):
        list_name = data.split(":", 1)[1]
        key = f'selected_channels_{list_name}'
        selected_channels = context.user_data.get(key, [])
        
        if not selected_channels:
            await query.edit_message_text("❌ Please select at least one channel.")
            return
        
        try:
            custom_list = db.create_custom_list(list_name, selected_channels, user_id)
            if custom_list:
                # Get channel info
                channel_info = []
                for channel_id in selected_channels:
                    channel = db.get_channel(channel_id)
                    if channel:
                        username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel_id}"
                        channel_info.append(f"• {channel.channel_title or 'Unknown'} ({username})")
                
                channels_text = '\n'.join(channel_info)
                await query.edit_message_text(
                    f"✅ **List '{list_name}' created successfully!**\n\n"
                    f"**Channels in list:**\n{channels_text}\n\n"
                    f"Use: /search <name> --list {list_name}\n"
                    f"Or: /library <name> --list {list_name}",
                    parse_mode='Markdown'
                )
                # Clean up
                del context.user_data[key]
            else:
                await query.edit_message_text(f"❌ List '{list_name}' already exists.")
        except Exception as e:
            logger.error(f"Error creating list: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")


_BOT_PIDFILE = Path(__file__).resolve().parent / ".bot.pid"


def _acquire_single_instance_lock() -> bool:
    """Refuse to start if another Index_bot process is already polling."""
    if _BOT_PIDFILE.exists():
        try:
            old_pid = int(_BOT_PIDFILE.read_text().strip())
            os.kill(old_pid, 0)
            logger.error(
                "Index_bot is already running (PID %s).\n"
                "Stop it first: ./stop_bot.sh",
                old_pid,
            )
            return False
        except (OSError, ValueError):
            _BOT_PIDFILE.unlink(missing_ok=True)

    _BOT_PIDFILE.write_text(str(os.getpid()))

    def _release() -> None:
        try:
            if _BOT_PIDFILE.exists() and int(_BOT_PIDFILE.read_text().strip()) == os.getpid():
                _BOT_PIDFILE.unlink()
        except (OSError, ValueError):
            _BOT_PIDFILE.unlink(missing_ok=True)

    atexit.register(_release)
    return True


async def post_init(application: Application) -> None:
    """Post-initialization hook to clear pending updates and check for conflicts"""
    await start_job_queue(application)
    from telethon_gateway import start_telethon_gateway

    await start_telethon_gateway()
    from channel_member_watch import start_member_watch_worker

    start_member_watch_worker(application)
    cleared = db.clear_pending_tmdb_retry_schedules()
    if cleared:
        logger.info("Cleared %s stale TMDB retry schedule(s) on startup", cleared)
    dismissed = db.auto_confirm_non_tmdb_pending()
    if dismissed:
        logger.info("Auto-confirmed %s image/GIF pending upload(s)", dismissed)
    bot = application.bot
    try:
        # First, delete any webhook
        logger.info("Checking webhook status...")
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.warning(f"⚠️ Webhook is active at: {webhook_info.url}")
            logger.info("Deleting webhook to enable polling...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook deleted")
        else:
            logger.info("✅ No webhook found, using polling mode")
            # Clear pending updates
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Pending updates cleared")
    except Exception as e:
        logger.warning(f"Could not check/clear webhook: {e}")
        logger.warning("⚠️ If you see 409 Conflict errors, make sure no other bot instance is running")


async def post_shutdown(application: Application) -> None:
    from channel_member_watch import stop_member_watch_worker
    from telethon_gateway import stop_telethon_gateway

    await stop_member_watch_worker()
    await stop_telethon_gateway()


def main():
    """Main function to run the bot"""
    if not _acquire_single_instance_lock():
        sys.exit(1)

    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return
    
    # Create application with post_init hook
    application = (
        Application.builder()
        .token(Config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .concurrent_updates(8)
        .build()
    )

    db_url = Config.DATABASE_URL or f"sqlite:///{Config.DB_PATH}"
    logger.info("Database: %s", db_url.split("@")[-1] if "@" in db_url else db_url)
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", lambda u, c: send_main_menu(u, c)))
    application.add_handler(CommandHandler("tracking", tracking_cmd))
    application.add_handler(CommandHandler("watch", watch_cmd))
    application.add_handler(CommandHandler("favorites", favorites_cmd))
    application.add_handler(CommandHandler("watchlist", watchlist_cmd))
    application.add_handler(CommandHandler("portal", portal_cmd))
    application.add_handler(CommandHandler("request", request_cmd))
    application.add_handler(CommandHandler("help", watch_help_cmd))
    application.add_handler(CommandHandler("channels", channels))
    application.add_handler(CommandHandler("discover_channels", discover_channels_cmd))
    application.add_handler(CommandHandler("add_channel", add_channel))
    application.add_handler(CommandHandler("remove_channel", remove_channel))
    application.add_handler(CommandHandler("list_channels", list_channels))
    application.add_handler(CommandHandler("backfill", backfill_channel))
    application.add_handler(CommandHandler("start_backfill", start_backfill_cmd))
    application.add_handler(CommandHandler("set_ingest_channel", set_ingest_channel_cmd))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("library", library))
    application.add_handler(CommandHandler("channel_index", channel_index))
    application.add_handler(CommandHandler("lists", list_lists))
    application.add_handler(CommandHandler("create_list", create_list))
    application.add_handler(CommandHandler("delete_list", delete_list))
    application.add_handler(CommandHandler("pending", pending))
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("test_tmdb", test_tmdb))
    application.add_handler(CommandHandler("test_channel_detection", test_channel_detection))
    application.add_handler(CallbackQueryHandler(callback_handler))

    # Detect bot added/removed as admin (registers channel without needing a new post)
    application.add_handler(
        ChatMemberHandler(handle_my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    
    # Handle channel messages
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_message))

    # Admin: forward a channel post to register that channel
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE & filters.FORWARDED,
            handle_forwarded_channel,
        )
    )
    
    # Handle text messages (for custom name input)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("=" * 60)
    logger.info("🚀 Bot starting...")
    logger.info("=" * 60)
    logger.info("⚠️  IMPORTANT: Make sure no other bot instance is running!")
    logger.info("   If you see 409 Conflict errors, stop other instances first.")
    logger.info("   Use: ./stop_bot.sh (this project) or ./stop_all_bots.sh")
    logger.info("=" * 60)
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
    except KeyboardInterrupt:
        logger.info("✅ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Error running bot: {e}")
        if "Conflict" in str(e) or "409" in str(e):
            logger.error("\n" + "=" * 60)
            logger.error("🚨 409 CONFLICT ERROR DETECTED!")
            logger.error("=" * 60)
            logger.error("Another bot instance is running. Please:")
            logger.error("1. Stop all other bot instances: ./stop_all_bots.sh")
            logger.error("2. Wait a few seconds")
            logger.error("3. Try starting again")
            logger.error("=" * 60)
        raise


if __name__ == '__main__':
    main()
