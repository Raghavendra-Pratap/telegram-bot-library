"""
Bot UI for watch channel, favorites, watchlists, and upload requests.
"""
from __future__ import annotations

import logging
import secrets
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config import Config
from database import Database
from tmdb_helper import (
    format_suggestion_card_caption,
    poster_image_url,
    suggestion_pick_button_label,
    tmdb_helper,
    tmdb_web_url,
)
from watch_catalog import (
    publish_catalog_all,
    season_from_callback,
    upgrade_all_catalog_keyboards,
)
from telegram_flood import (
    _is_channel_media_post,
    flood_bot_edit_message_text,
    flood_delete_message,
    flood_reply_photo,
    flood_reply_text,
    flood_send_message,
    present_callback_ui,
    safe_edit_callback_message,
)
from watch_catalog import upgrade_channel_card_keyboard
from watch_library import channel_message_link

logger = logging.getLogger(__name__)

db = Database()

# TMDB pick flows (request title / add to watchlist)
_PICK_MSGS_REQUEST = "upload_request_pick_msg_ids"
_PICK_MSGS_WATCHLIST = "watchlist_tmdb_pick_msg_ids"
_PICK_SESSION_REQUEST = "upload_request_pick_session"
_PICK_SESSION_WATCHLIST = "watchlist_tmdb_pick_session"


async def _clear_tmdb_pick_messages(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, msgs_key: str
) -> None:
    bot = context.bot
    for mid in context.user_data.pop(msgs_key, None) or []:
        try:
            await flood_delete_message(bot, chat_id, mid)
        except BadRequest:
            pass
        except Exception as e:
            logger.debug("pick message delete %s: %s", mid, e)


def _start_pick_session(context: ContextTypes.DEFAULT_TYPE, session_key: str, msgs_key: str) -> str:
    token = secrets.token_hex(4)
    context.user_data[session_key] = token
    context.user_data[msgs_key] = []
    return token


def _parse_pick_callback(data: str, prefix: str) -> tuple[str | None, int] | None:
    """Return (session_token or None for legacy, suggestion_index)."""
    if not data.startswith(prefix):
        return None
    rest = data[len(prefix) :]
    parts = rest.split(":")
    if len(parts) == 1:
        try:
            return None, int(parts[0])
        except ValueError:
            return None
    if len(parts) == 2:
        try:
            return parts[0], int(parts[1])
        except ValueError:
            return None
    return None


