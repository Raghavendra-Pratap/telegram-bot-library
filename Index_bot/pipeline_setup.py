"""
Upload pipeline defaults: one-time mapping of upload type → source channel.

Source channel = where files are uploaded (Telegram messages live; used for playback/indexing).
This is NOT the watch library publish channel (see watch_for_lane / catalog publish).
"""
from __future__ import annotations

from content_lanes import (
    LANE_ADULT,
    LANE_ARCHIVE,
    LANE_COURSE,
    LANE_MEDIA,
    LANE_SHORTFORM,
    normalize_lane,
)

# Upload types exposed in pipeline setup UI (keys match content_lane on jobs).
PIPELINE_UPLOAD_TYPES: tuple[tuple[str, str], ...] = (
    (LANE_MEDIA, "🎬 Movie / Series"),
    (LANE_COURSE, "🎓 Course"),
    (LANE_ADULT, "🔒 Adult"),
    (LANE_ARCHIVE, "📦 Archive"),
    (LANE_SHORTFORM, "📱 Shortform"),
    ("mixed", "🗂️ Mixed / dump (ingest sink)"),
)

PIPELINE_SOURCE_LANES = frozenset(
    {LANE_MEDIA, LANE_COURSE, LANE_ADULT, LANE_ARCHIVE, LANE_SHORTFORM, "mixed"}
)


def normalize_upload_type(upload_type: str | None) -> str:
    ut = (upload_type or LANE_MEDIA).strip().lower()
    if ut == "mixed":
        return "mixed"
    return normalize_lane(ut)


def upload_type_supports_catalog_publish(upload_type: str) -> bool:
    """Only media uses the watch-library TMDB card channel."""
    return normalize_upload_type(upload_type) == LANE_MEDIA


def resolve_source_channel_for_upload_type(
    upload_type: str, *, db=None
) -> str | None:
    """Default Telegram source channel for an upload job of this type."""
    from database import Database

    db = db or Database()
    ut = normalize_upload_type(upload_type)
    if ut == "mixed":
        return db.get_ingest_channel_id()
    row = db.get_pipeline_upload_default(ut)
    if row and row.get("source_channel_id"):
        return str(row["source_channel_id"])
    return None


def format_channel_label(
    channel_id: str | None,
    *,
    title: str | None = None,
    username: str | None = None,
    db=None,
) -> str:
    if not channel_id:
        return "not set"
    if username:
        return f"@{username}"
    if title:
        return title
    from database import Database

    ch = (db or Database()).get_channel(channel_id)
    if ch and ch.channel_username:
        return f"@{ch.channel_username}"
    if ch and ch.channel_title:
        return ch.channel_title
    return str(channel_id)


# --- Bot UI (Library setup → Pipeline upload targets) ---

import logging

from config import Config
from database import Database
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from watch_features import _edit_or_reply

logger = logging.getLogger(__name__)
_db = Database()


