"""Defer upload-job DB writes when SQLite is busy — Telethon must not fail."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

PENDING_MARKS_KEY = "upload_pending_job_marks"


def get_pending_marks(application) -> list[dict[str, Any]]:
    if not application:
        return []
    return application.bot_data.setdefault(PENDING_MARKS_KEY, [])


def queue_job_item_uploaded(
    application,
    *,
    item_id: int,
    message_id: int,
    job_id: int,
    channel_id: str,
    file_name: str,
    file_size: int | None,
) -> None:
    get_pending_marks(application).append(
        {
            "item_id": int(item_id),
            "message_id": int(message_id),
            "job_id": int(job_id),
            "channel_id": str(channel_id),
            "file_name": file_name,
            "file_size": file_size,
        }
    )


def flush_pending_job_marks(application, db) -> int:
    """Apply queued item marks; return count flushed. Leaves failures in queue."""
    if not application:
        return 0
    batch = list(application.bot_data.get(PENDING_MARKS_KEY) or [])
    if not batch:
        return 0
    remaining: list[dict[str, Any]] = []
    flushed = 0
    job_ids: set[int] = set()
    for rec in batch:
        item_id = rec.get("item_id")
        message_id = rec.get("message_id")
        if item_id is None or message_id is None:
            continue
        if db.mark_job_item_uploaded(int(item_id), int(message_id)):
            flushed += 1
            if rec.get("job_id") is not None:
                job_ids.add(int(rec["job_id"]))
        else:
            remaining.append(rec)
    application.bot_data[PENDING_MARKS_KEY] = remaining
    for jid in job_ids:
        try:
            db.refresh_upload_job_status(jid)
        except Exception as e:
            logger.warning("refresh_upload_job_status %s after flush: %s", jid, e)
    if remaining:
        logger.info(
            "Upload DB flush: %s applied, %s still queued (will retry on next flush / ingest)",
            flushed,
            len(remaining),
        )
    elif flushed:
        logger.info("Upload DB flush: applied %s deferred mark(s)", flushed)
    return flushed
