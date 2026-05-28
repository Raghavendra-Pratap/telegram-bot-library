"""
Admin vault browsers per content lane (course, archive, adult, shortform).
"""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import Config
from content_lanes import LANE_LABELS, VAULT_LANES, normalize_lane
from database import Database
from watch_features import _edit_or_reply

logger = logging.getLogger(__name__)
db = Database()
_VAULT_PAGE = 12


async def send_vault_hub(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    counts = db.get_vault_lane_counts()
    lines = [
        "<b>🗄 Content vaults</b>",
        "",
        "Admin-only browsing by lane. Adult content never appears in public search.",
        "",
    ]
    keyboard = []
    for lane in VAULT_LANES:
        n = counts.get(lane, 0)
        label = LANE_LABELS.get(lane, lane)
        lines.append(f"{label}: <b>{n:,}</b> file(s)")
        keyboard.append(
            [InlineKeyboardButton(f"{label} ({n})", callback_data=f"up_vault_lane:{lane}:0")]
        )
    keyboard.append(
        [InlineKeyboardButton("🔍 Search vault", callback_data="up_vault_search_menu")]
    )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_vault_lane(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lane: str,
    page: int = 0,
    *,
    edit: bool = False,
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    lane = normalize_lane(lane)
    label = LANE_LABELS.get(lane, lane)
    offset = page * _VAULT_PAGE
    lines = [f"<b>{label}</b>", ""]
    keyboard: list[list[InlineKeyboardButton]] = []

    if lane == "course":
        courses = db.list_course_titles(limit=_VAULT_PAGE + 1)
        courses = courses[offset : offset + _VAULT_PAGE]
        if not courses:
            lines.append("<i>No courses indexed yet.</i>")
        else:
            lines.append("Tap a course to browse lessons:")
            for ct in courses:
                n = db.count_vault_files("course", content_title_id=ct.id)
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"🎓 {ct.name[:36]} ({n})",
                            callback_data=f"up_course:{ct.id}",
                        )
                    ]
                )
    else:
        files = db.list_vault_files(lane, limit=_VAULT_PAGE + 1, offset=offset)
        has_more = len(files) > _VAULT_PAGE
        files = files[:_VAULT_PAGE]
        if not files:
            lines.append("<i>No files in this vault.</i>")
        else:
            lines.append(f"Latest files (page {page + 1}):")
            for u in files:
                icon = "📄"
                if (u.file_kind or "") == "image":
                    icon = "🖼"
                elif (u.file_kind or "") == "video":
                    icon = "🎬"
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{icon} {u.file_name[:38]}",
                            callback_data=f"watch_pick:{u.id}",
                        )
                    ]
                )
        nav = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(
                    "« Prev", callback_data=f"up_vault_lane:{lane}:{page - 1}"
                )
            )
        if has_more:
            nav.append(
                InlineKeyboardButton(
                    "Next »", callback_data=f"up_vault_lane:{lane}:{page + 1}"
                )
            )
        if nav:
            keyboard.append(nav)

    if lane != "adult":
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📚 Publish visible in lane",
                    callback_data=f"up_vault_promote_lane:{lane}",
                )
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("🔍 Search this lane", callback_data=f"up_vault_search:{lane}")]
    )
    keyboard.append([InlineKeyboardButton("« Vaults", callback_data="up_vault")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_vault_search_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    keyboard = [
        [
            InlineKeyboardButton("🎓 Course", callback_data="up_vault_search:course"),
            InlineKeyboardButton("📦 Archive", callback_data="up_vault_search:archive"),
        ],
        [
            InlineKeyboardButton("📱 Short", callback_data="up_vault_search:shortform"),
            InlineKeyboardButton("🔒 Adult", callback_data="up_vault_search:adult"),
        ],
        [InlineKeyboardButton("« Vaults", callback_data="up_vault")],
    ]
    await _edit_or_reply(
        target,
        "<b>🔍 Search vault</b>\n\nChoose a lane, then send your search text.",
        InlineKeyboardMarkup(keyboard),
        edit=edit,
    )


async def promote_and_publish_title(
    context: ContextTypes.DEFAULT_TYPE,
    content_title_id: int,
    *,
    to_media_lane: bool,
) -> tuple[int, str]:
    """Promote title and optionally publish watch catalog card."""
    n = db.promote_content_title_to_library(
        content_title_id, to_media_lane=to_media_lane
    )
    note = f"Updated <b>{n}</b> file(s)."
    if not to_media_lane or not n:
        return n, note
    ct = db.get_content_title(content_title_id)
    if not ct or getattr(ct, "catalog_excluded", False):
        return n, note + " Not eligible for watch catalog."
    try:
        from watch_catalog import publish_catalog_slot

        ok, msg = await publish_catalog_slot(
            context.bot,
            db,
            content_title_id,
            None,
            bot_username=context.bot.username,
            force=True,
        )
        if ok and msg == "Published":
            note += " Watch catalog card published."
        elif ok:
            note += f" Catalog: {msg}."
        else:
            note += f" Catalog not published ({msg})."
    except Exception as e:
        logger.warning("catalog publish after promote: %s", e)
        note += " Catalog publish failed — use Watch hub."
    return n, note


async def handle_vault_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    if not data.startswith("up_vault"):
        return False
    if not Config.is_admin(user_id):
        return False

    query = update.callback_query

    if data == "up_vault":
        await send_vault_hub(update, context, edit=True)
        return True
    if data == "up_vault_search_menu":
        await send_vault_search_menu(update, context, edit=True)
        return True
    if data.startswith("up_vault_lane:"):
        parts = data.split(":")
        lane = parts[1]
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_vault_lane(update, context, lane, page, edit=True)
        return True
    if data.startswith("up_vault_search:"):
        lane = data.split(":")[1]
        context.user_data["awaiting_vault_search_lane"] = lane
        await _edit_or_reply(
            query,
            f"<b>Search {escape(LANE_LABELS.get(lane, lane))}</b>\n\n"
            "Send filename or title keywords.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data=f"up_vault_lane:{lane}:0")]]
            ),
            edit=True,
        )
        return True
    if data.startswith("up_vault_promote_lane:"):
        lane = data.split(":")[1]
        if lane == "adult":
            await query.answer("Adult vault cannot go public", show_alert=True)
            return True
        session = db.get_session()
        try:
            from database import FileUpload

            rows = (
                session.query(FileUpload)
                .filter(db._vault_lane_filter(lane))
                .filter(FileUpload.library_visible.is_(False))
                .limit(500)
                .all()
            )
            n = 0
            for u in rows:
                u.library_visible = True
                u.distribution_approved = True
                u.is_confirmed = True
                n += 1
            session.commit()
        finally:
            session.close()
        await query.answer(f"Marked {n} visible in library", show_alert=True)
        await send_vault_lane(update, context, lane, 0, edit=True)
        return True
    return False


async def handle_vault_search_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str
) -> bool:
    lane = context.user_data.pop("awaiting_vault_search_lane", None)
    if not lane or not update.message:
        return False
    if not Config.is_admin(update.effective_user.id):
        return False
    files = db.list_vault_files(lane, limit=20, search=text)
    lines = [
        f"<b>🔍 {escape(LANE_LABELS.get(lane, lane))}</b> — “{escape(text[:40])}”",
        f"<b>{len(files)}</b> match(es)",
        "",
    ]
    keyboard = []
    for u in files[:15]:
        keyboard.append(
            [InlineKeyboardButton(u.file_name[:40], callback_data=f"watch_pick:{u.id}")]
        )
    keyboard.append([InlineKeyboardButton("« Vault", callback_data=f"up_vault_lane:{lane}:0")])
    await update.message.reply_text(
        "\n".join(lines) if files else lines[0] + "\n\n<i>No matches.</i>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )
    return True
