"""
Background TMDB re-index retries for uploads that failed due to transient API/network errors.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from config import Config
from title_indexer import build_index_metadata

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

_RETRY_DELAYS_S = (15.0, 60.0, 180.0, 600.0)


def should_queue_tmdb_retry(meta: dict, *, tmdb_helper) -> bool:
    """True when TMDB likely failed transiently and a retry may auto-confirm."""
    if not tmdb_helper.enabled:
        return False
    if meta.get("auto_confirm"):
        return False
    if not meta.get("needs_tmdb_pick"):
        return False
    return bool(tmdb_helper._last_api_error)


def _retry_delays() -> tuple[float, ...]:
    n = max(1, min(8, Config.TMDB_INGEST_RETRY_ATTEMPTS))
    return _RETRY_DELAYS_S[:n]


async def retry_upload_index_metadata(
    upload_id: int,
    *,
    db,
    parser,
    tmdb_helper,
) -> bool:
    """Re-run TMDB index; return True if auto-confirmed."""
    upload = db.get_file_upload(upload_id)
    if not upload or not upload.needs_confirmation:
        return False
    meta = await asyncio.to_thread(
        build_index_metadata,
        upload.file_name,
        parser=parser,
        tmdb_helper=tmdb_helper,
        db=db,
    )
    outcome = await asyncio.to_thread(
        db.refresh_pending_upload_from_meta, upload.id, meta
    )
    return outcome == "matched"


async def run_tmdb_retry_chain(
    application: "Application",
    upload_id: int,
    *,
    db,
    parser,
    tmdb_helper,
) -> None:
    for attempt, delay in enumerate(_retry_delays()):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            matched = await retry_upload_index_metadata(
                upload_id, db=db, parser=parser, tmdb_helper=tmdb_helper
            )
            if matched:
                logger.info(
                    "TMDB ingest retry #%s auto-confirmed upload #%s",
                    attempt + 1,
                    upload_id,
                )
                return
            if not tmdb_helper._last_api_error:
                logger.debug(
                    "TMDB ingest retry #%s for #%s — no API error, stop retrying",
                    attempt + 1,
                    upload_id,
                )
                return
        except Exception:
            logger.exception(
                "TMDB ingest retry #%s failed for upload #%s",
                attempt + 1,
                upload_id,
            )
    logger.info("TMDB ingest retries exhausted for upload #%s", upload_id)


def schedule_tmdb_ingest_retry(
    application: "Application",
    upload_id: int,
    *,
    db,
    parser,
    tmdb_helper,
) -> None:
    from job_queue import enqueue_background

    async def _enqueue() -> None:
        await enqueue_background(
            application,
            f"TMDB retry #{upload_id}",
            lambda: run_tmdb_retry_chain(
                application,
                upload_id,
                db=db,
                parser=parser,
                tmdb_helper=tmdb_helper,
            ),
            exclusive=False,
        )

    application.create_task(_enqueue())