async def _send_tmdb_suggestion_cards(
    message,
    context: ContextTypes.DEFAULT_TYPE,
    suggestions: list,
    query_text: str,
    *,
    pick_prefix: str,
    session_key: str,
    msgs_key: str,
    suggestions_key: str,
) -> None:
    """Show TMDB poster cards; track message ids so we can remove them after a pick."""
    chat_id = message.chat_id
    await _clear_tmdb_pick_messages(context, chat_id, msgs_key)
    context.user_data[suggestions_key] = suggestions
    token = _start_pick_session(context, session_key, msgs_key)
    msg_ids: list[int] = []

    header = await flood_reply_text(
        message,
        text=f"<b>Pick the correct title</b> for:\n{escape(query_text)}",
        parse_mode=ParseMode.HTML,
    )
    msg_ids.append(header.message_id)

    for i, s in enumerate(suggestions[:5], 1):
        caption = format_suggestion_card_caption(s, i, overview_chars=600)
        url = poster_image_url(s)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        suggestion_pick_button_label(s, i),
                        callback_data=f"{pick_prefix}:{token}:{i - 1}",
                    )
                ]
            ]
        )
        if url:
            sent = await flood_reply_photo(
                message,
                url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            sent = await flood_reply_text(
                message,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        msg_ids.append(sent.message_id)

    context.user_data[msgs_key] = msg_ids


async def _finish_tmdb_pick(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    session_key: str,
    msgs_key: str,
    success_html: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """Remove all suggestion cards and post a single confirmation message."""
    chat_id = query.message.chat_id if query.message else None
    if chat_id:
        await _clear_tmdb_pick_messages(context, chat_id, msgs_key)
        await flood_send_message(
            context.bot,
            chat_id,
            success_html,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    context.user_data.pop(session_key, None)


async def _edit_or_reply(target, text, keyboard, *, edit: bool) -> None:
    if edit and hasattr(target, "edit_message_text"):
        await present_callback_ui(
            target, text, reply_markup=keyboard, parse_mode=ParseMode.HTML
        )
    elif edit and hasattr(target, "effective_message") and target.effective_message:
        await target.effective_message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )
    else:
        msg = getattr(target, "effective_message", None) or getattr(target, "message", None)
        if msg:
            await msg.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


def _bot_username(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    return getattr(context.bot, "username", None) or None


async def _resolve_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    from watch_catalog import resolve_bot_username

    return await resolve_bot_username(context.bot, _bot_username(context))


async def _prompt_channel_deep_link(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    content_title_id: int,
    season_number: int | None,
    *,
    button_hint: str,
) -> bool:
    """Legacy callback on a channel card → swap to URL buttons, then user taps again."""
    msg = query.message
    if not msg or not _is_channel_media_post(msg):
        return False
    uname = await _resolve_bot_username(context)
    if not uname:
        await query.answer("Bot username not configured.", show_alert=True)
        return True
    await upgrade_channel_card_keyboard(
        context.bot,
        msg,
        content_title_id,
        season_number,
        bot_username=uname,
    )
    await query.answer(
        f"Tap {button_hint} on the card again — opens @{uname} for your personal menu.",
        show_alert=True,
    )
    return True


def _watch_channel_link(channel) -> str | None:
    if not channel:
        return None
    if channel.channel_username:
        return f"https://t.me/{channel.channel_username.lstrip('@')}"
    return channel_message_link(channel.channel_id, 1)


def _content_title_from_suggestion(s: dict):
    title = (s.get("title") or "?").strip()
    mt = (s.get("media_type") or "movie").lower()
    year = None
    if s.get("year") and str(s["year"]).isdigit():
        year = int(s["year"])
    vote = s.get("vote_average")
    vote_s = str(vote) if vote is not None else None
    return db.upsert_content_title(
        local_name=title,
        media_type=mt,
        tmdb_id=s.get("tmdb_id"),
        tmdb_title=title,
        release_year=year,
        poster_path=s.get("poster_path"),
        overview=s.get("overview"),
        vote_average=vote_s,
    )


def _maybe_request_missing_title(user_id: int, s: dict, content_title_id: int) -> bool:
    """Queue an upload request when the title is not in the library yet."""
    if db.count_library_uploads_for_content(content_title_id) > 0:
        return False
    tmdb_id = s.get("tmdb_id")
    media_type = (s.get("media_type") or "movie").lower()
    if db.has_pending_upload_request(user_id, tmdb_id, media_type):
        return False
    return bool(
        db.create_upload_request(
            user_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            tmdb_title=s.get("title") or "?",
            release_year=int(s["year"])
            if s.get("year") and str(s["year"]).isdigit()
            else None,
        )
    )


def build_first_visit_intro(update: Update) -> str:
    """One-time welcome (plain /start)."""
    user = update.effective_user
    name = escape(user.first_name or "there") if user else "there"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        "Tap <b>My menu</b> below to browse, save favorites, or request a title."
    )


def build_first_visit_picker_prefix() -> str:
    """One-line intro prepended to the first watch picker only."""
    return "👋 <b>Welcome!</b> Pick a version below — the file will be sent here.\n\n"


def _user_id(update: Update) -> int:
    return int(update.effective_user.id) if update.effective_user else 0


async def handle_user_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Plain /start for non-admin: welcome once, then open menu only."""
    user_id = _user_id(update)
    if db.user_needs_welcome(user_id):
        msg = update.effective_message
        if msg:
            await msg.reply_text(
                build_first_visit_intro(update),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("📚 My menu", callback_data="main_menu")]]
                ),
            )
            db.mark_user_welcomed(user_id)
        return
    await send_user_main_menu(update, context, edit=False)


def picker_intro_for_user(user_id: int) -> str | None:
    """Return one-time picker prefix, or None if user was already welcomed."""
    if not user_id or not db.user_needs_welcome(user_id):
        return None
    return build_first_visit_picker_prefix()


def _active_pick_message_ids(context: ContextTypes.DEFAULT_TYPE) -> set[int]:
    ids: list[int] = []
    ids.extend(context.user_data.get(_PICK_MSGS_REQUEST) or [])
    ids.extend(context.user_data.get(_PICK_MSGS_WATCHLIST) or [])
    return set(ids)


async def send_user_main_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    """Home menu for non-admin users — personal lists only, no indexer admin tools."""
    query = update.callback_query
    target = query if edit and query else update
    if (
        edit
        and query
        and query.message
        and query.message.message_id in _active_pick_message_ids(context)
    ):
        # Do not replace a TMDB suggestion poster with the menu — send a new message.
        target = update
        edit = False
    user = update.effective_user
    n_fav = len(db.get_user_favorites(user.id)) if user else 0
    n_wl = 0
    if user:
        for wl in db.get_user_watchlists(user.id):
            n_wl += len(db.get_watchlist_items(user.id, wl.id, limit=500))
    n_req = len(db.get_user_upload_requests(user.id, limit=100)) if user else 0
    watch_ch = db.get_watch_channel()
    lines = [
        "<b>📚 My library</b>",
        "",
        "Browse what is available, manage your lists, and request titles "
        "that are not uploaded yet.",
        "",
        f"⭐ Favorites: <b>{n_fav}</b> · 📋 Watchlist: <b>{n_wl}</b> · "
        f"📨 Requests: <b>{n_req}</b>",
    ]
    if watch_ch:
        link = _watch_channel_link(watch_ch)
        label = escape(watch_ch.channel_title or watch_ch.channel_username or "channel")
        lines.append(f"\n📺 Watch channel: <b>{label}</b>")
        if link:
            lines.append(f'<a href="{escape(link)}">Open channel</a>')
    keyboard = [
        [
            InlineKeyboardButton("🔍 Search", callback_data="search_menu"),
            InlineKeyboardButton("📖 Browse", callback_data="library_browse"),
        ],
        [InlineKeyboardButton("📚 Full library", callback_data="library_all")],
        [
            InlineKeyboardButton("⭐ Favorites", callback_data="watch_favorites"),
            InlineKeyboardButton("📋 Watchlist", callback_data="watch_watchlists"),
        ],
        [
            InlineKeyboardButton("📨 My requests", callback_data="watch_my_requests"),
            InlineKeyboardButton("➕ Request title", callback_data="watch_req_start"),
        ],
        [InlineKeyboardButton("➕ Add to watchlist", callback_data="watch_wl_add_start")],
    ]
    if watch_ch:
        keyboard.insert(2, [InlineKeyboardButton("📺 Watch channel", callback_data="watch_hub")])
    keyboard.append([InlineKeyboardButton("ℹ️ Help", callback_data="watch_help")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_watch_hub_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    watch_ch = db.get_watch_channel()
    published = db.count_watch_published()
    pending_new = db.count_unpublished_catalog_slots()
    pending_req = db.count_pending_upload_requests()
    lines = [
        "<b>📺 Watch library</b>",
        "",
        "The watch channel shows <b>one poster card per title</b> "
        "(or per TV season). Tap <b>▶️ Watch</b> on a card — it opens this bot "
        "to pick quality and download.",
        "",
    ]
    user = update.effective_user
    is_admin_user = bool(user and Config.is_admin(user.id))
    if watch_ch:
        link = _watch_channel_link(watch_ch)
        label = escape(watch_ch.channel_title or watch_ch.channel_username or "channel")
        lines.append(f"Channel: <b>{label}</b>")
        if link:
            lines.append(f'<a href="{escape(link)}">Open watch channel</a>')
        if is_admin_user:
            lines.append(
                f"Published catalog cards: <b>{published}</b>"
                + (f" · <b>{pending_new}</b> new to publish" if pending_new else "")
            )
        lines.append(
            "\n<i>Commands:</i> /favorites · /watchlist · /request · /menu"
        )
    else:
        lines.append("<i>Watch channel not set — ask an admin to configure it.</i>")
    if pending_req and is_admin_user:
        lines.append(f"\n⏳ Pending upload requests: <b>{pending_req}</b>")
    if is_admin_user:
        lines.extend(
            [
                "",
                "<b>Admin buttons</b>",
                "• <b>Publish new cards</b> — queues all unpublished titles (batched, runs in background)",
                "• Pending files: use <b>Skip watch catalog</b> or <b>Custom (no card)</b> for reels/lectures",
                "• <b>Refresh existing cards</b> — update live posts; repost any that were deleted",
                "• <b>Post all to channel</b> — new poster for every title (use if channel was cleared)",
                "• <b>Fix card buttons</b> — ▶ Watch / watchlist links only (no caption changes)",
                "• <b>Reset registry</b> — clear DB registry, then post all as new messages",
                "• <b>Upload requests</b> — user-requested titles (poster cards, like TMDB pick)",
                "• <b>Set channel</b> — which Telegram channel is the public watch feed",
            ]
        )

    keyboard = [
        [
            InlineKeyboardButton("⭐ Favorites", callback_data="watch_favorites"),
            InlineKeyboardButton("📋 Watchlist", callback_data="watch_watchlists"),
        ],
        [
            InlineKeyboardButton("📨 My requests", callback_data="watch_my_requests"),
            InlineKeyboardButton("➕ Request title", callback_data="watch_req_start"),
        ],
        [InlineKeyboardButton("➕ Add to watchlist", callback_data="watch_wl_add_start")],
        [InlineKeyboardButton("📚 Browse library", callback_data="library_all")],
    ]
    if not is_admin_user:
        keyboard.append([InlineKeyboardButton("« My menu", callback_data="main_menu")])
    if is_admin_user:
        pub_row = [
            InlineKeyboardButton(
                "📤 Publish new cards", callback_data="watch_publish_run"
            ),
            InlineKeyboardButton("⚙️ Set channel", callback_data="set_watch_channel_menu"),
        ]
        keyboard.append(pub_row)
        if published > 0:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔄 Refresh existing cards",
                        callback_data="watch_refresh_catalog",
                    ),
                ]
            )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📤 Post all to channel", callback_data="watch_republish_run"
                ),
            ]
        )
        if published > 0:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        "🔗 Fix card buttons", callback_data="watch_upgrade_links"
                    ),
                    InlineKeyboardButton(
                        "🗑 Reset registry", callback_data="watch_publish_fresh"
                    ),
                ]
            )
        if pending_req:
            keyboard.append(
                [InlineKeyboardButton("📋 Upload requests", callback_data="watch_req_admin")]
            )
    if is_admin_user:
        keyboard.append([InlineKeyboardButton("« Main menu", callback_data="main_menu")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_my_requests_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    user = update.effective_user
    if not user:
        return
    rows = db.get_user_upload_requests(user.id, limit=25)
    lines = ["<b>📨 My upload requests</b>", ""]
    keyboard = []
    if not rows:
        lines.append(
            "<i>No requests yet.</i>\n\n"
            "Use <b>➕ Request title</b> or add a missing title to your watchlist — "
            "we queue a request automatically when it is not in the library."
        )
    else:
        status_icon = {"pending": "⏳", "done": "✅", "rejected": "❌"}
        for r in rows:
            kind = "📺" if r.media_type == "tv" else "🎬"
            yr = f" ({r.release_year})" if r.release_year else ""
            icon = status_icon.get(r.status, "•")
            lines.append(
                f"{icon} {kind} <b>{escape(r.tmdb_title)}</b>{yr} — "
                f"<i>{escape(r.status)}</i>"
            )
    keyboard.append(
        [InlineKeyboardButton("➕ Request title", callback_data="watch_req_start")]
    )
    keyboard.append([InlineKeyboardButton("« My menu", callback_data="main_menu")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_set_watch_channel_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    channels = [c for c in db.get_all_channels_registered(active_only=False) if c.is_active]
    current = db.get_watch_channel()
    lines = [
        "<b>📺 Watch channel setup</b>",
        "",
        "Pick the channel where library files are <b>copied</b> for users. "
        "The bot must be <b>admin</b> there and in source channels.",
        "",
    ]
    if current:
        lines.append(f"Current: <b>{escape(current.channel_title or current.channel_id)}</b>")
    else:
        lines.append("<i>None set — or set WATCH_CHANNEL_ID in .env</i>")
    keyboard = []
    for ch in channels[:20]:
        marker = "✅ " if current and str(ch.channel_id) == str(current.channel_id) else ""
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{marker}{ch.channel_title or ch.channel_id}"[:60],
                    callback_data=f"set_watch_channel:{ch.channel_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Watch hub", callback_data="watch_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_favorites_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    user = update.effective_user
    if not user:
        return
    favs = db.get_user_favorites(user.id)
    lines = ["<b>⭐ Favorites</b>", ""]
    keyboard = []
    if not favs:
        lines.append("<i>No favorites yet. Use ⭐ on watch channel posts or title pages.</i>")
    else:
        for f in favs:
            icon = "📺" if (f.get("media_type") or "") == "tv" else "🎬"
            title = (f.get("title") or "?")[:28]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{icon} {title}",
                        callback_data=f"watch_open_title:{f['content_title_id']}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton("« My menu", callback_data="main_menu")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_watchlists_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    user = update.effective_user
    if not user:
        return
    lists = db.get_user_watchlists(user.id)
    if not lists:
        db.get_or_create_default_watchlist(user.id)
        lists = db.get_user_watchlists(user.id)
    lines = ["<b>📋 My watchlists</b>", "", "Tap a list to view titles:"]
    keyboard = []
    for wl in lists:
        n = len(db.get_watchlist_items(user.id, wl.id, limit=500))
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📋 {wl.list_name} ({n})",
                    callback_data=f"watch_wl_view:{wl.id}",
                )
            ]
        )
    keyboard.append(
        [
            InlineKeyboardButton("➕ Add title", callback_data="watch_wl_add_start"),
            InlineKeyboardButton("➕ New list", callback_data="watch_wl_new"),
        ]
    )
    keyboard.append([InlineKeyboardButton("« My menu", callback_data="main_menu")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_watchlist_add_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    watchlist_id: int | None = None,
    edit: bool = False,
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    user = update.effective_user
    if not user:
        return
    if watchlist_id is None:
        watchlist_id = db.get_or_create_default_watchlist(user.id)
    if query and query.message:
        await _clear_tmdb_pick_messages(context, query.message.chat_id, _PICK_MSGS_WATCHLIST)
        context.user_data.pop(_PICK_SESSION_WATCHLIST, None)
        context.user_data.pop("watchlist_tmdb_suggestions", None)
    context.user_data["watch_wl_add_target"] = watchlist_id
    context.user_data["awaiting_watchlist_tmdb"] = True
    lines = [
        "<b>➕ Add to watchlist</b>",
        "",
        "Send the <b>movie or series name</b> (English works best).",
        "We match TMDB, add the title to your list, and "
        "<b>automatically request an upload</b> if it is not in the library yet.",
        "",
        "<i>Example: Dune Part Two</i>",
    ]
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Cancel", callback_data="watch_watchlists")]]
    )
    await _edit_or_reply(target, "\n".join(lines), keyboard, edit=edit)


async def send_watchlist_tmdb_picks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query_text: str,
) -> None:
    if not tmdb_helper.enabled:
        await update.message.reply_text(
            "❌ TMDB is not configured on this bot.",
            parse_mode=ParseMode.HTML,
        )
        return
    suggestions = tmdb_helper.search_suggestions_multi(query_text, limit=5)
    if not suggestions:
        await update.message.reply_text(
            f"No TMDB matches for <b>{escape(query_text)}</b>. Try another spelling.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _send_tmdb_suggestion_cards(
        update.message,
        context,
        suggestions,
        query_text,
        pick_prefix="watch_wl_tmdb_pick",
        session_key=_PICK_SESSION_WATCHLIST,
        msgs_key=_PICK_MSGS_WATCHLIST,
        suggestions_key="watchlist_tmdb_suggestions",
    )


async def send_watchlist_view(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    watchlist_id: int,
    *,
    edit: bool = False,
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    user = update.effective_user
    if not user:
        return
    items = db.get_watchlist_items(user.id, watchlist_id)
    lines = [
        "<b>📋 Watchlist</b>",
        "",
        "⏳ = not in library yet · ✅ = watched",
        "",
    ]
    keyboard = []
    if not items:
        lines.append(
            "<i>Empty — add from the library, watch channel, or ➕ Add title (TMDB).</i>"
        )
    for it in items:
        icon = "📺" if (it.get("media_type") or "") == "tv" else "🎬"
        prefix = "✅ " if it.get("watched") else ""
        if not it.get("in_library"):
            prefix = "⏳ " + prefix
        title = (it.get("title") or "?")[:26]
        item_id = it.get("item_id")
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{prefix}{icon} {title}",
                    callback_data=f"watch_open_title:{it['content_title_id']}",
                ),
                InlineKeyboardButton(
                    "✅" if it.get("watched") else "⬜",
                    callback_data=f"watch_wl_watched:{item_id}",
                ),
            ]
        )
    keyboard.append(
        [InlineKeyboardButton("➕ Add title", callback_data=f"watch_wl_add_to:{watchlist_id}")]
    )
    keyboard.append([InlineKeyboardButton("« Watchlists", callback_data="watch_watchlists")])
    keyboard.append([InlineKeyboardButton("« My menu", callback_data="main_menu")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_request_upload_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    if query and query.message:
        await _clear_tmdb_pick_messages(context, query.message.chat_id, _PICK_MSGS_REQUEST)
        context.user_data.pop(_PICK_SESSION_REQUEST, None)
        context.user_data.pop("upload_request_suggestions", None)
    context.user_data["awaiting_upload_request"] = True
    lines = [
        "<b>➕ Request a title</b>",
        "",
        "Send the <b>movie or series name</b> (English title works best).",
        "We will match it on TMDB and queue it for upload.",
        "",
        "<i>Example: Dune Part Two</i>",
    ]
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Cancel", callback_data="main_menu")]]
    )
    await _edit_or_reply(target, "\n".join(lines), keyboard, edit=edit)


async def send_upload_request_tmdb_picks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query_text: str,
) -> None:
    if not tmdb_helper.enabled:
        await update.message.reply_text(
            "❌ TMDB is not configured on this bot.",
            parse_mode=ParseMode.HTML,
        )
        return
    suggestions = tmdb_helper.search_suggestions_multi(query_text, limit=5)
    if not suggestions:
        await update.message.reply_text(
            f"No TMDB matches for <b>{escape(query_text)}</b>. Try another spelling.",
            parse_mode=ParseMode.HTML,
        )
        return
    await _send_tmdb_suggestion_cards(
        update.message,
        context,
        suggestions,
        query_text,
        pick_prefix="watch_req_pick",
        session_key=_PICK_SESSION_REQUEST,
        msgs_key=_PICK_MSGS_REQUEST,
        suggestions_key="upload_request_suggestions",
    )


def _upload_request_card_dict(req) -> dict:
    """TMDB-shaped dict for poster cards (same style as publish / user pick)."""
    s = {
        "title": req.tmdb_title,
        "year": req.release_year,
        "media_type": req.media_type or "movie",
        "tmdb_id": req.tmdb_id,
    }
    if req.tmdb_id:
        mt = (req.media_type or "movie").lower()
        details = (
            tmdb_helper.fetch_tv_details(req.tmdb_id)
            if mt in ("tv", "series")
            else tmdb_helper.fetch_movie_details(req.tmdb_id)
        )
        if details:
            s["title"] = details.get("tmdb_title") or s["title"]
            s["year"] = details.get("release_year") or s["year"]
            s["overview"] = details.get("overview")
            s["poster_path"] = details.get("poster_path")
            s["vote_average"] = details.get("vote_average")
    return s


def format_admin_request_card_caption(s: dict, index: int, req) -> str:
    body = format_suggestion_card_caption(s, index, overview_chars=500)
    when = ""
    if getattr(req, "created_at", None):
        when = f"\n🕐 {req.created_at.strftime('%Y-%m-%d %H:%M')} UTC"
    return (
        f"{body}\n\n"
        f"📨 <b>Upload request #{req.id}</b> · user <code>{req.user_id}</code>{when}"
    )


_ADMIN_REQ_MSGS_KEY = "admin_upload_request_msg_ids"


async def _clear_admin_request_cards(context, chat_id: int) -> None:
    ids = context.user_data.pop(_ADMIN_REQ_MSGS_KEY, None) or []
    for mid in ids:
        try:
            await flood_delete_message(context.bot, chat_id, mid)
        except Exception:
            pass


async def send_admin_upload_requests(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    rows = db.get_pending_upload_requests(12)
    chat_id = None
    if query and query.message:
        chat_id = query.message.chat_id
    elif update.effective_message:
        chat_id = update.effective_message.chat_id

    if chat_id:
        await _clear_admin_request_cards(context, chat_id)

    hub_keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("« Watch hub", callback_data="watch_hub")]]
    )

    if not rows:
        text = "<b>📋 Upload requests</b>\n\n<i>No pending requests.</i>"
        if edit and query:
            await safe_edit_callback_message(
                query, text, reply_markup=hub_keyboard, parse_mode=ParseMode.HTML
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                text, parse_mode=ParseMode.HTML, reply_markup=hub_keyboard
            )
        return

    header = (
        f"<b>📋 Upload requests</b> — <b>{len(rows)}</b> pending\n\n"
        "<i>Poster cards below (same layout as published / TMDB pick). "
        "Use ✅ Done or ❌ Reject on each.</i>"
    )
    if edit and query:
        await safe_edit_callback_message(
            query, header, reply_markup=hub_keyboard, parse_mode=ParseMode.HTML
        )
        anchor = query.message
    elif update.effective_message:
        header_msg = await update.effective_message.reply_text(
            header, parse_mode=ParseMode.HTML, reply_markup=hub_keyboard
        )
        anchor = header_msg
    else:
        return

    if not chat_id:
        return

    msg_ids: list[int] = []
    for i, req in enumerate(rows, 1):
        s = _upload_request_card_dict(req)
        caption = format_admin_request_card_caption(s, i, req)
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Done", callback_data=f"watch_req_done:{req.id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Reject", callback_data=f"watch_req_reject:{req.id}"
                    ),
                ],
            ]
        )
        url = poster_image_url(s)
        if url:
            sent = await flood_reply_photo(
                anchor,
                url,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            page = tmdb_web_url(s)
            if page:
                caption += f'\n\n<a href="{escape(page)}">TMDB</a>'
            sent = await flood_reply_text(
                anchor,
                text=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        msg_ids.append(sent.message_id)

    context.user_data[_ADMIN_REQ_MSGS_KEY] = msg_ids


async def run_watch_publish_batch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    edit: bool = False,
    republish: bool = False,
    post_new: bool = False,
    reset_registry: bool = False,
) -> None:
    from job_queue import enqueue_background

    user = update.effective_user
    if not user or not Config.is_admin(user.id):
        if update.callback_query:
            await update.callback_query.answer("Admin only", show_alert=True)
        return
    query = update.callback_query
    app = context.application
    refresh_in_place = republish and not post_new and not reset_registry
    if reset_registry:
        action = "Resetting & publishing catalog cards"
    elif post_new:
        action = "Posting catalog cards"
    elif refresh_in_place:
        action = "Refreshing catalog cards"
    else:
        action = "Publishing catalog cards"

    status = query.message if edit and query else None
    if edit and query:
        await safe_edit_callback_message(
            query,
            f"⏳ <b>Please wait</b>\n\n📤 <b>{action}…</b>\n\n"
            "<i>Runs in the background in batches — indexing and other bot work "
            "continues. Large catalogs may take a while.</i>",
            reply_markup=None,
            parse_mode=ParseMode.HTML,
        )

    async def _job() -> None:
        try:
            if reset_registry:
                cleared = db.clear_watch_catalog_posts()
                logger.info("Cleared %s watch catalog registry rows", cleared)

            async def progress(
                done: int, ok: int, fail: int, batch_num: int
            ) -> None:
                if not status:
                    return
                try:
                    await flood_bot_edit_message_text(
                        context.bot,
                        status.chat_id,
                        status.message_id,
                        f"⏳ <b>{action}…</b>\n"
                        f"Batch <b>{batch_num}</b> · processed <b>{done}</b>\n"
                        f"✅ {ok} · ❌ {fail}",
                    )
                except Exception:
                    pass

            ok, fail, errors, total, batch_stats = await publish_catalog_all(
                context.bot,
                db,
                bot_username=_bot_username(context),
                progress_callback=progress if status else None,
                republish=republish or reset_registry,
                post_new=post_new or reset_registry,
            )
            if reset_registry or post_new:
                label = "Post complete"
                stat = f"✅ {ok} posted · ❌ {fail} failed"
            elif refresh_in_place:
                label = "Refresh complete"
                parts = []
                if batch_stats.get("updated"):
                    parts.append(f"{batch_stats['updated']} updated")
                if batch_stats.get("reposted"):
                    parts.append(f"{batch_stats['reposted']} reposted")
                if batch_stats.get("published"):
                    parts.append(f"{batch_stats['published']} new")
                stat = (
                    f"✅ {ok} ok"
                    + (f" ({', '.join(parts)})" if parts else "")
                    + f" · ❌ {fail} failed"
                )
            else:
                label = "Publish complete"
                stat = f"✅ {ok} published · ❌ {fail} failed"
            lines = [f"<b>📤 {label}</b>", stat]
            if batch_stats.get("batches", 0) > 1:
                lines.append(
                    f"\n<i>Completed in {batch_stats['batches']} batches "
                    f"({Config.WATCH_CATALOG_PUBLISH_BATCH_SIZE} cards per batch).</i>"
                )
            if total == 0 and not republish and not reset_registry:
                lines.append(
                    "\n<i>Bot thinks everything is already published.</i>\n"
                    "If you deleted channel posts, use <b>📤 Post all to channel</b> "
                    "or <b>🗑 Reset registry</b>."
                )
            elif total == 0:
                lines.append("\n<i>No library titles found to publish.</i>")
            elif refresh_in_place and batch_stats.get("reposted"):
                lines.append(
                    f"\n<i>{batch_stats['reposted']} card(s) were missing in the channel and were posted again.</i>"
                )
            elif refresh_in_place and fail > 0:
                lines.append(
                    "\n<i>Some slots could not be refreshed — check bot admin rights in the watch channel.</i>"
                )
            if errors[:5]:
                lines.append("\n" + "\n".join(escape(e) for e in errors[:5]))
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Watch hub", callback_data="watch_hub")]]
            )
            if status:
                await flood_bot_edit_message_text(
                    context.bot,
                    status.chat_id,
                    status.message_id,
                    "\n".join(lines),
                    reply_markup=keyboard,
                )
        except Exception:
            logger.exception("watch publish batch failed")
            if status:
                try:
                    await flood_bot_edit_message_text(
                        context.bot,
                        status.chat_id,
                        status.message_id,
                        "❌ <b>Catalog publish failed</b>\n\n"
                        "<i>Check bot.log for details.</i>",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "« Watch hub", callback_data="watch_hub"
                                    )
                                ]
                            ]
                        ),
                    )
                except Exception:
                    pass
    async def _enqueue() -> None:
        await enqueue_background(app, action, _job, exclusive=False)

    context.application.create_task(_enqueue())


async def handle_watch_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    """Handle watch_* callbacks. Return True if consumed."""
    query = update.callback_query
    if not query:
        return False

    if data == "watch_hub":
        await send_watch_hub_menu(update, context, edit=True)
        return True

    if data == "watch_favorites":
        await send_favorites_menu(update, context, edit=True)
        return True

    if data == "watch_watchlists":
        await send_watchlists_menu(update, context, edit=True)
        return True

    if data == "watch_my_requests":
        await send_my_requests_menu(update, context, edit=True)
        return True

    if data == "watch_wl_add_start":
        await send_watchlist_add_start(update, context, edit=True)
        return True

    if data.startswith("watch_wl_add_to:"):
        wl_id = int(data.split(":")[1])
        await send_watchlist_add_start(update, context, watchlist_id=wl_id, edit=True)
        return True

    if data.startswith("watch_wl_watched:"):
        item_id = int(data.split(":")[1])
        watched = db.toggle_watchlist_item_watched(user_id, item_id)
        if watched is None:
            await query.answer("Not found", show_alert=True)
            return True
        await query.answer("Marked watched" if watched else "Marked unwatched", show_alert=False)
        wl_id = context.user_data.get("watch_wl_view_id")
        if wl_id:
            await send_watchlist_view(update, context, wl_id, edit=True)
        else:
            await send_watchlists_menu(update, context, edit=True)
        return True

    if data.startswith("watch_wl_tmdb_pick:"):
        parsed = _parse_pick_callback(data, "watch_wl_tmdb_pick:")
        if not parsed:
            await query.answer("Invalid pick", show_alert=True)
            return True
        token, idx = parsed
        expected = context.user_data.get(_PICK_SESSION_WATCHLIST)
        if expected and token is not None and token != expected:
            await query.answer(
                "This list expired — search again from Add to watchlist.",
                show_alert=True,
            )
            return True
        suggestions = context.user_data.get("watchlist_tmdb_suggestions") or []
        if idx >= len(suggestions):
            await query.answer("Expired — try again", show_alert=True)
            return True
        s = suggestions[idx]
        ct = _content_title_from_suggestion(s)
        if not ct:
            await query.answer("Could not save title", show_alert=True)
            return True
        wl_id = context.user_data.get("watch_wl_add_target") or db.get_or_create_default_watchlist(
            user_id
        )
        db.add_watchlist_item(user_id, wl_id, ct.id)
        requested = _maybe_request_missing_title(user_id, s, ct.id)
        in_lib = db.count_library_uploads_for_content(ct.id) > 0
        extra = ""
        if requested:
            extra = "\n\n📨 <b>Upload request</b> queued — we will add it when available."
        elif not in_lib:
            extra = "\n\n<i>Already requested or waiting for upload.</i>"
        title = escape(s.get("title") or "?")
        await _finish_tmdb_pick(
            query,
            context,
            session_key=_PICK_SESSION_WATCHLIST,
            msgs_key=_PICK_MSGS_WATCHLIST,
            success_html=(
                f"✅ <b>Added to watchlist</b>\n\n<b>{title}</b>"
                + (
                    "\n\n▶️ Available in the library — open My menu → Browse."
                    if in_lib
                    else extra
                )
            ),
            keyboard=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📋 Watchlist", callback_data=f"watch_wl_view:{wl_id}")],
                    [InlineKeyboardButton("« My menu", callback_data="main_menu")],
                ]
            ),
        )
        context.user_data.pop("awaiting_watchlist_tmdb", None)
        context.user_data.pop("watchlist_tmdb_suggestions", None)
        return True

    if data == "watch_help":
        bot_user = context.bot.username or "bot"
        await safe_edit_callback_message(
            query,
            "<b>📺 How to use the bot</b>\n\n"
            f"• <b>My menu</b> — favorites, watchlist, requests\n"
            f"• <b>Watch channel</b> — tap ▶️ on a card to pick quality\n"
            f"• <b>Add to watchlist</b> — any TMDB title; missing uploads are requested automatically\n"
            f"• Mark items ✅ from your watchlist when you have watched them\n\n"
            f"<i>Commands in @{bot_user}: /menu /favorites /watchlist /request</i>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« My menu", callback_data="main_menu")]]
            ),
        )
        return True

    if data.startswith("watch_wl_view:"):
        wl_id = int(data.split(":")[1])
        context.user_data["watch_wl_view_id"] = wl_id
        await send_watchlist_view(update, context, wl_id, edit=True)
        return True

    if data == "watch_wl_new":
        context.user_data["awaiting_watchlist_name"] = True
        await safe_edit_callback_message(
            query,
            "Send a name for your new watchlist:",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data="watch_watchlists")]]
            ),
        )
        return True

    if data == "watch_req_start":
        if query.message:
            await _clear_tmdb_pick_messages(context, query.message.chat_id, _PICK_MSGS_REQUEST)
            context.user_data.pop(_PICK_SESSION_REQUEST, None)
        await send_request_upload_start(update, context, edit=True)
        return True

    if data.startswith("watch_req_pick:"):
        parsed = _parse_pick_callback(data, "watch_req_pick:")
        if not parsed:
            await query.answer("Invalid pick", show_alert=True)
            return True
        token, idx = parsed
        expected = context.user_data.get(_PICK_SESSION_REQUEST)
        if expected and token is not None and token != expected:
            await query.answer(
                "This list expired — use /request and search again.",
                show_alert=True,
            )
            return True
        suggestions = context.user_data.get("upload_request_suggestions") or []
        if idx >= len(suggestions):
            await query.answer("Expired — try again", show_alert=True)
            return True
        s = suggestions[idx]
        db.create_upload_request(
            user_id,
            tmdb_id=s.get("tmdb_id"),
            media_type=s.get("media_type") or "movie",
            tmdb_title=s.get("title") or "?",
            release_year=int(s["year"]) if s.get("year") and str(s["year"]).isdigit() else None,
        )
        title = escape(s.get("title") or "?")
        await _finish_tmdb_pick(
            query,
            context,
            session_key=_PICK_SESSION_REQUEST,
            msgs_key=_PICK_MSGS_REQUEST,
            success_html=(
                f"✅ <b>Request submitted</b>\n\n"
                f"We will try to add <b>{title}</b> to the library.\n\n"
                f"<i>You can track it under My menu → My requests.</i>"
            ),
            keyboard=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📨 My requests", callback_data="watch_my_requests")],
                    [InlineKeyboardButton("« My menu", callback_data="main_menu")],
                ]
            ),
        )
        context.user_data.pop("upload_request_suggestions", None)
        return True

    if data == "watch_req_admin":
        if not Config.is_admin(user_id):
            await safe_edit_callback_message(
                query, "❌ Admin only.", parse_mode=ParseMode.HTML
            )
            return True
        await send_admin_upload_requests(update, context, edit=True)
        return True

    if data.startswith("watch_req_done:"):
        if not Config.is_admin(user_id):
            await safe_edit_callback_message(
                query, "❌ Admin only.", parse_mode=ParseMode.HTML
            )
            return True
        req_id = int(data.split(":", 1)[1])
        req = db.get_upload_request(req_id)
        if not req:
            await safe_edit_callback_message(
                query, "❌ Request not found.", parse_mode=ParseMode.HTML
            )
            return True
        db.set_upload_request_status(req_id, "done")
        title = escape(req.tmdb_title or "?")
        await safe_edit_callback_message(
            query,
            f"✅ <b>Marked done</b>\n\n{title}\n\n<i>Removed from pending queue.</i>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Watch hub", callback_data="watch_hub")]]
            ),
            parse_mode=ParseMode.HTML,
        )
        return True

    if data.startswith("watch_req_reject:"):
        if not Config.is_admin(user_id):
            await safe_edit_callback_message(
                query, "❌ Admin only.", parse_mode=ParseMode.HTML
            )
            return True
        req_id = int(data.split(":", 1)[1])
        req = db.get_upload_request(req_id)
        if not req:
            await safe_edit_callback_message(
                query, "❌ Request not found.", parse_mode=ParseMode.HTML
            )
            return True
        db.set_upload_request_status(req_id, "rejected")
        title = escape(req.tmdb_title or "?")
        await safe_edit_callback_message(
            query,
            f"❌ <b>Rejected</b>\n\n{title}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Watch hub", callback_data="watch_hub")]]
            ),
            parse_mode=ParseMode.HTML,
        )
        return True

    if data == "watch_publish_run":
        await run_watch_publish_batch(update, context, edit=True, republish=False)
        return True

    if data == "watch_refresh_catalog":
        if not Config.is_admin(user_id):
            await safe_edit_callback_message(
                query, "❌ Admin only.", parse_mode=ParseMode.HTML
            )
            return True
        await run_watch_publish_batch(
            update, context, edit=True, republish=True, post_new=False
        )
        return True

    if data == "watch_republish_run":
        await run_watch_publish_batch(
            update, context, edit=True, republish=True, post_new=True
        )
        return True

    if data == "watch_publish_fresh":
        await run_watch_publish_batch(
            update, context, edit=True, republish=True, reset_registry=True
        )
        return True

    if data == "watch_upgrade_links":
        if not Config.is_admin(user_id):
            await safe_edit_callback_message(
                query, "❌ Admin only.", parse_mode=ParseMode.HTML
            )
            return True
        await safe_edit_callback_message(
            query,
            "⏳ <b>Upgrading card buttons…</b>",
            reply_markup=None,
            parse_mode=ParseMode.HTML,
        )
        uname = await _resolve_bot_username(context)
        ok, fail = await upgrade_all_catalog_keyboards(
            context.bot, db, bot_username=uname
        )
        await safe_edit_callback_message(
            query,
            f"<b>🔗 Card buttons updated</b>\n\n"
            f"✅ {ok} upgraded · ❌ {fail} failed\n\n"
            f"Users tap ▶ Watch / Watchlist / Favorite on a card to open "
            f"@{uname or 'bot'} (works for new users after they tap Start).",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Watch hub", callback_data="watch_hub")]]
            ),
        )
        return True

    if data == "set_watch_channel_menu":
        if not Config.is_admin(user_id):
            await query.answer("Admin only", show_alert=True)
            return True
        await send_set_watch_channel_menu(update, context, edit=True)
        return True

    if data.startswith("set_watch_channel:"):
        if not Config.is_admin(user_id):
            await query.answer("Admin only", show_alert=True)
            return True
        cid = data.split(":", 1)[1]
        ch = db.set_watch_channel(cid)
        if ch:
            await query.answer("Watch channel set", show_alert=False)
        await send_set_watch_channel_menu(update, context, edit=True)
        return True

    if data.startswith("watch_fav:"):
        ct_id = int(data.split(":")[1])
        now = db.toggle_favorite(user_id, ct_id)
        await query.answer("⭐ Saved" if now else "Removed from favorites", show_alert=False)
        return True

    if data.startswith("watch_wl:"):
        ct_id = int(data.split(":")[1])
        if await _prompt_channel_deep_link(
            query, context, ct_id, None, button_hint="📋 Watchlist"
        ):
            return True
        context.user_data["watch_wl_pending_ct"] = ct_id
        lists = db.get_user_watchlists(user_id)
        if not lists:
            wl_id = db.get_or_create_default_watchlist(user_id)
            db.add_watchlist_item(user_id, wl_id, ct_id)
            await query.answer("Added to My watchlist", show_alert=True)
            return True
        keyboard = []
        for wl in lists[:8]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        wl.list_name,
                        callback_data=f"watch_wl_add:{wl.id}:{ct_id}",
                    )
                ]
            )
        keyboard.append([InlineKeyboardButton("« Cancel", callback_data="watch_hub")])
        await present_callback_ui(
            query,
            "<b>Add to watchlist</b>\n\nChoose a list:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    if data.startswith("watch_wl_add:"):
        parts = data.split(":")
        wl_id, ct_id = int(parts[1]), int(parts[2])
        if db.add_watchlist_item(user_id, wl_id, ct_id):
            await query.answer("Added to watchlist", show_alert=False)
        else:
            await query.answer("Could not add", show_alert=True)
        return True

    if data.startswith("watch_open_title:"):
        ct_id = int(data.split(":")[1])
        entries = db.get_library_browse_entries(limit=80)
        idx = next(
            (i for i, e in enumerate(entries) if e.get("content_title_id") == ct_id),
            None,
        )
        if idx is None:
            ct = db.get_content_title(ct_id)
            entries = [
                {
                    "title": (ct.tmdb_title if ct else None) or "?",
                    "content_title_id": ct_id,
                    "media_type": (ct.media_type if ct else "movie") or "movie",
                }
            ]
            idx = 0
        context.user_data["browse_titles"] = entries
        await safe_edit_callback_message(
            query,
            "Opening title…",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("▶ Open", callback_data=f"lib_idx:{idx}")]]
            ),
        )
        return True

    if data.startswith("watch_go:"):
        parts = data.split(":")
        ct_id = int(parts[1])
        season = season_from_callback(int(parts[2]))
        if await _prompt_channel_deep_link(
            query, context, ct_id, season, button_hint="▶ Watch"
        ):
            return True
        await _open_catalog_watch_picker(query, context, ct_id, season)
        return True

    if data.startswith("watch_dl:"):
        upload_id = int(data.split(":")[1])
        await _send_download_pick(query, context, upload_id)
        return True

    return False


async def _open_catalog_watch_picker(
    query, context: ContextTypes.DEFAULT_TYPE, content_title_id: int, season_number: int | None
) -> None:
    """After ▶️ Watch on a catalog card — episode/quality picker in bot."""
    import importlib

    bot_mod = importlib.import_module("bot")
    ct = db.get_content_title(content_title_id)
    title = db.display_title_for_content(ct, "?")
    entry = {
        "title": title,
        "content_title_id": content_title_id,
        "media_type": (ct.media_type if ct else "movie") or "movie",
    }
    context.user_data["browse_titles"] = [entry]
    context.user_data["watch_browse_idx"] = 0
    context.user_data["watch_slot_season"] = season_number
    uploads = db.get_library_uploads_for_content(
        content_title_id, watchable_only=True, season_number=season_number
    )
    if not uploads:
        await query.answer("No files available", show_alert=True)
        return
    mt = (ct.media_type if ct else "movie") or "movie"
    is_tv = mt in ("tv", "series")
    await query.answer()
    if is_tv:
        from watch_library import group_tv_episodes

        episodes = group_tv_episodes(uploads)
        if len(episodes) > 1:
            await bot_mod.send_watch_episode_list(
                query, context, 0, uploads=uploads
            )
            return
        if len(episodes) == 1:
            ep_key, ep_uploads = episodes[0]
            s, e = ep_key
            await bot_mod.send_watch_quality_list(
                query,
                context,
                idx=0,
                ct_id=content_title_id,
                uploads=ep_uploads,
                season=s,
                episode=e,
                back_cb=f"watch_go:{content_title_id}:{parts_season_cb(season_number)}",
                back_label="« Card",
            )
            return
    await bot_mod.send_watch_quality_list(
        query,
        context,
        idx=0,
        ct_id=content_title_id,
        uploads=uploads,
        back_cb=f"watch_go:{content_title_id}:{parts_season_cb(season_number)}",
        back_label="« Card",
    )


def parts_season_cb(season_number: int | None) -> int:
    from watch_deep_links import season_callback_value

    return season_callback_value(season_number)


async def _send_download_pick(
    query, context: ContextTypes.DEFAULT_TYPE, upload_id: int
) -> None:
    import bot as bot_mod

    await bot_mod.send_watch_pick(query, context, upload_id)


async def begin_watch_in_dm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content_title_id: int,
    season_number: int | None,
    *,
    include_welcome: bool = False,
) -> None:
    """Open watch/quality picker in private chat (from catalog deep link)."""
    import bot as bot_mod
    from watch_deep_links import season_callback_value
    from watch_library import filter_watchable_media_uploads, group_tv_episodes

    msg = update.effective_message
    if not msg:
        return
    ct = db.get_content_title(content_title_id)
    title = db.display_title_for_content(ct, "?")
    entry = {
        "title": title,
        "content_title_id": content_title_id,
        "media_type": (ct.media_type if ct else "movie") or "movie",
    }
    context.user_data["browse_titles"] = [entry]
    context.user_data["watch_browse_idx"] = 0
    context.user_data["watch_slot_season"] = season_number
    user_id = _user_id(update)
    message_prefix = None
    if include_welcome:
        message_prefix = picker_intro_for_user(user_id)
        if message_prefix:
            db.mark_user_welcomed(user_id)
    uploads = db.get_library_uploads_for_content(
        content_title_id, watchable_only=True, season_number=season_number
    )
    uploads = filter_watchable_media_uploads(uploads)
    menu_row = [[InlineKeyboardButton("« Menu", callback_data="main_menu")]]
    if not uploads:
        no_files = (
            "❌ <b>No files available</b> for this title yet.\n\n"
            "Try <b>/request</b> to ask for an upload."
        )
        if message_prefix:
            no_files = message_prefix + no_files
        await msg.reply_text(
            no_files,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(menu_row),
        )
        return
    mt = (ct.media_type if ct else "movie") or "movie"
    is_tv = mt in ("tv", "series")
    if is_tv:
        episodes = group_tv_episodes(uploads)
        context.user_data["watch_episode_keys"] = [ep_key for ep_key, _ in episodes]
        context.user_data["watch_ep_ct_id"] = content_title_id
        if len(episodes) > 1:
            await bot_mod.send_watch_episode_list(
                None,
                context,
                0,
                uploads=uploads,
                reply_message=msg,
                message_prefix=message_prefix,
            )
            return
        if len(episodes) == 1:
            ep_key, ep_uploads = episodes[0]
            s, e = ep_key
            await bot_mod.send_watch_quality_list(
                None,
                context,
                idx=0,
                ct_id=content_title_id,
                uploads=ep_uploads,
                season=s,
                episode=e,
                back_cb="watch_hub",
                back_label="« Menu",
                reply_message=msg,
                message_prefix=message_prefix,
            )
            return
    await bot_mod.send_watch_quality_list(
        None,
        context,
        idx=0,
        ct_id=content_title_id,
        uploads=uploads,
        back_cb="watch_hub",
        back_label="« Menu",
        reply_message=msg,
        message_prefix=message_prefix,
    )


async def send_watchlist_pick_dm(
    update: Update, context: ContextTypes.DEFAULT_TYPE, content_title_id: int
) -> None:
    user_id = update.effective_user.id if update.effective_user else 0
    msg = update.effective_message
    if not msg:
        return
    context.user_data["watch_wl_pending_ct"] = content_title_id
    lists = db.get_user_watchlists(user_id)
    if not lists:
        wl_id = db.get_or_create_default_watchlist(user_id)
        db.add_watchlist_item(user_id, wl_id, content_title_id)
        await msg.reply_text(
            "✅ Added to <b>My watchlist</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("📋 My watchlists", callback_data="watch_watchlists")],
                    [InlineKeyboardButton("« Menu", callback_data="main_menu")],
                ]
            ),
        )
        return
    keyboard = []
    for wl in lists[:8]:
        keyboard.append(
            [
                InlineKeyboardButton(
                    wl.list_name,
                    callback_data=f"watch_wl_add:{wl.id}:{content_title_id}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Menu", callback_data="main_menu")])
    await msg.reply_text(
        "<b>Add to watchlist</b>\n\nChoose a list:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_start_payload(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    """Deep links from catalog cards: watch_ · wl_ · fav_ · watch."""
    args = context.args or []
    if not args or not update.effective_message:
        return False
    payload = args[0]
    user_id = update.effective_user.id if update.effective_user else 0

    from watch_deep_links import parse_watch_start_payload

    parsed = parse_watch_start_payload(payload)
    if parsed:
        ct_id, season = parsed
        await begin_watch_in_dm(
            update,
            context,
            ct_id,
            season,
            include_welcome=not Config.is_admin(user_id),
        )
        return True

    if payload.startswith("wl_"):
        try:
            ct_id = int(payload.split("_", 1)[1])
        except ValueError:
            return False
        await send_watchlist_pick_dm(update, context, ct_id)
        return True

    if payload.startswith("fav_"):
        try:
            ct_id = int(payload.split("_", 1)[1])
        except ValueError:
            return False
        now = db.toggle_favorite(user_id, ct_id)
        ct = db.get_content_title(ct_id)
        label = escape(db.display_title_for_content(ct, "Title"))
        await update.effective_message.reply_text(
            f"{'⭐ Added to' if now else 'Removed from'} <b>favorites</b>: {label}",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("⭐ Favorites", callback_data="watch_favorites")],
                    [InlineKeyboardButton("« Menu", callback_data="main_menu")],
                ]
            ),
        )
        return True

    if payload in ("watch", "hub"):
        if Config.is_admin(user_id):
            await send_watch_hub_menu(update, context, edit=False)
        else:
            await send_user_main_menu(update, context, edit=False)
        return True

    return False


async def handle_watch_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int
) -> bool:
    """Handle text for watchlist name / upload request. Return True if consumed."""
    if context.user_data.pop("awaiting_watchlist_name", None):
        name = (update.message.text or "").strip()
        wl_id = db.create_user_watchlist(user_id, name)
        if wl_id:
            await update.message.reply_text(f"✅ Created watchlist <b>{escape(name)}</b>", parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text("❌ Could not create list.")
        return True

    if context.user_data.pop("awaiting_upload_request", None):
        q = (update.message.text or "").strip()
        if len(q) < 2:
            await update.message.reply_text("Send at least 2 characters.")
            return True
        await send_upload_request_tmdb_picks(update, context, q)
        return True

    if context.user_data.pop("awaiting_watchlist_tmdb", None):
        q = (update.message.text or "").strip()
        if len(q) < 2:
            await update.message.reply_text("Send at least 2 characters.")
            return True
        await send_watchlist_tmdb_picks(update, context, q)
        return True

    return False
