"""Public browse for archive lane files (PDFs, ebooks, images)."""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from database import Database
from watch_features import _edit_or_reply

logger = logging.getLogger(__name__)
db = Database()
_PAGE = 12


def _file_icon(upload) -> str:
    kind = (upload.file_kind or "").lower()
    name = (upload.file_name or "").lower()
    if kind == "image" or name.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return "🖼"
    if name.endswith(".pdf"):
        return "📄"
    if name.endswith((".epub", ".mobi", ".azw3")):
        return "📚"
    return "📦"


async def send_archive_browse(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    *,
    edit: bool = False,
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    offset = page * _PAGE
    files = db.list_public_archive_files(limit=_PAGE + 1, offset=offset)
    has_more = len(files) > _PAGE
    files = files[:_PAGE]
    total = db.count_public_archive_files()

    lines = [
        "<b>📦 Documents & archive</b>",
        "",
        f"<b>{total:,}</b> file(s) available.",
        "",
    ]
    if not files:
        lines.append("<i>No published archive files yet.</i>")
    else:
        lines.append(f"Page <b>{page + 1}</b> — tap to open:")
    keyboard: list[list[InlineKeyboardButton]] = []
    for u in files:
        icon = _file_icon(u)
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{icon} {(u.confirmed_name or u.parsed_name or u.file_name)[:38]}",
                    callback_data=f"watch_pick:{u.id}",
                )
            ]
        )
    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton("« Prev", callback_data=f"watch_archive:{page - 1}")
        )
    if has_more:
        nav.append(
            InlineKeyboardButton("Next »", callback_data=f"watch_archive:{page + 1}")
        )
    if nav:
        keyboard.append(nav)
    keyboard.append(
        [InlineKeyboardButton("🔍 Search", callback_data="watch_archive_search")]
    )
    back = "main_menu"
    if context.user_data.get("watch_admin_menu"):
        back = "watch_hub"
    keyboard.append([InlineKeyboardButton("« Menu", callback_data=back)])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def handle_archive_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> bool:
    if data == "watch_archive_search":
        context.user_data["awaiting_archive_search"] = True
        query = update.callback_query
        await _edit_or_reply(
            query,
            "<b>Search archive</b>\n\nSend filename or title keywords.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data="watch_archive:0")]]
            ),
            edit=True,
        )
        return True
    if data.startswith("watch_archive:"):
        page = int(data.split(":")[1])
        await send_archive_browse(update, context, page, edit=True)
        return True
    return False


async def handle_archive_search_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    if not context.user_data.pop("awaiting_archive_search", None):
        return False
    if not update.message:
        return False
    files = db.list_public_archive_files(limit=20, search=text)
    lines = [
        f"<b>📦 Archive search</b> — “{escape(text[:40])}”",
        f"<b>{len(files)}</b> match(es)",
        "",
    ]
    keyboard = []
    for u in files[:15]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    (u.file_name or "?")[:40],
                    callback_data=f"watch_pick:{u.id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Archive", callback_data="watch_archive:0")])
    await update.message.reply_text(
        "\n".join(lines) if files else lines[0] + "\n\n<i>No matches.</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return True
