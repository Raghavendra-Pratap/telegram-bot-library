"""
Admin UI: upload jobs, duplicate review, course vault, channel content lanes.
"""
from __future__ import annotations

import logging
import os
from html import escape
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config import Config
from content_lanes import LANE_COURSE, LANE_LABELS, VALID_LANES, normalize_lane
from database import Database
from watch_features import _edit_or_reply

logger = logging.getLogger(__name__)
db = Database()
_ROOT = Path(__file__).resolve().parent
TELEGRAM_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB

UPLOAD_WIZARD_LANES = ("course", "media", "archive", "shortform", "adult")


def _collection_field_label(lane: str) -> str:
    return "Course" if normalize_lane(lane) == LANE_COURSE else "Collection"


def _clear_upload_wizard(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("upload_wizard", None)
    context.user_data.pop("awaiting_upload_csv", None)


async def _scan_folder_with_live_progress(
    update: Update,
    folder: Path,
) -> tuple[list[dict], int, int]:
    """Run scan_folder_for_plan in a thread with Telegram progress edits."""
    import asyncio
    import time

    from telegram_flood import flood_bot_edit_message_text
    from upload_planning import format_scan_progress_message, scan_folder_for_plan

    status = await update.message.reply_text(
        format_scan_progress_message({"phase": "listing", "found": 0}, folder_label=folder.name),
        parse_mode=ParseMode.HTML,
    )
    loop = asyncio.get_running_loop()
    last_edit = 0.0
    min_interval = 0.85

    def on_progress(info: dict) -> None:
        nonlocal last_edit
        now = time.monotonic()
        if info.get("phase") != "done" and now - last_edit < min_interval:
            return
        last_edit = now
        text = format_scan_progress_message(info, folder_label=str(folder.name))

        async def _edit() -> None:
            try:
                await flood_bot_edit_message_text(
                    update.get_bot(),
                    status.chat_id,
                    status.message_id,
                    text,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug("scan progress edit skipped: %s", e)

        asyncio.run_coroutine_threadsafe(_edit(), loop)

    rows, new, dup = await asyncio.to_thread(
        scan_folder_for_plan, folder, on_progress=on_progress
    )
    return rows, new, dup, status


def _upload_run_state_key(job_id: int) -> str:
    return f"upload_job_run_{job_id}"


def _upload_run_cancelled(application, job_id: int) -> bool:
    state = application.bot_data.get(_upload_run_state_key(job_id)) or {}
    return bool(state.get("active") and state.get("cancel"))


def request_upload_job_stop(application, job_id: int) -> bool:
    state = application.bot_data.get(_upload_run_state_key(job_id))
    if state and state.get("active") and not state.get("cancel"):
        state["cancel"] = True
        return True
    return False


def _upload_progress_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⏹ Stop upload", callback_data=f"up_job_stop:{job_id}")]]
    )


def _item_local_size(item) -> int | None:
    if item.file_size:
        try:
            return int(item.file_size)
        except Exception:
            return None
    lp = item.local_path
    if not lp:
        return None
    try:
        p = Path(lp)
        if p.is_file():
            return int(p.stat().st_size)
    except Exception:
        return None
    return None


def _channel_label(channel_id: str) -> str:
    ch = db.get_channel(channel_id)
    if not ch:
        return channel_id
    if ch.channel_username:
        return f"@{ch.channel_username}"
    return ch.channel_title or channel_id


def _scan_error_message(exc: Exception, folder: Path) -> str:
    """User-facing scan error text with clearer timeout guidance."""
    msg = (str(exc) or "").strip()
    low = msg.lower()
    if "timed out" in low or "timeout" in low:
        return (
            "❌ Scan request timed out while talking to Telegram.\n\n"
            "<i>Your path format looks fine; this is usually network/load related.</i>\n"
            "Please send the <b>same path</b> again."
        )
    return (
        f"❌ {escape(msg[:200])}\n\n"
        "<i>Tip: paste the path without quotes, e.g.</i>\n"
        f"<code>{escape(str(folder))}</code>"
    )


def _telethon_ready() -> tuple[bool, str]:
    api_id = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()
    if not api_id or not api_hash:
        return False, "Set API_ID and API_HASH in .env (Telethon)."
    session = Path(os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"))
    if not session.is_absolute():
        session = _ROOT / session
    if not session.is_file():
        return False, "Run telethon_login.py once to create a session file."
    return True, str(session)


def format_job_progress(job_id: int, prog: dict) -> str:
    phase = prog.get("phase", "")
    total = prog.get("total", 0)
    done = prog.get("done", 0)
    ok = prog.get("ok", 0)
    fail = prog.get("fail", 0)
    current = prog.get("current", "")
    lines = [
        f"<b>▶️ Upload job #{job_id}</b>",
        f"Phase: <code>{escape(str(phase))}</code>",
        f"Progress: <b>{done}</b> / <b>{total}</b> · OK <b>{ok}</b> · fail <b>{fail}</b>",
    ]
    if current:
        lines.append(f"Current: <code>{escape(str(current)[:60])}</code>")
    lines.append("\n<i>Keep bot.py running so channel posts get indexed.</i>")
    return "\n".join(lines)


async def send_new_job_lane_picker(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    _clear_upload_wizard(context)
    target = update.callback_query if edit and update.callback_query else update
    lines = [
        "<b>➕ New upload job</b>",
        "",
        "Pick a <b>content type</b> for this batch. This controls how files are indexed "
        "after they land in the target channel.",
    ]
    keyboard = []
    for lane in UPLOAD_WIZARD_LANES:
        keyboard.append(
            [
                InlineKeyboardButton(
                    LANE_LABELS.get(lane, lane),
                    callback_data=f"up_wiz_lane:{lane}",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_new_job_source_picker(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lane: str, *, edit: bool = False
) -> None:
    lane = normalize_lane(lane)
    context.user_data["upload_wizard"] = {"lane": lane, "step": "source"}
    target = update.callback_query if edit and update.callback_query else update
    lane_label = LANE_LABELS.get(lane, lane)
    lines = [
        f"<b>New {lane_label} job</b>",
        "",
        "How should we build the file list?",
        "",
        "<b>📁 Folder on this device</b> — scan videos/PDFs under a path "
        "(bot must run on the same machine as the files).",
        "",
        "<b>📄 File path(s) on this device</b> — upload one file quickly, or send multiple "
        "absolute paths (one per line).",
        "",
        "<b>📄 CSV manifest</b> — paste or send a file with filenames and optional "
        "<code>local_path</code> columns.",
    ]
    keyboard = [
        [InlineKeyboardButton("📁 Scan folder", callback_data=f"up_wiz_src:folder:{lane}")],
        [InlineKeyboardButton("📄 Use file path(s)", callback_data=f"up_wiz_src:file:{lane}")],
        [InlineKeyboardButton("📄 CSV manifest", callback_data=f"up_wiz_src:csv:{lane}")],
        [InlineKeyboardButton("« Back", callback_data="up_new")],
    ]
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_folder_check_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    context.user_data["upload_wizard"] = {"step": "check_folder"}
    target = update.callback_query if edit and update.callback_query else update
    lines = [
        "<b>🔍 Check folder duplicates</b>",
        "",
        "Send the <b>full folder path</b> on this device.",
        "",
        "Paste without quotes. Example (Termux):",
        "<code>/storage/emulated/0/Download/MyCourse</code>",
    ]
    keyboard = [[InlineKeyboardButton("« Cancel", callback_data="up_hub")]]
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


def _plan_preview_payload(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lane: str,
    rows: list[dict],
    new: int,
    dup: int,
    folder: str | None = None,
    create_name: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    from upload_planning import format_plan_summary

    wiz = context.user_data.setdefault("upload_wizard", {})
    wiz.update(
        {
            "lane": normalize_lane(lane),
            "step": "confirm",
            "folder": folder,
            "planned_rows": rows,
            "rows_count": len(rows),
            "new": new,
            "dup": dup,
            "default_name": create_name,
        }
    )
    text = format_plan_summary(
        total=len(rows),
        new=new,
        dup=dup,
        lane=lane,
        sample_rows=rows,
    )
    if folder:
        text += f"\n\nFolder: <code>{escape(folder)}</code>"
    keyboard: list[list[InlineKeyboardButton]] = []
    if create_name:
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"✅ Create job «{create_name[:28]}»",
                    callback_data="up_wiz_create",
                )
            ]
        )
        keyboard.append(
            [
                InlineKeyboardButton(
                    "✏️ Custom job name",
                    callback_data="up_wiz_name",
                )
            ]
        )
    keyboard.append([InlineKeyboardButton("« Cancel", callback_data="up_hub")])
    return text, InlineKeyboardMarkup(keyboard)


async def _reply_plan_preview(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    lane: str,
    rows: list[dict],
    new: int,
    dup: int,
    folder: str | None = None,
    create_name: str | None = None,
    status_message=None,
) -> None:
    """Show plan preview; prefer editing the scan status message (no delete)."""
    from telegram.error import BadRequest, NetworkError, TimedOut
    from telegram_flood import flood_bot_edit_message_text

    text, markup = _plan_preview_payload(
        context,
        lane=lane,
        rows=rows,
        new=new,
        dup=dup,
        folder=folder,
        create_name=create_name,
    )
    if status_message is not None:
        try:
            bot = status_message.get_bot()
            await flood_bot_edit_message_text(
                bot,
                status_message.chat_id,
                status_message.message_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=markup,
            )
            return
        except (TimedOut, NetworkError) as e:
            logger.warning("Plan preview edit timed out, sending new message: %s", e)
        except BadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.debug("Plan preview edit: %s", e)
            else:
                return
        except Exception as e:
            logger.debug("Plan preview edit failed: %s", e)
    try:
        await update.message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
        )
    except (TimedOut, NetworkError) as e:
        logger.warning("Plan preview reply timed out: %s", e)


async def _create_job_from_wizard_state(
    name: str,
    wiz: dict,
    *,
    user_id: int,
) -> tuple[int | None, dict]:
    import asyncio

    from upload_planning import create_job_from_rows

    lane = normalize_lane(wiz.get("lane", LANE_COURSE))
    course_title = wiz.get("course_title") or name
    rows = wiz.get("planned_rows")
    if not rows:
        folder = wiz.get("folder")
        if not folder:
            raise ValueError("No folder — start again from Upload pipeline.")
        from upload_planning import scan_folder_for_plan

        rows, _new, _dup = await asyncio.to_thread(
            scan_folder_for_plan, Path(folder)
        )
    if not rows:
        raise ValueError("No supported files found.")
    return await asyncio.to_thread(
        create_job_from_rows,
        name,
        rows,
        content_lane=lane,
        course_title=course_title,
        created_by=user_id,
    )


async def _present_job_screen(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    message_id: int,
    job_id: int,
) -> None:
    import asyncio

    from telegram_flood import flood_bot_edit_message_text

    await asyncio.to_thread(db.recheck_upload_job_library_matches, job_id)
    text, markup = build_job_detail_view(job_id, application=context.application)
    await flood_bot_edit_message_text(
        context.bot,
        chat_id,
        message_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


async def create_wizard_job(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    name: str,
) -> None:
    wiz = context.user_data.get("upload_wizard") or {}
    user_id = update.effective_user.id if update.effective_user else 0
    status = await update.message.reply_text("⏳ Saving job to database…")

    try:
        job_id, info = await _create_job_from_wizard_state(
            name, wiz, user_id=user_id
        )
    except Exception as e:
        logger.exception("create_wizard_job failed")
        await status.edit_text(f"❌ Failed: {escape(str(e)[:200])}", parse_mode=ParseMode.HTML)
        _clear_upload_wizard(context)
        return

    _clear_upload_wizard(context)
    if not job_id:
        await status.edit_text("❌ Could not create job.")
        return
    try:
        await _present_job_screen(
            context, status.chat_id, status.message_id, job_id
        )
    except Exception:
        logger.exception("present job screen failed")
        await status.edit_text(f"✅ Created job #{job_id} — open Upload pipeline → Jobs.")


async def create_wizard_job_from_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    name: str,
) -> None:
    """Create job from inline confirm (uses callback message for status)."""
    query = update.callback_query
    if not query or not query.message:
        return
    wiz = context.user_data.get("upload_wizard") or {}
    user_id = update.effective_user.id if update.effective_user else 0
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    from telegram_flood import flood_bot_edit_message_text

    await flood_bot_edit_message_text(
        context.bot, chat_id, message_id, "⏳ Saving job to database…", parse_mode=ParseMode.HTML
    )
    try:
        job_id, info = await _create_job_from_wizard_state(
            name, wiz, user_id=user_id
        )
    except Exception as e:
        logger.exception("create_wizard_job_from_callback failed")
        await flood_bot_edit_message_text(
            context.bot,
            chat_id,
            message_id,
            f"❌ Failed: {escape(str(e)[:200])}",
            parse_mode=ParseMode.HTML,
        )
        _clear_upload_wizard(context)
        return

    _clear_upload_wizard(context)
    if not job_id:
        await flood_bot_edit_message_text(
            context.bot, chat_id, message_id, "❌ Could not create job."
        )
        return
    await _present_job_screen(context, chat_id, message_id, job_id)


def _wizard_job_next_steps(job_id: int) -> str:
    job = db.get_upload_job(job_id)
    if job and job.target_channel_id:
        return "Next: Upload all new → Start upload"
    return (
        "Next: set source in Library setup → Pipeline upload targets, "
        "or pick channel on the job → Upload all new → Start upload"
    )


async def send_upload_hub(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    dupes = db.count_duplicate_holds()
    jobs = db.list_upload_jobs(limit=5)
    courses = db.list_course_titles(limit=5)
    lines = [
        "<b>📤 Upload pipeline</b>",
        "",
        "Plan bulk uploads in-bot: scan a folder or CSV, review duplicates, "
        "upload via Telethon, and index automatically.",
        "",
        f"⚠️ Duplicates awaiting review: <b>{dupes}</b>",
        f"📋 Recent jobs: <b>{len(jobs)}</b>",
        f"🎓 Courses indexed: <b>{len(courses)}</b>",
        "",
        "<b>Workflow</b>",
        "1️⃣ <b>New upload job</b> — pick type → folder or CSV",
        "2️⃣ Review job → <b>Upload all new</b> (source from Pipeline setup)",
        "3️⃣ <b>Start upload</b> (keep bot running for indexing)",
    ]
    import bot_busy

    if bot_busy.upload_job_active(context.application):
        lines.append("")
        lines.append(
            "<i>▶️ Upload in progress — you can still scan folders and create new jobs. "
            "Only one Telethon upload runs at a time.</i>"
        )
    keyboard = [
        [InlineKeyboardButton("➕ New upload job", callback_data="up_new")],
        [InlineKeyboardButton("📋 Upload jobs", callback_data="up_jobs")],
        [
            InlineKeyboardButton("🔍 Check folder dupes", callback_data="up_check"),
            InlineKeyboardButton("⚠️ Duplicates", callback_data="up_dupes"),
        ],
        [
            InlineKeyboardButton("🎓 Course vault", callback_data="up_course"),
            InlineKeyboardButton("🗄 All vaults", callback_data="up_vault"),
        ],
        [
            InlineKeyboardButton("📊 Pipeline status", callback_data="up_pipe_status"),
            InlineKeyboardButton("⚙️ Setup targets", callback_data="setup_pipeline"),
        ],
        [InlineKeyboardButton("« Admin menu", callback_data="main_menu")],
    ]
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_pipeline_status(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    from pipeline_status import get_pipeline_readiness

    query = update.callback_query
    target = query if edit and query else update
    data = get_pipeline_readiness(db=db)
    cfg = data.get("config") or {}
    lines = [
        "<b>📊 Pipeline status</b>",
        "",
        "<b>Configuration</b>",
        f"Classify on ingest: <code>{'on' if cfg.get('classify_ingest') else 'off'}</code>",
        f"Auto-route to buckets: <code>{'on' if cfg.get('auto_route') else 'off'}</code>",
        f"Auto-publish watch cards: <code>{'on' if cfg.get('auto_publish_watch') else 'off'}</code>",
        "",
        "<b>Readiness</b>",
    ]
    for chk in data.get("checks") or []:
        if chk.get("ok") is True:
            mark = "✅"
        elif chk.get("ok") is False:
            mark = "❌"
        else:
            mark = "➖"
        lines.append(f"{mark} {escape(chk.get('label', '?'))}")
        if chk.get("ok") is False and chk.get("hint"):
            lines.append(f"   <i>{escape(chk['hint'])}</i>")

    lines.extend(
        [
            "",
            f"Duplicate holds: <b>{data.get('duplicate_holds', 0)}</b>",
            f"Pending route queue: <b>{data.get('route_pending', 0)}</b>",
        ]
    )
    jobs = data.get("recent_jobs") or []
    if jobs:
        lines.append("")
        lines.append("<b>Recent jobs</b>")
        for j in jobs[:5]:
            tgt = "✓ source" if j.get("target_channel_id") else "no source"
            lines.append(
                f"• #{j['id']} {escape(j['name'][:32])} "
                f"<code>{escape(j['status'])}</code> · {escape(j['lane'])} · {tgt}"
            )

    keyboard = [
        [InlineKeyboardButton("⚙️ Pipeline targets", callback_data="setup_pipeline")],
    ]
    if data.get("route_pending", 0) > 0:
        keyboard.insert(
            0,
            [
                InlineKeyboardButton(
                    "▶️ Run route queue", callback_data="up_pipe_route_run"
                )
            ],
        )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_jobs_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    jobs = db.list_upload_jobs(limit=15)
    lines = ["<b>📋 Upload jobs</b>", ""]
    keyboard = []
    if not jobs:
        lines.append("<i>No jobs yet — use upload_planner.py or send a CSV.</i>")
    else:
        for j in jobs:
            summary = db.get_upload_job_summary(j.id)
            dec = summary.get("decisions", {})
            label = f"#{j.id} {j.name[:28]} ({j.status}) · {summary.get('total', 0)} files"
            keyboard.append(
                [InlineKeyboardButton(label, callback_data=f"up_job:{j.id}")]
            )
            lines.append(
                f"• <b>#{j.id}</b> {escape(j.name)} — <code>{escape(j.status)}</code> "
                f"({summary.get('total', 0)} items, upload={dec.get('upload', 0)}, skip={dec.get('skip', 0)})"
            )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


def _format_job_item_line(it, *, lib_names: dict[int, str] | None = None) -> str:
    """One planned file with new vs in-library label."""
    title = escape(it.lesson_title or it.file_name)
    names = lib_names or {}
    if it.duplicate_of_upload_id:
        uid = int(it.duplicate_of_upload_id)
        match = escape(names.get(uid) or "")
        lib = f"<b>already indexed</b> · library <code>#{uid}</code>"
        if match:
            lib += f" · <i>{match}</i>"
        flag = "⚠️"
    elif it.item_status == "indexed":
        lib = "<b>indexed</b> (this job)"
        flag = "✔️"
    elif it.item_status == "uploaded":
        lib = "<b>uploaded</b> (index pending)"
        flag = "📤"
    else:
        lib = "<b>new</b> (not in library)"
        flag = "✅"
    return (
        f"{flag} {it.sequence}. {title}\n"
        f"   {lib} · <code>{escape(it.decision)}</code> · <code>{escape(it.item_status)}</code>"
    )


def build_job_detail_view(
    job_id: int, *, application=None
) -> tuple[str, InlineKeyboardMarkup | None]:
    job = db.get_upload_job(job_id)
    if not job:
        return "Job not found.", None
    db.refresh_upload_job_status(job_id)
    job = db.get_upload_job(job_id)
    summary = db.get_upload_job_summary(job_id)
    st = summary.get("statuses") or {}
    dec = summary.get("decisions", {})
    all_items = db.get_upload_job_items(job_id)
    dup_items = [it for it in all_items if it.duplicate_of_upload_id]
    new_items = [it for it in all_items if not it.duplicate_of_upload_id]
    lib_names = db.map_upload_display_names(
        [int(it.duplicate_of_upload_id) for it in dup_items if it.duplicate_of_upload_id]
    )
    dup_total = len(dup_items)
    dup_upload = sum(
        1 for it in dup_items if it.decision in ("upload", "force")
    )
    dup_skip = sum(1 for it in dup_items if it.decision == "skip")
    new_count = len(new_items)
    with_path = sum(1 for it in all_items if it.local_path)
    oversize = sum(
        1
        for it in all_items
        if it.decision in ("upload", "force")
        and it.local_path
        and (_item_local_size(it) or 0) > TELEGRAM_MAX_UPLOAD_BYTES
    )
    uploadable = sum(
        1
        for it in all_items
        if it.decision in ("upload", "force") and it.local_path
    )
    source_label = (
        _channel_label(job.target_channel_id) if job.target_channel_id else "not set"
    )
    coll_label = _collection_field_label(job.content_lane)
    lines = [
        f"<b>Job #{job.id}</b> — {escape(job.name)}",
        f"Status: <code>{escape(job.status)}</code> · Lane: <code>{escape(job.content_lane)}</code>",
        f"Source channel: <b>{escape(source_label)}</b>",
        f"{coll_label}: <b>{escape(job.course_title or job.name)}</b>",
        "",
        f"Items <b>{summary.get('total', 0)}</b> · "
        f"upload={dec.get('upload', 0)} force={dec.get('force', 0)} skip={dec.get('skip', 0)}",
        f"planned={st.get('planned', 0)} uploaded={st.get('uploaded', 0)} "
        f"indexed={st.get('indexed', 0)} failed={st.get('failed', 0)}",
        f"Library check: <b>{new_count}</b> new · <b>{dup_total}</b> already indexed "
        f"(skip: <b>{dup_skip}</b> · re-upload: <b>{dup_upload}</b>)",
        "<i>✅ new · ⚠️ in library → <b>Skip duplicate</b> or <b>Upload anyway</b></i>",
        f"On-disk: <b>{with_path}</b>/{summary.get('total', 0)} "
        f"(ready: <b>{uploadable}</b>)",
        "",
        "<i>Buttons:</i>",
        "📡 <b>Change source</b> — override pipeline default for this job",
        "▶️ <b>Start upload</b> — Telethon sends files to source channel",
        "Skip duplicate / Upload anyway — for files already in library",
        "🔄 Refresh — re-check library + reload this screen",
        "",
    ]
    will_upload = dec.get("upload", 0) + dec.get("force", 0)
    if will_upload and uploadable == 0:
        lines.append(
            "⚠️ No local paths — add <code>local_path</code> in CSV or scan folder on this machine."
        )
    if oversize:
        lines.append(
            f"⚠️ <b>{oversize}</b> file(s) are over Telegram's 4 GB limit and will be skipped."
        )
    max_per_section = 10
    if dup_items:
        lines.append(f"<i>Already in library ({dup_total}):</i>")
        for it in dup_items[:max_per_section]:
            lines.append(_format_job_item_line(it, lib_names=lib_names))
        if dup_total > max_per_section:
            lines.append(f"<i>… +{dup_total - max_per_section} more in library</i>")
    if new_items:
        lines.append(f"<i>New ({new_count}):</i>")
        for it in new_items[:max_per_section]:
            lines.append(_format_job_item_line(it, lib_names=lib_names))
        if new_count > max_per_section:
            lines.append(f"<i>… +{new_count - max_per_section} more new</i>")
    if not dup_items and not new_items:
        lines.append("<i>No items in this job.</i>")
    elif dup_total == 0 and job.target_channel_id and summary.get("total", 0) > 0:
        lines.append(
            "<i>Files visible in the source channel but still “new” here usually means "
            "they were not indexed in the library DB yet (e.g. upload finished while DB was locked). "
            "Keep the bot running, then tap Refresh — or run channel ingest from the admin menu.</i>"
        )
    ready, _ = _telethon_ready()
    if not ready:
        lines.append("\n⚠️ Telethon not ready — run <code>python telethon_login.py</code>")
    if application is not None:
        from upload_job_queue import status_line_html

        qline = status_line_html(application, job_id)
        if qline:
            lines.extend(["", qline])
    keyboard = [
        [
            InlineKeyboardButton(
                "📡 Change source channel", callback_data=f"up_job_ch:{job_id}:0"
            ),
        ],
        [
            InlineKeyboardButton("Skip duplicate", callback_data=f"up_job_skip:{job_id}"),
            InlineKeyboardButton("Upload anyway", callback_data=f"up_job_anyway:{job_id}"),
        ],
    ]
    if job.target_channel_id and will_upload and ready:
        keyboard.insert(
            1,
            [InlineKeyboardButton("▶️ Start upload", callback_data=f"up_job_run:{job_id}")],
        )
    keyboard.append(
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"up_job:{job_id}")]
    )
    keyboard.append([InlineKeyboardButton("« Jobs", callback_data="up_jobs")])
    return "\n".join(lines), InlineKeyboardMarkup(keyboard)


async def send_job_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_id: int,
    *,
    edit: bool = False,
    recheck_library: bool = True,
) -> None:
    import asyncio

    query = update.callback_query
    target = query if edit and query else update
    if recheck_library:
        await asyncio.to_thread(db.recheck_upload_job_library_matches, job_id)
    text, markup = build_job_detail_view(job_id, application=context.application)
    await _edit_or_reply(target, text, markup, edit=edit)


async def send_job_channel_picker(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_id: int,
    page: int = 0,
    query: str | None = None,
    *,
    edit: bool = False,
) -> None:
    from channel_picker import build_channel_picker

    target = update.callback_query if edit and update.callback_query else update
    channels = db.get_channels_bot_can_post(active_only=True)
    title = (
        f"<b>Source channel for job #{job_id}</b>\n\n"
        "Override the pipeline default for this job only (bot must be admin)."
    )

    def label_fn(ch):
        lane = normalize_lane(getattr(ch, "content_lane", None))
        return f"{ch.channel_title or ch.channel_username or ch.channel_id} · {lane}"[:60]

    text, markup = build_channel_picker(
        channels,
        page=page,
        query=query,
        callback_prefix=f"upjch{job_id}",
        pick_prefix=f"up_job_target:{job_id}",
        label_fn=label_fn,
        back_callback=f"up_job:{job_id}",
        back_label="« Job",
        search_callback=f"up_job_ch_search:{job_id}",
        title_line=title,
    )
    await _edit_or_reply(target, text, markup, edit=edit)


async def _answer_upload_callback(
    query, text: str, *, show_alert: bool = False
) -> None:
    if not query:
        return
    from telegram.error import BadRequest

    from telegram_flood import flood_answer_callback

    try:
        await flood_answer_callback(query, text=text, show_alert=show_alert)
    except BadRequest:
        pass


async def start_upload_job_background(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    job_id: int,
) -> None:
    """Queue Telethon bulk upload as an exclusive background job."""
    from telegram.error import BadRequest

    from upload_job_queue import dequeue_slot, enqueue_slot, queue_contains, queue_position

    ready, session_or_msg = _telethon_ready()
    query = update.callback_query
    if not ready:
        await _answer_upload_callback(query, session_or_msg, show_alert=True)
        return

    app = context.application

    if context.user_data.get(f"upload_job_running_{job_id}"):
        await _answer_upload_callback(
            query, f"Upload job #{job_id} is already running.", show_alert=True
        )
        return

    if queue_contains(app, job_id):
        pos = queue_position(app, job_id) or 1
        await _answer_upload_callback(
            query,
            f"Job #{job_id} is already in the upload queue (position {pos}).",
            show_alert=True,
        )
        return

    job = db.get_upload_job(job_id)
    if not job:
        await _answer_upload_callback(query, "Job not found.", show_alert=True)
        return
    if not job.target_channel_id:
        await _answer_upload_callback(
            query, "Set a source channel first (📡 Change source channel).", show_alert=True
        )
        return

    items = db.get_upload_job_items(job_id)
    oversize = sum(
        1
        for it in items
        if it.decision in ("upload", "force")
        and it.local_path
        and (_item_local_size(it) or 0) > TELEGRAM_MAX_UPLOAD_BYTES
    )
    uploadable = sum(
        1
        for it in items
        if it.decision in ("upload", "force") and it.local_path
    )
    if uploadable == 0:
        await _answer_upload_callback(
            query,
            "No files ready to upload (need local paths and upload/force decision).",
            show_alert=True,
        )
        return
    if uploadable - oversize <= 0:
        await _answer_upload_callback(
            query,
            "All selected files are over Telegram's 4 GB upload limit.",
            show_alert=True,
        )
        return

    chat_id = message_id = None
    if query and query.message:
        chat_id = query.message.chat_id
        message_id = query.message.message_id
    elif update.effective_chat:
        chat_id = update.effective_chat.id

    if chat_id is None:
        await _answer_upload_callback(
            query,
            "Open this job in a private chat with the bot, then tap Start upload.",
            show_alert=True,
        )
        return

    import bot_busy

    was_busy = bot_busy.exclusive_job_running(app) or bot_busy.upload_job_active(app)
    pos = await enqueue_slot(app, job_id, chat_id, message_id or 0)
    logger.info(
        "Upload job #%s enqueued (position %s, busy=%s, uploadable=%s)",
        job_id,
        pos,
        was_busy,
        uploadable,
    )

    if was_busy or pos > 1:
        await _answer_upload_callback(
            query,
            f"⏳ Job #{job_id} queued (position {pos}). "
            "It will start after the current upload finishes.",
            show_alert=True,
        )
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⏳ <b>Upload job #{job_id}</b> queued "
                    f"(position <b>{pos}</b>).\n"
                    "<i>Keep the bot running — it starts automatically.</i>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.debug("queued upload notice: %s", e)
    else:
        await _answer_upload_callback(query, "▶️ Upload queued — starting…")
        if query and query.message and message_id:
            try:
                await query.message.edit_reply_markup(_upload_progress_keyboard(job_id))
            except BadRequest:
                pass

    run_key = _upload_run_state_key(job_id)
    progress_chat_id = chat_id
    progress_message_id = message_id

    async def _job() -> None:
        from bot_busy import UPLOAD_ACTIVE_KEY
        from telegram_flood import flood_bot_edit_message_text

        nonlocal progress_message_id

        context.user_data[f"upload_job_running_{job_id}"] = True
        app.bot_data[UPLOAD_ACTIVE_KEY] = job_id
        app.bot_data[run_key] = {"active": True, "cancel": False}
        prog = {"phase": "starting", "total": 0, "done": 0, "ok": 0, "fail": 0}
        progress_kb = _upload_progress_keyboard(job_id)

        if not progress_message_id:
            try:
                msg = await context.bot.send_message(
                    chat_id=progress_chat_id,
                    text=format_job_progress(job_id, prog),
                    parse_mode=ParseMode.HTML,
                    reply_markup=progress_kb,
                )
                progress_message_id = msg.message_id
            except Exception as e:
                logger.warning("Could not open progress message for job %s: %s", job_id, e)

        async def on_progress(p: dict) -> None:
            prog.update(p)
            if not progress_message_id:
                return
            try:
                await flood_bot_edit_message_text(
                    context.bot,
                    progress_chat_id,
                    progress_message_id,
                    format_job_progress(job_id, prog),
                    parse_mode=ParseMode.HTML,
                    reply_markup=progress_kb,
                )
            except Exception as e:
                logger.debug("job progress edit: %s", e)

        try:
            import asyncio

            from upload_db_defer import flush_pending_job_marks, get_pending_marks
            from upload_job_runner import run_upload_job

            api_id = int(os.getenv("API_ID", "").strip())
            api_hash = os.getenv("API_HASH", "").strip()
            pending = get_pending_marks(app)
            result = await run_upload_job(
                job_id=job_id,
                session_path=Path(session_or_msg),
                api_id=api_id,
                api_hash=api_hash,
                delay_s=3.0,
                on_progress=on_progress,
                cancel_check=lambda: _upload_run_cancelled(app, job_id),
                pending_marks=pending,
                defer_db_writes=True,
            )
            prog["phase"] = "stopped" if result.get("stopped") else "done"
            prog["ok"] = result.get("ok", 0)
            prog["fail"] = result.get("fail", 0)
            deferred = int(result.get("db_deferred") or 0)
            skipped_oversize = int(result.get("skipped_oversize") or 0)
            if result.get("stopped"):
                tail = (
                    f"\n\n⏹ Stopped — <b>{result.get('ok', 0)}</b> uploaded before cancel."
                )
            else:
                tail = (
                    f"\n\n✅ Finished — <b>{result.get('ok', 0)}</b> uploaded. "
                    "Index_bot will link posts as they arrive."
                )
            if deferred:
                tail += (
                    f"\n\n<i>{deferred} DB update(s) queued — files are in the channel; "
                    "indexing will catch up shortly.</i>"
                )
            if skipped_oversize:
                tail += (
                    f"\n\n⚠️ Skipped <b>{skipped_oversize}</b> file(s) larger than Telegram's 4 GB limit."
                )
            failed_items = result.get("failed_items") or []
            if failed_items:
                max_show = 10
                tail += "\n\n<b>Failed files:</b>"
                for rec in failed_items[:max_show]:
                    fn = escape(str(rec.get("file") or "?")[:80])
                    reason = escape(str(rec.get("reason") or "unknown failure")[:140])
                    tail += f"\n• <code>{fn}</code> — {reason}"
                if len(failed_items) > max_show:
                    tail += f"\n<i>… +{len(failed_items) - max_show} more failed file(s)</i>"
            await asyncio.to_thread(flush_pending_job_marks, app, db)
            if progress_message_id:
                await flood_bot_edit_message_text(
                    context.bot,
                    progress_chat_id,
                    progress_message_id,
                    format_job_progress(job_id, prog) + tail,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("« Job", callback_data=f"up_job:{job_id}")]]
                    ),
                )
        except Exception as e:
            logger.exception("upload job %s failed", job_id)
            if progress_message_id:
                await flood_bot_edit_message_text(
                    context.bot,
                    progress_chat_id,
                    progress_message_id,
                    f"❌ Upload job failed:\n<code>{escape(str(e)[:200])}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("« Job", callback_data=f"up_job:{job_id}")]]
                    ),
                )
        finally:
            import asyncio

            from bot_busy import UPLOAD_ACTIVE_KEY
            from upload_db_defer import flush_pending_job_marks

            context.user_data.pop(f"upload_job_running_{job_id}", None)
            app.bot_data.pop(UPLOAD_ACTIVE_KEY, None)
            app.bot_data.pop(run_key, None)
            dequeue_slot(app, job_id)
            try:
                await asyncio.to_thread(flush_pending_job_marks, app, db)
            except Exception as e:
                logger.warning("flush_pending_job_marks after job %s: %s", job_id, e)

    from job_queue import enqueue_background

    try:
        await enqueue_background(
            context.application, f"Upload job #{job_id}", _job, exclusive=True
        )
    except Exception as e:
        dequeue_slot(app, job_id)
        logger.exception("Failed to enqueue upload job #%s", job_id)
        await _answer_upload_callback(
            query, f"Could not queue upload: {str(e)[:120]}", show_alert=True
        )


