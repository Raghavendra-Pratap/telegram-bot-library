"""
One-time library channel setup (admin) — separate from daily ingest / browse menus.

Model:
  - Content can be indexed from any monitored channel (including messy dumps).
  - Index classifies each upload (media, course, archive, …).
  - Distribution channels are where you *publish* by type (catalog cards, delivery).
"""
from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import Config
from content_lanes import DISTRIBUTION_LANE_LABELS, LANE_LABELS, WATCH_LANE_OPTIONS, normalize_lane
from database import Database
from watch_features import _edit_or_reply, send_watch_channels_hub

logger = logging.getLogger(__name__)
db = Database()


def _ch_label(ch) -> str:
    if not ch:
        return "—"
    if ch.channel_username:
        return f"@{ch.channel_username}"
    return ch.channel_title or str(ch.channel_id)


async def send_library_setup_hub(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update

    ingest = db.get_ingest_channel()
    dist = db.list_watch_lane_assignments()

    lines = [
        "<b>⚙️ Library setup</b>",
        "<i>One-time configuration — not needed for daily use.</i>",
        "",
        "How it works:",
        "1️⃣ Index files from <b>any</b> monitored channel (dumps are fine).",
        "2️⃣ Index_bot classifies each title (media, course, archive, …).",
        "3️⃣ Publish to <b>dedicated channels</b> below by content type.",
        "",
        "<b>📤 Distribution channels</b>",
        "<i>Where catalog cards and library delivery go — per content type.</i>",
    ]
    for lane in WATCH_LANE_OPTIONS:
        label = DISTRIBUTION_LANE_LABELS.get(lane, LANE_LABELS.get(lane, lane))
        ch = dist.get(lane)
        lines.append(f"  {label}")
        lines.append(f"    → {_ch_label(ch) if ch else '<i>not set</i>'}")
    lines.extend(
        [
            "",
            "<b>📥 Historical ingest sink</b>",
            _ch_label(ingest) if ingest else "<i>Not set</i>",
            "<i>Only for forwarding old posts — not your public library.</i>",
        ]
    )

    pipeline = db.list_pipeline_upload_defaults()
    configured = sum(1 for p in pipeline if p.get("source_channel_id"))
    lines.extend(
        [
            "",
            "<b>📤 Pipeline upload targets</b>",
            f"<i>Default source channels for bulk upload jobs ({configured}/{len(pipeline)} set).</i>",
        ]
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "📤 Pipeline upload targets", callback_data="setup_pipeline"
            )
        ],
        [InlineKeyboardButton("📤 Distribution channels", callback_data="setup_watch")],
        [InlineKeyboardButton("📥 Ingest channel", callback_data="setup_ingest")],
        [InlineKeyboardButton("🔎 Discover channels", callback_data="setup_discover")],
        [
            InlineKeyboardButton(
                "⚙️ Advanced: staging defaults", callback_data="setup_staging"
            )
        ],
        [
            InlineKeyboardButton(
                "✂️ Filename prefix rules", callback_data="setup_strip"
            )
        ],
        [InlineKeyboardButton("« Admin menu", callback_data="main_menu")],
    ]
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_setup_staging_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    """Optional: mark a channel used only for one upload type (e.g. course staging)."""
    query = update.callback_query
    target = query if edit and query else update
    channels = [c for c in db.get_all_channels_registered(active_only=False) if c.is_active]
    lines = [
        "<b>⚙️ Staging channel defaults</b> <i>(optional)</i>",
        "",
        "Use this only when a channel is <b>dedicated</b> to one upload type "
        "(e.g. a course-only staging channel).",
        "",
        "If you dump mixed content randomly, leave channels on default — "
        "classification happens on each file during indexing.",
        "",
    ]
    keyboard = []
    if not channels:
        lines.append("<i>No channels registered yet.</i>")
    else:
        for ch in channels[:18]:
            lane = normalize_lane(getattr(ch, "content_lane", None))
            short = LANE_LABELS.get(lane, lane).split()[0]
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{ch.channel_title or ch.channel_id} · {short}"[:60],
                        callback_data=f"setup_lane_ch:{ch.channel_id}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton("« Setup", callback_data="setup_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_setup_staging_channel(
    update: Update, context: ContextTypes.DEFAULT_TYPE, channel_id: str, *, edit: bool = False
) -> None:
    from content_lanes import LANE_ADULT

    query = update.callback_query
    target = query if edit and query else update
    channel = db.get_channel(channel_id)
    if not channel:
        await _edit_or_reply(target, "Channel not found.", None, edit=edit)
        return
    lane = normalize_lane(getattr(channel, "content_lane", None))
    lines = [
        f"<b>{escape(channel.channel_title or 'Channel')}</b>",
        f"Staging default: <b>{escape(LANE_LABELS.get(lane, lane))}</b>",
        "",
        "Only set this if <b>all</b> new posts here are one type.",
        "Does not replace distribution channels above.",
        "",
    ]
    keyboard = [
        [
            InlineKeyboardButton("🎬 Media", callback_data=f"up_lane:{channel_id}:media"),
            InlineKeyboardButton("🎓 Course", callback_data=f"up_lane:{channel_id}:course"),
        ],
        [
            InlineKeyboardButton("📦 Archive", callback_data=f"up_lane:{channel_id}:archive"),
            InlineKeyboardButton("📱 Short", callback_data=f"up_lane:{channel_id}:shortform"),
        ],
        [
            InlineKeyboardButton(
                "🔒 Adult", callback_data=f"up_lane:{channel_id}:{LANE_ADULT}"
            ),
        ],
        [InlineKeyboardButton("« Staging list", callback_data="setup_staging")],
    ]
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_filename_strip_rules_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    """Admin: prefixes/strings stripped before title parsing."""
    from name_parser import NameParser, apply_filename_strip_rules

    query = update.callback_query
    target = query if edit and query else update
    rules = db.list_filename_strip_rules(active_only=False)
    lines = [
        "<b>✂️ Filename prefix rules</b>",
        "",
        "Common uploader tags (e.g. <code>[@Anime_RTX] </code>) are removed "
        "from filenames <b>before</b> title parsing and TMDB lookup.",
        "",
        "<i>Include trailing spaces if the prefix has them.</i>",
        "",
    ]
    keyboard = []
    if not rules:
        lines.append("<i>No rules yet — tap Add prefix below.</i>")
    else:
        lines.append(f"<b>{len(rules)}</b> rule(s):")
        for rule in rules[:20]:
            pat = escape(rule["pattern"])
            if len(pat) > 36:
                pat = pat[:33] + "…"
            note = f" — {escape(rule['note'])}" if rule.get("note") else ""
            tag = "" if rule.get("is_active", True) else " ⏸"
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🗑 {pat}{tag}"[:60],
                        callback_data=f"setup_strip_del:{rule['id']}",
                    )
                ]
            )
            lines.append(f"• <code>{escape(rule['pattern'])}</code>{note}")
        if len(rules) > 20:
            lines.append(f"<i>…and {len(rules) - 20} more in the portal.</i>")

    sample = context.user_data.get("strip_preview_sample")
    if sample:
        stripped = apply_filename_strip_rules(sample)
        parsed = NameParser().parse_name(sample)
        title = parsed.get("show_name") or parsed.get("name") or "?"
        lines.extend(
            [
                "",
                "<b>Preview</b>",
                f"File: <code>{escape(sample[:120])}</code>",
                f"After strip: <code>{escape(stripped[:120])}</code>",
                f"Parsed title: <b>{escape(title)}</b>",
            ]
        )

    keyboard.append(
        [InlineKeyboardButton("➕ Add prefix", callback_data="setup_strip_add")]
    )
    if not sample:
        keyboard.append(
            [InlineKeyboardButton("🧪 Try sample filename", callback_data="setup_strip_test")]
        )
    else:
        keyboard.append(
            [InlineKeyboardButton("🔄 Clear preview", callback_data="setup_strip_clear")]
        )
    keyboard.append([InlineKeyboardButton("« Setup", callback_data="setup_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def handle_setup_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    if not data.startswith("setup_"):
        return False
    if not Config.is_admin(user_id):
        return False

    if data == "setup_hub":
        await send_library_setup_hub(update, context, edit=True)
        return True
    from pipeline_setup import handle_pipeline_setup_callback

    if await handle_pipeline_setup_callback(data, update, context, user_id):
        return True
    if data == "setup_watch":
        if context.user_data.get("setup_return") != "setup_pipeline":
            context.user_data["setup_return"] = "setup_hub"
        await send_watch_channels_hub(update, context, edit=True)
        return True
    if data == "setup_ingest":
        import bot as bot_mod

        await bot_mod.send_set_ingest_channel_menu(
            update, context, edit=True, back_callback="setup_hub"
        )
        return True
    if data in ("setup_staging", "setup_lanes"):
        await send_setup_staging_menu(update, context, edit=True)
        return True
    if data.startswith("setup_lane_ch:"):
        channel_id = data.split(":", 1)[1]
        await send_setup_staging_channel(update, context, channel_id, edit=True)
        return True
    if data == "setup_discover":
        import bot as bot_mod

        context.user_data["setup_return"] = "setup_hub"
        await bot_mod.run_channel_discovery(update, context, edit=True)
        return True
    if data == "setup_strip":
        await send_filename_strip_rules_menu(update, context, edit=True)
        return True
    if data == "setup_strip_add":
        context.user_data["pending_strip_rule_add"] = True
        await _edit_or_reply(
            update.callback_query,
            "➕ <b>Add filename prefix</b>\n\n"
            "Send the exact text to strip from the <b>start</b> of filenames.\n\n"
            "Example:\n<code>[@Anime_RTX] </code>\n\n"
            "<i>Include spaces and brackets exactly as they appear in files.</i>",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data="setup_strip")]]
            ),
            edit=True,
        )
        return True
    if data == "setup_strip_test":
        context.user_data["pending_strip_rule_test"] = True
        await _edit_or_reply(
            update.callback_query,
            "🧪 <b>Test filename</b>\n\n"
            "Send a sample filename to preview stripping + parsed title.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data="setup_strip")]]
            ),
            edit=True,
        )
        return True
    if data == "setup_strip_clear":
        context.user_data.pop("strip_preview_sample", None)
        await send_filename_strip_rules_menu(update, context, edit=True)
        return True
    if data.startswith("setup_strip_del:"):
        rule_id = int(data.split(":", 1)[1])
        from name_parser import invalidate_filename_strip_rules_cache

        if db.delete_filename_strip_rule(rule_id):
            invalidate_filename_strip_rules_cache()
        await send_filename_strip_rules_menu(update, context, edit=True)
        return True
    return False
