"""
Rate-limited TMDB retry queue for pending uploads after transient API/network errors.

Bulk "Retry TMDB" schedules rows with staggered ``tmdb_retry_after`` timestamps.
A background tick processes a small batch at a time so TMDB is not hammered.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from config import Config
from title_indexer import build_index_metadata

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

# Seconds before next attempt (by tmdb_retry_count after a failed try).
_BACKOFF_S = (90.0, 180.0, 300.0, 600.0, 1200.0, 1800.0, 3600.0, 7200.0)

_worker_task: asyncio.Task | None = None


def _backoff_seconds(retry_count: int) -> float:
    idx = min(max(0, retry_count), len(_BACKOFF_S) - 1)
    return _BACKOFF_S[idx]


def schedule_upload_tmdb_retry(
    db,
    upload_id: int,
    *,
    delay_seconds: float | None = None,
    increment: bool = True,
) -> None:
    """Queue one upload for a future TMDB retry attempt."""
    row = db.get_file_upload(upload_id)
    if not row or not row.needs_confirmation or row.is_confirmed:
        return
    count = int(getattr(row, "tmdb_retry_count", None) or 0)
    if increment:
        count += 1
    if delay_seconds is None:
        delay_seconds = _backoff_seconds(count - 1 if increment else count)
    if count > Config.TMDB_RETRY_MAX_ATTEMPTS:
        logger.info(
            "TMDB retry max attempts reached for upload #%s — leaving for manual pick",
            upload_id,
        )
        db.clear_upload_tmdb_retry(upload_id, keep_count=True)
        return
    db.set_upload_tmdb_retry(upload_id, delay_seconds=delay_seconds, retry_count=count)


def enqueue_tmdb_retry_ids(
    db, upload_ids: list[int], *, due_immediately: bool = False
) -> int:
    if not upload_ids:
        return 0
    stagger = 0.0 if due_immediately else max(0.5, Config.TMDB_RETRY_STAGGER_S)
    return db.enqueue_pending_tmdb_retries(
        upload_ids,
        stagger_seconds=stagger,
        due_immediately=due_immediately,
    )


def enqueue_all_pending_tmdb_retries(
    db, *, limit: int | None = None, due_immediately: bool = False
) -> int:
    """
    Schedule every pending confirmation for TMDB retries.

    ``due_immediately=True`` (campaign mode): all rows due now; worker rate-limits API.
    Otherwise rows are staggered by ``TMDB_RETRY_STAGGER_S``.

    Returns how many rows were queued.
    """
    cap = limit if limit is not None else Config.PENDING_SCAN_LIMIT
    pending = db.get_pending_confirmations(limit=cap)
    if not pending:
        return 0
    return enqueue_tmdb_retry_ids(
        db,
        [u.id for u in pending],
        due_immediately=due_immediately,
    )


async def retry_one_upload(
    upload_id: int,
    *,
    db,
    parser,
    tmdb_helper,
    application: "Application | None" = None,
) -> str:
    """
    Try TMDB once for a pending upload.

    Returns: matched | still_pending | api_error | skipped
    """
    upload = db.get_file_upload(upload_id)
    if not upload or not upload.needs_confirmation or upload.is_confirmed:
        if application is not None:
            from tmdb_retry_campaign import note_campaign_result

            note_campaign_result(application, "skipped")
        return "skipped"

    tmdb_helper._last_api_error = None
    meta = await asyncio.to_thread(
        build_index_metadata,
        upload.file_name,
        parser=parser,
        tmdb_helper=tmdb_helper,
        db=db,
    )
    api_err = bool(tmdb_helper._last_api_error) and meta.get("needs_tmdb_pick")
    outcome = await asyncio.to_thread(
        db.refresh_pending_upload_from_meta, upload.id, meta
    )
    if outcome == "matched":
        db.clear_upload_tmdb_retry(upload.id)
        result = "matched"
    elif api_err:
        from tmdb_retry_campaign import get_campaign

        if application is not None and get_campaign(application):
            # Defer to next campaign wave/cycle — avoid a second overlapping queue.
            db.clear_upload_tmdb_retry(upload.id)
        else:
            schedule_upload_tmdb_retry(db, upload.id, increment=True)
        result = "api_error"
    else:
        db.clear_upload_tmdb_retry(upload.id)
        result = "still_pending"
    if application is not None:
        from tmdb_retry_campaign import note_campaign_result

        note_campaign_result(application, result)
    return result


def _worker_settings(application: "Application") -> tuple[float, int, float, int]:
    from tmdb_retry_campaign import get_campaign

    if get_campaign(application):
        return (
            max(10.0, Config.TMDB_CAMPAIGN_TICK_S),
            max(1, Config.TMDB_CAMPAIGN_BATCH_SIZE),
            max(0.5, Config.TMDB_CAMPAIGN_INTERVAL_S),
            max(1, Config.TMDB_CAMPAIGN_BURST_TICKS),
        )
    return (
        max(15.0, Config.TMDB_RETRY_TICK_S),
        max(1, Config.TMDB_RETRY_BATCH_SIZE),
        max(0.5, Config.TMDB_RETRY_INTERVAL_S),
        1,
    )


async def _worker_loop(application: "Application") -> None:
    from bot import db, parser, tmdb_helper

    tick, batch_size, gap, _ = _worker_settings(application)
    logger.info(
        "TMDB retry worker started (tick=%ss, batch=%s, gap=%ss)",
        tick,
        batch_size,
        gap,
    )
    while True:
        try:
            tick, batch_size, gap, bursts = _worker_settings(application)
            await asyncio.sleep(tick)
            if not tmdb_helper.enabled:
                continue
            if application.bot_data.get("tmdb_retry_paused"):
                continue

            tick_matched = tick_api = tick_processed = 0
            for _burst in range(bursts):
                due = await asyncio.to_thread(
                    db.get_due_tmdb_retries, batch_size
                )
                if not due:
                    break

                for upload_id in due:
                    try:
                        result = await retry_one_upload(
                            upload_id,
                            db=db,
                            parser=parser,
                            tmdb_helper=tmdb_helper,
                            application=application,
                        )
                        tick_processed += 1
                        if result == "matched":
                            tick_matched += 1
                        elif result == "api_error":
                            tick_api += 1
                    except Exception:
                        logger.exception(
                            "TMDB retry worker failed for upload #%s", upload_id
                        )
                    await asyncio.sleep(gap)

            if tick_processed:
                logger.info(
                    "TMDB retry tick: processed=%s matched=%s api_errors=%s queue_due=%s",
                    tick_processed,
                    tick_matched,
                    tick_api,
                    await asyncio.to_thread(db.count_due_tmdb_retries),
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("TMDB retry worker tick failed")


def start_tmdb_retry_worker(application: "Application") -> None:
    """Start the background TMDB retry loop once."""
    global _worker_task
    if _worker_task and not _worker_task.done():
        return
    _worker_task = application.create_task(_worker_loop(application))


async def stop_tmdb_retry_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