async def send_duplicates_menu(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    from database import FileUpload

    query = update.callback_query
    target = query if edit and query else update
    session = db.get_session()
    try:
        rows = (
            session.query(FileUpload)
            .filter_by(ingest_state="duplicate_hold")
            .order_by(FileUpload.uploaded_at.desc())
            .limit(12)
            .all()
        )
    finally:
        session.close()
    lines = ["<b>⚠️ Duplicate holds</b>", ""]
    keyboard = []
    if not rows:
        lines.append("<i>No duplicates waiting.</i>")
    else:
        for u in rows:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"#{u.id} {u.file_name[:40]}",
                        callback_data=f"up_dupe:{u.id}",
                    )
                ]
            )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_duplicate_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE, upload_id: int, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    upload = db.get_file_upload(upload_id)
    if not upload:
        await _edit_or_reply(target, "Not found.", None, edit=edit)
        return
    dupes = db.find_uploads_by_fingerprint(
        upload.content_fingerprint or "",
        exclude_upload_id=upload_id,
        incoming_channel_id=upload.channel_id,
    )
    lines = [
        f"<b>Duplicate review</b> #{upload.id}",
        f"<code>{escape(upload.file_name)}</code>",
        f"Size: {upload.file_size or '?'}",
        "",
        f"<b>{len(dupes)}</b> existing match(es):",
    ]
    from channel_labels import upload_location_label

    ingest_id = db.get_ingest_channel_id()
    for d in dupes[:5]:
        loc = upload_location_label(d, ingest_channel_id=ingest_id)
        lines.append(f"• #{d.id} in {loc} — {escape(d.parsed_name or '?')}")
    keyboard = []
    if dupes:
        for d in dupes[:3]:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📂 Open #{d.id}",
                        callback_data=f"watch_pick:{d.id}",
                    ),
                    InlineKeyboardButton(
                        "🔗 Merge",
                        callback_data=f"up_dupe_link:{upload_id}:{d.id}",
                    ),
                ]
            )
        first = dupes[0]
        keyboard.append(
            [
                InlineKeyboardButton(
                    "📤 Publish existing",
                    callback_data=f"up_promote_upload:{first.id}",
                )
            ]
        )
    keyboard.extend(
        [
            [
                InlineKeyboardButton("⏭ Skip", callback_data=f"up_dupe_skip:{upload_id}"),
                InlineKeyboardButton("✅ Index anyway", callback_data=f"up_dupe_force:{upload_id}"),
            ],
            [InlineKeyboardButton("« Duplicates", callback_data="up_dupes")],
        ]
    )
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_course_vault(
    update: Update, context: ContextTypes.DEFAULT_TYPE, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    courses = db.list_course_titles(limit=20)
    lines = ["<b>🎓 Course vault</b>", "", "Admin-only course libraries.", ""]
    keyboard = []
    if not courses:
        lines.append("<i>No courses yet — create an upload job with lane=course.</i>")
    else:
        for ct in courses:
            keyboard.append(
                [InlineKeyboardButton(f"🎓 {ct.name[:40]}", callback_data=f"up_course:{ct.id}")]
            )
    keyboard.append([InlineKeyboardButton("« Upload hub", callback_data="up_hub")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def send_course_lessons(
    update: Update, context: ContextTypes.DEFAULT_TYPE, ct_id: int, *, edit: bool = False
) -> None:
    query = update.callback_query
    target = query if edit and query else update
    ct = db.get_content_title(ct_id)
    if not ct:
        await _edit_or_reply(target, "Course not found.", None, edit=edit)
        return
    uploads = db.get_course_uploads(ct_id, limit=30)
    lines = [f"<b>🎓 {escape(ct.name)}</b>", f"<b>{len(uploads)}</b> lesson(s)", ""]
    keyboard = []
    for u in uploads[:20]:
        mod = u.module_name or ""
        seq = u.lesson_sequence or u.episode_number or "?"
        label = f"{seq}. {(u.episode_title or u.file_name)[:35]}"
        keyboard.append(
            [InlineKeyboardButton(label, callback_data=f"watch_pick:{u.id}")]
        )
    keyboard.append(
        [
            InlineKeyboardButton(
                "📚 Publish to library",
                callback_data=f"up_promote_course:{ct_id}",
            ),
            InlineKeyboardButton(
                "🎬 Promote as media",
                callback_data=f"up_promote_media:{ct_id}",
            ),
        ]
    )
    keyboard.append([InlineKeyboardButton("« Courses", callback_data="up_course")])
    await _edit_or_reply(target, "\n".join(lines), InlineKeyboardMarkup(keyboard), edit=edit)


async def handle_upload_admin_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, user_id: int
) -> bool:
    """Wizard steps + channel search while picking upload job target."""
    import asyncio

    from upload_planning import (
        format_plan_summary,
        normalize_user_path,
        scan_files_for_plan,
        scan_folder_for_plan,
    )

    pipe_ut = context.user_data.pop("awaiting_pipeline_channel_search", None)
    if pipe_ut and Config.is_admin(user_id):
        from pipeline_setup import send_pipeline_channel_picker

        await send_pipeline_channel_picker(
            update, context, pipe_ut, 0, query=text, edit=False
        )
        return True

    job_id = context.user_data.pop("awaiting_job_channel_search", None)
    if job_id and Config.is_admin(user_id):
        await send_job_channel_picker(update, context, int(job_id), 0, query=text, edit=False)
        return True

    wiz = context.user_data.get("upload_wizard")
    if not wiz or not Config.is_admin(user_id):
        return False

    step = wiz.get("step")

    if step in ("check_folder", "folder_path"):
        try:
            folder = normalize_user_path(text)
        except ValueError:
            await update.message.reply_text("❌ Send a folder path (no empty message).")
            return True

    if step == "check_folder":
        status = None
        try:
            rows, new, dup, status = await _scan_folder_with_live_progress(update, folder)
        except Exception as e:
            if status is None:
                status = await update.message.reply_text("⏳ Scanning folder…")
            await status.edit_text(_scan_error_message(e, folder), parse_mode=ParseMode.HTML)
            _clear_upload_wizard(context)
            return True
        _clear_upload_wizard(context)
        if not rows:
            await status.edit_text("No supported files found in that folder.")
            return True
        body = format_plan_summary(
            total=len(rows),
            new=new,
            dup=dup,
            lane="media",
            sample_rows=rows,
        )
        await status.edit_text(
            body
            + f"\n\nFolder: <code>{escape(str(folder))}</code>\n\n"
            "<i>To upload: Upload pipeline → New upload job → scan this folder.</i>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("➕ New upload job", callback_data="up_new")]]
            ),
        )
        return True

    if step == "folder_path":
        status = None
        try:
            rows, new, dup, status = await _scan_folder_with_live_progress(update, folder)
        except Exception as e:
            if status is None:
                status = await update.message.reply_text("⏳ Scanning folder…")
            await status.edit_text(_scan_error_message(e, folder), parse_mode=ParseMode.HTML)
            return True
        if not rows:
            await status.edit_text("No supported files found in that folder.")
            return True
        default_name = folder.name[:50] or "Upload batch"
        wiz["folder"] = str(folder.resolve())
        wiz["lane"] = normalize_lane(wiz.get("lane", LANE_COURSE))
        wiz["planned_rows"] = rows
        wiz["new"] = new
        wiz["dup"] = dup
        wiz["step"] = "confirm"
        await _reply_plan_preview(
            update,
            context,
            lane=wiz["lane"],
            rows=rows,
            new=new,
            dup=dup,
            folder=str(folder.resolve()),
            create_name=default_name,
            status_message=status,
        )
        return True

    if step == "file_paths":
        raw_paths = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not raw_paths:
            await update.message.reply_text(
                "❌ Send at least one absolute file path (one per line)."
            )
            return True
        from telegram.error import BadRequest, NetworkError, TimedOut
        from telegram_flood import flood_bot_edit_message_text, flood_reply_text

        status = await flood_reply_text(
            update.message,
            "⏳ Checking file path(s)…",
            parse_mode=ParseMode.HTML,
        )
        try:
            rows, new, dup = await asyncio.to_thread(scan_files_for_plan, raw_paths)
        except Exception as e:
            err = (
                f"❌ {escape(str(e)[:220])}\n\n"
                "<i>Tip: send absolute file path(s), one per line.</i>"
            )
            try:
                await flood_bot_edit_message_text(
                    status.get_bot(),
                    status.chat_id,
                    status.message_id,
                    err,
                    parse_mode=ParseMode.HTML,
                )
            except (TimedOut, NetworkError, BadRequest):
                await flood_reply_text(
                    update.message, err, parse_mode=ParseMode.HTML
                )
            return True
        if not rows:
            empty = "No supported files found in the provided paths."
            try:
                await flood_bot_edit_message_text(
                    status.get_bot(),
                    status.chat_id,
                    status.message_id,
                    empty,
                    parse_mode=ParseMode.HTML,
                )
            except (TimedOut, NetworkError, BadRequest):
                await flood_reply_text(
                    update.message, empty, parse_mode=ParseMode.HTML
                )
            return True
        default_name = (Path(rows[0].get("file_name") or "Upload batch").stem)[:50] or "Upload batch"
        wiz["lane"] = normalize_lane(wiz.get("lane", LANE_COURSE))
        wiz["planned_rows"] = rows
        wiz["new"] = new
        wiz["dup"] = dup
        wiz["step"] = "confirm"
        await _reply_plan_preview(
            update,
            context,
            lane=wiz["lane"],
            rows=rows,
            new=new,
            dup=dup,
            folder=None,
            create_name=default_name,
            status_message=status,
        )
        return True

    if step == "job_name":
        name = text.strip()[:200]
        if not name:
            await update.message.reply_text("Send a non-empty job name.")
            return True
        wiz["course_title"] = name
        await create_wizard_job(update, context, name)
        return True

    return False


async def import_csv_job(
    text: str,
    user_id: int,
    *,
    lane: str | None = None,
    job_name: str | None = None,
    course_title: str | None = None,
) -> tuple[bool, str, int | None]:
    import asyncio

    from upload_planning import create_job_from_rows, parse_csv_for_plan

    content_lane = normalize_lane(lane or LANE_COURSE)
    rows, new, dup = await asyncio.to_thread(parse_csv_for_plan, text)
    if not rows:
        return (
            False,
            "Could not parse CSV. Need a header row and column "
            "<code>filename</code> and/or <code>local_path</code>.",
            None,
        )
    with_path = sum(1 for r in rows if r.get("local_path"))
    name = (job_name or f"CSV import {len(rows)} files")[:200]
    title = (course_title or rows[0].get("lesson_title") or name)[:200]
    job_id, info = await asyncio.to_thread(
        create_job_from_rows,
        name,
        rows,
        content_lane=content_lane,
        course_title=title,
        created_by=user_id,
    )
    if not job_id:
        return False, "Failed to create job", None
    dec = info.get("decisions") or {}
    coll = _collection_field_label(content_lane)
    path_note = (
        f"\nPaths on disk: <b>{with_path}</b> / <b>{info.get('items', len(rows))}</b> "
        "(ready for ▶️ Start upload)."
        if with_path
        else (
            "\n⚠️ No <code>local_path</code> in CSV — manifest only. "
            "Add paths or use <b>Scan folder</b> in the bot."
        )
    )
    return True, (
        f"Created job <b>#{job_id}</b> with <b>{info.get('items', len(rows))}</b> items.\n"
        f"Lane: <code>{escape(content_lane)}</code> · {coll}: <b>{escape(title)}</b>\n"
        f"New: <b>{new}</b> · Already in library: <b>{dup}</b>\n"
        f"Decisions: upload={dec.get('upload', 0)} skip={dec.get('skip', 0)}"
        f"{path_note}\n\n"
        f"Next: open job → set target → <b>Upload all new</b> → <b>Start upload</b>"
    ), job_id


async def handle_upload_callback(
    data: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
) -> bool:
    if not Config.is_admin(user_id):
        return False
    if not data.startswith("up_"):
        return False

    query = update.callback_query

    if data == "up_hub":
        _clear_upload_wizard(context)
        await send_upload_hub(update, context, edit=True)
        return True
    if data == "up_pipe_status":
        await send_pipeline_status(update, context, edit=True)
        return True
    if data == "up_pipe_route_run":
        pending = db.list_pipeline_route_queue(limit=25)
        if not pending:
            await query.answer("Route queue empty", show_alert=True)
            return True
        from pipeline_router import schedule_pipeline_route

        for row in pending:
            schedule_pipeline_route(context.application, row.id)
        await query.answer(f"Queued {len(pending)} route job(s)")
        await send_pipeline_status(update, context, edit=True)
        return True
    if data == "up_jobs":
        await send_jobs_menu(update, context, edit=True)
        return True
    if data == "up_dupes":
        await send_duplicates_menu(update, context, edit=True)
        return True
    if data == "up_course":
        await send_course_vault(update, context, edit=True)
        return True
    if data == "up_new":
        await send_new_job_lane_picker(update, context, edit=True)
        return True
    if data == "up_check":
        await send_folder_check_prompt(update, context, edit=True)
        return True
    if data.startswith("up_wiz_lane:"):
        lane = data.split(":", 1)[1]
        await send_new_job_source_picker(update, context, lane, edit=True)
        return True
    if data.startswith("up_wiz_src:"):
        parts = data.split(":")
        src = parts[1] if len(parts) > 1 else "folder"
        lane = parts[2] if len(parts) > 2 else LANE_COURSE
        if src == "csv":
            context.user_data["upload_wizard"] = {
                "lane": normalize_lane(lane),
                "step": "csv",
            }
            context.user_data["awaiting_upload_csv"] = True
            lane_label = LANE_LABELS.get(normalize_lane(lane), lane)
            await _edit_or_reply(
                query,
                f"<b>CSV for {lane_label}</b>\n\n"
                "Send a <b>CSV file</b> or paste text.\n\n"
                "Header: <code>sequence,module,lesson_title,filename,local_path</code>\n"
                "Include <code>local_path</code> for ▶️ Start upload.",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Cancel", callback_data="up_hub")]]
                ),
                edit=True,
            )
        elif src == "file":
            context.user_data["upload_wizard"] = {
                "lane": normalize_lane(lane),
                "step": "file_paths",
            }
            lane_label = LANE_LABELS.get(normalize_lane(lane), lane)
            await _edit_or_reply(
                query,
                f"<b>File path mode — {lane_label}</b>\n\n"
                "Send one or more <b>absolute file paths</b> on this machine.\n"
                "If sending multiple, put <b>one path per line</b>.\n\n"
                "Example (single):\n"
                "<code>/Volumes/Mac-Extension/Movies/Raised.by.Wolves.S01E01.mkv</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Cancel", callback_data="up_hub")]]
                ),
                edit=True,
            )
        else:
            context.user_data["upload_wizard"] = {
                "lane": normalize_lane(lane),
                "step": "folder_path",
            }
            lane_label = LANE_LABELS.get(normalize_lane(lane), lane)
            await _edit_or_reply(
                query,
                f"<b>Folder scan — {lane_label}</b>\n\n"
                "Send the <b>full folder path</b> on this device.\n\n"
                "Paste without quotes. Example (Termux):\n"
                "<code>/storage/emulated/0/Download/MyCourse</code>\n"
                "Example (Mac): <code>/Volumes/Mac-Extension/Courses/MyCourse</code>",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("« Cancel", callback_data="up_hub")]]
                ),
                edit=True,
            )
        await query.answer()
        return True
    if data == "up_wiz_create":
        wiz = context.user_data.get("upload_wizard") or {}
        name = (wiz.get("default_name") or "Upload batch")[:200]
        await query.answer("Creating job…")
        if query.message:
            await create_wizard_job_from_callback(update, context, name)
        return True
    if data == "up_wiz_name":
        wiz = context.user_data.get("upload_wizard") or {}
        wiz["step"] = "job_name"
        await _edit_or_reply(
            query,
            "<b>Job name</b>\n\nSend the name for this upload job.",
            InlineKeyboardMarkup([[InlineKeyboardButton("« Cancel", callback_data="up_hub")]]),
            edit=True,
        )
        return True
    if data == "up_new_csv":
        await send_new_job_lane_picker(update, context, edit=True)
        return True
    if data.startswith("up_job:"):
        await send_job_detail(update, context, int(data.split(":")[1]), edit=True)
        return True
    if data.startswith("up_job_ch:"):
        parts = data.split(":")
        job_id = int(parts[1])
        page = int(parts[2]) if len(parts) > 2 else 0
        await send_job_channel_picker(update, context, job_id, page, edit=True)
        return True
    if data.startswith("up_job_ch_search:"):
        job_id = int(data.split(":")[1])
        context.user_data["awaiting_job_channel_search"] = job_id
        await _edit_or_reply(
            query,
            f"<b>Search channels</b> (job #{job_id})\n\nSend @username or title fragment.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("« Cancel", callback_data=f"up_job:{job_id}")]]
            ),
            edit=True,
        )
        return True
    if data.startswith("up_job_target:"):
        parts = data.split(":")
        job_id = int(parts[1])
        channel_id = parts[2]
        db.set_upload_job_target(job_id, channel_id)
        await query.answer("Source channel set", show_alert=False)
        await send_job_detail(update, context, job_id, edit=True)
        return True
    if data.startswith("up_job_run:"):
        await start_upload_job_background(update, context, int(data.split(":")[1]))
        return True
    if data.startswith("up_job_stop:"):
        job_id = int(data.split(":")[1])
        if request_upload_job_stop(context.application, job_id):
            await query.answer("Stopping after current file…")
        else:
            await query.answer("No upload running for this job.", show_alert=True)
        return True
    import re

    m = re.match(r"^upjch(\d+)_page:(\d+)(?::(.*))?$", data)
    if m:
        from channel_picker import decode_query_token

        job_id = int(m.group(1))
        page = int(m.group(2))
        token = m.group(3) or ""
        q = decode_query_token(token) if token else None
        await send_job_channel_picker(update, context, job_id, page, q, edit=True)
        return True
    if data.startswith("up_job_skip:"):
        job_id = int(data.split(":")[1])
        changed, total = db.skip_all_duplicate_job_items(job_id)
        if total == 0:
            await query.answer("No duplicates in this job", show_alert=True)
        elif changed == 0:
            await query.answer(
                f"All {total} duplicate(s) already set to skip",
                show_alert=True,
            )
        else:
            await query.answer(f"Skipped {changed} duplicate(s)", show_alert=False)
        await send_job_detail(update, context, job_id, edit=True)
        return True
    if data.startswith("up_job_anyway:") or data.startswith("up_job_new:"):
        job_id = int(data.split(":")[1])
        changed, total = db.upload_anyway_duplicate_job_items(job_id)
        if total == 0:
            await query.answer("No duplicates — nothing to force-upload", show_alert=True)
        elif changed == 0:
            await query.answer(
                f"All {total} duplicate(s) already set to upload",
                show_alert=True,
            )
        else:
            await query.answer(
                f"Will re-upload {changed} duplicate(s)",
                show_alert=False,
            )
        await send_job_detail(update, context, job_id, edit=True)
        return True
    if data.startswith("up_dupe:"):
        await send_duplicate_detail(update, context, int(data.split(":")[1]), edit=True)
        return True
    if data.startswith("up_dupe_skip:"):
        db.resolve_duplicate_upload(int(data.split(":")[1]), "skip")
        await query.answer("Skipped", show_alert=False)
        await send_duplicates_menu(update, context, edit=True)
        return True
    if data.startswith("up_dupe_force:"):
        uid = int(data.split(":")[1])
        db.resolve_duplicate_upload(uid, "force")
        from name_parser import NameParser
        from tmdb_helper import tmdb_helper
        from upload_pipeline import reindex_existing_upload

        ok = reindex_existing_upload(db, NameParser(), tmdb_helper, uid)
        await query.answer(
            "Indexed" if ok else "Could not re-index",
            show_alert=not ok,
        )
        await send_duplicates_menu(update, context, edit=True)
        return True
    if data.startswith("up_course:"):
        await send_course_lessons(update, context, int(data.split(":")[1]), edit=True)
        return True
    if data.startswith("up_dupe_use_existing:"):
        parts = data.split(":")
        hold_id = int(parts[1])
        existing_id = int(parts[2])
        ok = db.link_duplicate_hold_to_existing(hold_id, existing_id)
        await query.answer(
            f"Linked to #{existing_id}" if ok else "Could not link",
            show_alert=not ok,
        )
        await send_duplicates_menu(update, context, edit=True)
        return True
    if data.startswith("up_dupe_link:"):
        parts = data.split(":")
        hold_id = int(parts[1])
        existing_id = int(parts[2])
        ok = db.link_duplicate_hold_to_existing(hold_id, existing_id)
        await query.answer("Merged" if ok else "Failed", show_alert=not ok)
        await send_duplicate_detail(update, context, hold_id, edit=True)
        return True
    if data.startswith("up_promote_course:"):
        ct_id = int(data.split(":")[1])
        from vault_features import promote_and_publish_title

        n, _note = await promote_and_publish_title(
            context, ct_id, to_media_lane=False
        )
        await query.answer(f"Published {n} lesson(s) to library", show_alert=True)
        await send_course_lessons(update, context, ct_id, edit=True)
        return True
    if data.startswith("up_promote_media:"):
        ct_id = int(data.split(":")[1])
        from vault_features import promote_and_publish_title

        n, note = await promote_and_publish_title(
            context, ct_id, to_media_lane=True
        )
        await query.answer(f"Promoted {n} file(s)", show_alert=False)
        await _edit_or_reply(query, note, None, edit=True)
        await send_course_lessons(update, context, ct_id, edit=True)
        return True
    if data.startswith("up_promote_upload:"):
        uid = int(data.split(":")[1])
        up = db.promote_upload_to_library(uid, to_media_lane=False)
        if up and up.content_title_id:
            from vault_features import promote_and_publish_title

            await promote_and_publish_title(
                context, up.content_title_id, to_media_lane=False
            )
        await query.answer("Published" if up else "Failed", show_alert=not bool(up))
        return True
    if data.startswith("up_lane:") and data.count(":") >= 2:
        _, ch_id, lane = data.split(":", 2)
        db.set_channel_lane(ch_id, lane)
        await query.answer(f"Lane set to {lane}", show_alert=False)
        if context.user_data.get("setup_return") == "setup_hub":
            from library_setup import send_setup_staging_channel

            await send_setup_staging_channel(update, context, ch_id, edit=True)
        return True
    return False