async def send_pipeline_setup_hub(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    defaults = _db.list_pipeline_upload_defaults()
    dist = _db.list_watch_lane_assignments()
    media_pub = dist.get(LANE_MEDIA)

    lines = [
        "<b>📤 Pipeline upload targets</b>",
        "<i>One-time — new jobs inherit these automatically.</i>",
        "",
        "<b>Source channel</b> = where Telethon uploads files "
        "(messages live here; used for playback/indexing).",
        "<b>Publish channel</b> (media only) = watch library with TMDB catalog cards.",
        "",
        "<b>Default source per upload type</b>",
    ]
    keyboard = []
    for row in defaults:
        ut = row["upload_type"]
        label = dict(PIPELINE_UPLOAD_TYPES).get(ut, ut)
        src = format_channel_label(
            row.get("source_channel_id"),
            title=row.get("channel_title"),
            username=row.get("channel_username"),
            db=_db,
        )
        lines.append(f"{label}")
        lines.append(f"  → <b>{src}</b>")
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"Set {label.split(maxsplit=1)[-1][:20]}",
                    callback_data=f"setup_pipe_type:{ut}",
                )
            ]
        )
    lines.extend(
        [
            "",
            "<b>Media publish channel</b> (watch library)",
            f"  → {format_channel_label(media_pub.channel_id if media_pub else None, title=getattr(media_pub, 'channel_title', None), username=getattr(media_pub, 'channel_username', None), db=_db) if media_pub else 'not set'}",
        ]
    )
    keyboard.append(
        [InlineKeyboardButton("📺 Set media publish channel", callback_data="setup_watch")]
    )
    keyboard.append([InlineKeyboardButton("« Library setup", callback_data="setup_hub")])
    context.user_data["setup_return"] = "setup_pipeline"
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_pipeline_type_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    upload_type: str,
    *,
    edit: bool = False,
) -> None:
    from content_lanes import LANE_LABELS

    query = update.callback_query
    target = query if edit and query else update
    ut = normalize_upload_type(upload_type)
    label = dict(PIPELINE_UPLOAD_TYPES).get(ut, LANE_LABELS.get(ut, ut))
    ch_id = resolve_source_channel_for_upload_type(ut, db=_db)
    src = format_channel_label(ch_id, db=_db)
    lines = [
        f"<b>{label}</b>",
        "",
        f"Default <b>source channel</b>: {src}",
        "",
        "Pick a channel where the bot can post (Telethon upload destination).",
    ]
    if ut == "mixed":
        lines.append(
            "\n<i>This also sets the historical ingest sink channel.</i>"
        )
    if ut == LANE_MEDIA:
        lines.append(
            "\n<i>Catalog publish uses a separate watch channel — "
            "use « Set media publish channel » from the previous screen.</i>"
        )
    keyboard = [
        [InlineKeyboardButton("📡 Choose channel", callback_data=f"setup_pipe_ch:{ut}:0")],
    ]
    if ch_id:
        keyboard.append(
            [InlineKeyboardButton("✖ Clear default", callback_data=f"setup_pipe_clear:{ut}")]
        )
    keyboard.append([InlineKeyboardButton("« Pipeline targets", callback_data="setup_pipeline")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_pipeline_channel_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    upload_type: str,
    page: int = 0,
    query: str | None = None,
    *,
    edit: bool = False,
) -> None:
    from channel_picker import build_channel_picker
    from content_lanes import LANE_LABELS

    target = update.callback_query if edit and update.callback_query else update
    ut = normalize_upload_type(upload_type)
    label = dict(PIPELINE_UPLOAD_TYPES).get(ut, LANE_LABELS.get(ut, ut))
    channels = _db.get_channels_bot_can_post(active_only=True)
    title = (
        f"<b>Source channel — {label}</b>\n\n"
        "Bot must be admin here. New upload jobs of this type use this channel."
    )

    def label_fn(ch):
        return (ch.channel_title or ch.channel_username or ch.channel_id)[:60]

    text, markup = build_channel_picker(
        channels,
        page=page,
        query=query,
        callback_prefix=f"spch{ut}",
        pick_prefix=f"setup_pipe_pick:{ut}",
        label_fn=label_fn,
        back_callback=f"setup_pipe_type:{ut}",
        back_label="« Back",
        search_callback=f"setup_pipe_search:{ut}",
        title_line=title,
    )
    await _edit_or_reply(target, text, markup, edit=edit)


async def handle_pipeline_setup_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    if not (
        data == "setup_pipeline"
        or data.startswith("setup_pipe_")
        or data.startswith("spch")
    ):
        return False
    if not Config.is_admin(user_id):
        return False

    if data == "setup_pipeline":
        await send_pipeline_setup_hub(update, context, edit=True)
        return True
    if data.startswith("setup_pipe_type:"):
        ut = data.split(":", 1)[1]
        await send_pipeline_type_menu(update, context, ut, edit=True)
        return True
    if data.startswith("setup_pipe_ch:"):
        parts = data.split(":")
        ut = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_pipeline_channel_picker(update, context, ut, page, edit=True)
        return True
    if data.startswith("setup_pipe_search:"):
        ut = data.split(":", 1)[1]
        context.user_data["awaiting_pipeline_channel_search"] = ut
        await _edit_or_reply(
            update.callback_query,
            f"<b>Search channels</b> ({ut})\n\nSend @username or title fragment.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data=f"setup_pipe_type:{ut}")]]
            ),
            edit=True,
        )
        return True
    if data.startswith("setup_pipe_pick:"):
        parts = data.split(":")
        ut = parts[1]
        channel_id = parts[2]
        if _db.set_pipeline_source_channel(ut, channel_id):
            if update.callback_query:
                await update.callback_query.answer("Source channel saved")
        await send_pipeline_type_menu(update, context, ut, edit=True)
        return True
    if data.startswith("setup_pipe_clear:"):
        ut = data.split(":", 1)[1]
        _db.set_pipeline_source_channel(ut, None)
        if update.callback_query:
            await update.callback_query.answer("Cleared")
        await send_pipeline_type_menu(update, context, ut, edit=True)
        return True
    import re

    from channel_picker import decode_query_token

    m = re.match(r"^spch([^_]+)_page:(\d+)(?::(.*))?$", data)
    if m:
        ut = m.group(1)
        page = int(m.group(2))
        token = m.group(3) or ""
        q = decode_query_token(token) if token else None
        await send_pipeline_channel_picker(update, context, ut, page, q, edit=True)
        return True
    return False
