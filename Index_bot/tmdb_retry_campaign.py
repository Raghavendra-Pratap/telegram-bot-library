"""
Multi-cycle TMDB retry campaign with live Telegram progress (matched / pending / errors).

Processes pending files in small waves so only one batch is due at a time.
Cycle 2 does not start until cycle 1 has fully drained the queue.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from config import Config
from tmdb_retry_queue import enqueue_tmdb_retry_ids

if TYPE_CHECKING:
    from telegram.ext import Application, ContextTypes

logger = logging.getLogger(__name__)

_CAMPAIGN_KEY = "tmdb_retry_campaign"
_PROGRESS_TASK_KEY = "tmdb_retry_campaign_progress_task"


def get_campaign(application: "Application") -> dict[str, Any] | None:
    camp = application.bot_data.get(_CAMPAIGN_KEY)
    if camp and camp.get("active"):
        return camp
    return None


def campaign_max_attempts_per_minute() -> float:
    """Configured upper bound (tries/min) during an active campaign."""
    batch = max(1, Config.TMDB_CAMPAIGN_BATCH_SIZE)
    burst = max(1, Config.TMDB_CAMPAIGN_BURST_TICKS)
    tick = max(1.0, Config.TMDB_CAMPAIGN_TICK_S)
    gap = max(0.1, Config.TMDB_CAMPAIGN_INTERVAL_S)
    per_tick = batch * burst
    tick_duration = tick + burst * batch * gap
    return per_tick * 60.0 / tick_duration


def _format_duration(seconds: float) -> str:
    secs = max(0, int(seconds))
    hours, rem = divmod(secs, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _estimate_attempts_per_second(camp: dict[str, Any]) -> float:
    """Use measured pace when available, else configured campaign throughput."""
    started = float(camp.get("started_mono", 0))
    elapsed = max(1.0, time.monotonic() - started) if started else 1.0
    attempted = int(camp.get("attempted", 0))
    if attempted >= 25 and elapsed >= 90:
        return attempted / elapsed
    batch = max(1, Config.TMDB_CAMPAIGN_BATCH_SIZE)
    burst = max(1, Config.TMDB_CAMPAIGN_BURST_TICKS)
    tick = max(1.0, Config.TMDB_CAMPAIGN_TICK_S)
    gap = max(0.1, Config.TMDB_CAMPAIGN_INTERVAL_S)
    per_tick = batch * burst
    tick_duration = tick + burst * batch * gap
    return per_tick / tick_duration


def note_campaign_result(application: "Application", result: str) -> None:
    """Called by the TMDB retry worker after each upload attempt."""
    camp = get_campaign(application)
    if not camp:
        return
    camp["attempted"] = int(camp.get("attempted", 0)) + 1
    camp["cycle_attempted"] = int(camp.get("cycle_attempted", 0)) + 1
    if result == "matched":
        camp["matched"] = int(camp.get("matched", 0)) + 1
    elif result == "api_error":
        camp["api_errors"] = int(camp.get("api_errors", 0)) + 1


def _format_progress(camp: dict[str, Any], db) -> str:
    still = db.count_pending_confirmations()
    scheduled = db.count_scheduled_tmdb_retries()
    due = db.count_due_tmdb_retries()
    initial = int(camp.get("initial_pending", 0))
    attempted = int(camp.get("attempted", 0))
    cycle = int(camp.get("cycle", 1))
    max_cycles = int(camp.get("max_cycles", 1))
    cycle_enq = int(camp.get("cycle_enqueued", 0))
    cycle_done = int(camp.get("cycle_attempted", 0))
    wave = int(camp.get("wave", 0))
    wave_size = int(camp.get("wave_size", Config.TMDB_RETRY_CAMPAIGN_WAVE_SIZE))
    not_queued = db.count_pending_not_on_tmdb_retry_queue()

    lines = [
        "⏳ <b>Retrying TMDB for pending files…</b>",
        "",
        f"Cycle <b>{cycle}</b> / <b>{max_cycles}</b>"
        + (f" · wave <b>{wave}</b>" if wave else ""),
        f"Progress: <b>{attempted:,}</b> / <b>{initial:,}</b>",
        f"Auto-matched: <b>{int(camp.get('matched', 0)):,}</b>",
        f"Still pending: <b>{still:,}</b>",
    ]
    api_err = int(camp.get("api_errors", 0))
    if api_err:
        lines.append(f"TMDB errors (retry next wave/cycle): <b>{api_err:,}</b>")
    if cycle_enq:
        lines.append(
            f"This cycle: <b>{min(cycle_done, cycle_enq):,}</b> / <b>{cycle_enq:,}</b> tried"
        )
    if scheduled or due:
        lines.append(
            f"Active wave: <b>{due:,}</b> due now"
            f" (max <b>{wave_size:,}</b> at a time)"
        )
    if not_queued and cycle_enq:
        lines.append(f"Waiting for next wave: <b>{not_queued:,}</b> file(s)")

    started = float(camp.get("started_mono", 0))
    if started:
        elapsed = time.monotonic() - started
        rate = _estimate_attempts_per_second(camp)
        lines.append("")
        lines.append(f"Elapsed: <b>{_format_duration(elapsed)}</b>")
        remaining_tries = max(0, initial - attempted)
        if rate > 0 and remaining_tries > 0:
            lines.append(
                f"Est. remaining (tries): <b>~{_format_duration(remaining_tries / rate)}</b>"
            )
        if rate > 0 and still > 0:
            matched = int(camp.get("matched", 0))
            if matched >= 10 and elapsed >= 120:
                match_rate = matched / elapsed
                lines.append(
                    f"Est. remaining (pending): <b>~{_format_duration(still / match_rate)}</b>"
                )
        pace = rate * 60.0
        max_pace = campaign_max_attempts_per_minute()
        if int(camp.get("attempted", 0)) >= 25:
            lines.append(f"Pace: <b>~{pace:.0f}</b> tries/min (measured)")
        else:
            lines.append(
                f"Pace: <b>~{pace:.0f}</b> tries/min "
                f"(est. max <b>{max_pace:.0f}</b>/min)"
            )

    lines.append("")
    lines.append(
        "<i>Waves of "
        f"<b>{wave_size}</b> · worker "
        f"<b>{Config.TMDB_CAMPAIGN_BATCH_SIZE}×{Config.TMDB_CAMPAIGN_BURST_TICKS}</b> "
        f"per <b>{int(Config.TMDB_CAMPAIGN_TICK_S)}s</b> · "
        f"gap <b>{Config.TMDB_CAMPAIGN_INTERVAL_S}s</b></i>"
    )
    return "\n".join(lines)


async def _progress_loop(application: "Application", context: "ContextTypes.DEFAULT_TYPE") -> None:
    from bot import bot_edit_message, db

    interval = max(20.0, Config.TMDB_RETRY_CAMPAIGN_PROGRESS_S)
    try:
        while get_campaign(application):
            camp = get_campaign(application)
            if not camp:
                break
            text = _format_progress(camp, db)
            if text != camp.get("_last_progress_text"):
                camp["_last_progress_text"] = text
                try:
                    await bot_edit_message(
                        context,
                        camp["chat_id"],
                        camp["message_id"],
                        text,
                    )
                except Exception:
                    logger.debug("campaign progress edit failed", exc_info=True)
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        raise


def _stop_progress_task(application: "Application") -> None:
    task = application.bot_data.pop(_PROGRESS_TASK_KEY, None)
    if task and not task.done():
        task.cancel()


async def _wait_queue_drained(application: "Application", db) -> None:
    """Block until no row is on the TMDB retry schedule (wave fully processed)."""
    poll = max(6.0, Config.TMDB_CAMPAIGN_INTERVAL_S * 2)
    idle_ticks = 0
    while get_campaign(application):
        scheduled = await asyncio.to_thread(db.count_scheduled_tmdb_retries)
        due = await asyncio.to_thread(db.count_due_tmdb_retries)
        if scheduled == 0 and due == 0:
            idle_ticks += 1
            if idle_ticks >= 2:
                return
        else:
            idle_ticks = 0
        await asyncio.sleep(poll)


async def _run_one_cycle(application: "Application", db, camp: dict[str, Any]) -> None:
    """Try every pending file once, in waves — never more than wave_size due at once."""
    wave_size = max(16, Config.TMDB_RETRY_CAMPAIGN_WAVE_SIZE)
    camp["cycle_enqueued"] = 0
    camp["cycle_attempted"] = 0
    camp["wave_size"] = wave_size
    camp["wave"] = 0

    while get_campaign(application):
        if await asyncio.to_thread(db.count_pending_confirmations) == 0:
            break
        ids = await asyncio.to_thread(db.get_pending_for_tmdb_wave, wave_size)
        if not ids:
            break

        camp["wave"] = int(camp.get("wave", 0)) + 1
        queued = await asyncio.to_thread(
            enqueue_tmdb_retry_ids, db, ids, due_immediately=True
        )
        if not queued:
            break
        camp["cycle_enqueued"] = int(camp.get("cycle_enqueued", 0)) + queued
        logger.info(
            "TMDB campaign cycle %s wave %s: queued %s (cycle total %s)",
            camp.get("cycle"),
            camp["wave"],
            queued,
            camp["cycle_enqueued"],
        )
        await _wait_queue_drained(application, db)


async def run_tmdb_retry_campaign(
    application: "Application",
    context: "ContextTypes.DEFAULT_TYPE",
    *,
    chat_id: int,
    message_id: int,
    return_page: int = 0,
) -> None:
    from bot import bot_edit_message, db

    _stop_progress_task(application)
    initial = await asyncio.to_thread(db.count_pending_confirmations)
    if initial == 0:
        await bot_edit_message(
            context,
            chat_id,
            message_id,
            "✅ <b>No pending files</b> — nothing to retry.",
        )
        return

    max_cycles = max(1, Config.TMDB_RETRY_CAMPAIGN_MAX_CYCLES)
    pause = max(30.0, Config.TMDB_RETRY_CAMPAIGN_CYCLE_PAUSE_S)

    camp: dict[str, Any] = {
        "active": True,
        "chat_id": chat_id,
        "message_id": message_id,
        "return_page": return_page,
        "initial_pending": initial,
        "max_cycles": max_cycles,
        "cycle": 0,
        "attempted": 0,
        "matched": 0,
        "api_errors": 0,
        "_last_progress_text": "",
        "started_mono": time.monotonic(),
    }
    application.bot_data[_CAMPAIGN_KEY] = camp
    application.bot_data[_PROGRESS_TASK_KEY] = application.create_task(
        _progress_loop(application, context)
    )

    try:
        for cycle in range(1, max_cycles + 1):
            if not get_campaign(application):
                break
            pending_n = await asyncio.to_thread(db.count_pending_confirmations)
            if pending_n == 0:
                break

            camp["cycle"] = cycle
            await asyncio.to_thread(db.clear_pending_tmdb_retry_schedules)
            await _run_one_cycle(application, db, camp)

            if cycle < max_cycles:
                remaining = await asyncio.to_thread(db.count_pending_confirmations)
                if remaining == 0:
                    break
                await asyncio.to_thread(db.clear_pending_tmdb_retry_schedules)
                logger.info(
                    "TMDB campaign pause %.0fs before cycle %s (%s pending)",
                    pause,
                    cycle + 1,
                    remaining,
                )
                await asyncio.sleep(pause)

        still = await asyncio.to_thread(db.count_pending_confirmations)
        matched = int(camp.get("matched", 0))
        api_err = int(camp.get("api_errors", 0))
        elapsed_s = 0.0
        if camp.get("started_mono"):
            elapsed_s = time.monotonic() - float(camp["started_mono"])
        lines = [
            "<b>✅ TMDB retry campaign finished</b>",
            "",
            f"Cycles run: <b>{camp.get('cycle', 0)}</b> / <b>{max_cycles}</b>",
            f"Time elapsed: <b>{_format_duration(elapsed_s)}</b>",
            f"Attempts: <b>{int(camp.get('attempted', 0)):,}</b>",
            f"Auto-matched: <b>{matched:,}</b>",
            f"Still need confirmation: <b>{still:,}</b>",
        ]
        if api_err:
            lines.append(
                f"\nTMDB could not be reached for <b>{api_err:,}</b> attempt(s) "
                "during the campaign — run again later or match manually."
            )
        if still:
            lines.append(
                "\n<i>Run Retry TMDB again for another campaign, "
                "or match remaining files in Pending.</i>"
            )

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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
        await bot_edit_message(context, chat_id, message_id, "\n".join(lines), keyboard)
    except Exception:
        logger.exception("TMDB retry campaign failed")
        await bot_edit_message(
            context,
            chat_id,
            message_id,
            "❌ <b>TMDB retry campaign failed</b> — see bot.log",
        )
    finally:
        camp = application.bot_data.get(_CAMPAIGN_KEY)
        if camp:
            camp["active"] = False
        application.bot_data.pop(_CAMPAIGN_KEY, None)
        _stop_progress_task(application)
        await asyncio.to_thread(db.clear_pending_tmdb_retry_schedules)
