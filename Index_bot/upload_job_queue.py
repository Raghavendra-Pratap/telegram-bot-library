"""
FIFO tracking for Telethon bulk upload jobs (dedupe + queue position in UI).

Execution still runs through job_queue.enqueue_background(exclusive=True).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

UPLOAD_RUN_QUEUE_KEY = "upload_run_queue"
_LOCK_KEY = "upload_run_queue_lock"


@dataclass(slots=True)
class UploadRunSlot:
    job_id: int
    chat_id: int
    message_id: int


def _queue(app) -> list[UploadRunSlot]:
    raw = app.bot_data.get(UPLOAD_RUN_QUEUE_KEY)
    if not isinstance(raw, list):
        raw = []
        app.bot_data[UPLOAD_RUN_QUEUE_KEY] = raw
    return raw


def _lock(app) -> asyncio.Lock:
    lock = app.bot_data.get(_LOCK_KEY)
    if lock is None:
        lock = asyncio.Lock()
        app.bot_data[_LOCK_KEY] = lock
    return lock


def queue_contains(app, job_id: int) -> bool:
    return any(s.job_id == job_id for s in _queue(app))


def queue_position(app, job_id: int) -> int | None:
    for i, slot in enumerate(_queue(app)):
        if slot.job_id == job_id:
            return i + 1
    return None


def queue_length(app) -> int:
    return len(_queue(app))


async def enqueue_slot(
    app, job_id: int, chat_id: int, message_id: int
) -> int:
    """Add job if missing; return 1-based queue position."""
    async with _lock(app):
        q = _queue(app)
        if not any(s.job_id == job_id for s in q):
            q.append(UploadRunSlot(job_id=job_id, chat_id=chat_id, message_id=message_id))
        for i, slot in enumerate(q):
            if slot.job_id == job_id:
                return i + 1
    return len(_queue(app))


def dequeue_slot(app, job_id: int) -> None:
    q = _queue(app)
    app.bot_data[UPLOAD_RUN_QUEUE_KEY] = [s for s in q if s.job_id != job_id]


def active_upload_job_id(app) -> int | None:
    from bot_busy import UPLOAD_ACTIVE_KEY

    val = app.bot_data.get(UPLOAD_ACTIVE_KEY)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def status_line_html(app, job_id: int) -> str | None:
    """Short status for job detail screen."""
    active = active_upload_job_id(app)
    pos = queue_position(app, job_id)
    if active == job_id:
        return "▶️ <b>Upload running</b> for this job."
    if pos is None:
        return None
    total = queue_length(app)
    if pos == 1 and active is None:
        return "⏳ <b>Queued</b> — starting next."
    ahead = pos - 1
    if active is not None:
        return (
            f"⏳ <b>Queued</b> (position <b>{pos}</b> of <b>{total}</b>) — "
            f"upload job <b>#{active}</b> is running."
        )
    return f"⏳ <b>Queued</b> (position <b>{pos}</b> of <b>{total}</b>)."
