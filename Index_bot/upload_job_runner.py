"""Run bulk upload jobs via Telethon (shared by CLI and bot UI)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from database import Database
from forward_ingest import resolve_entity
from telethon.errors import FloodWaitError

logger = logging.getLogger(__name__)

ProgressFn = Callable[[dict], Awaitable[None]]
CancelFn = Callable[[], bool]
TELEGRAM_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB


def _flush_pending_marks(
    db: Database,
    pending_marks: list[dict[str, Any]] | None,
    *,
    job_id: int,
) -> int:
    """Try to persist deferred item marks; shrink list in place."""
    if not pending_marks:
        return 0
    flushed = 0
    still: list[dict[str, Any]] = []
    for rec in pending_marks:
        item_id = rec.get("item_id")
        message_id = rec.get("message_id")
        if item_id is None or message_id is None:
            continue
        if db.mark_job_item_uploaded(int(item_id), int(message_id)):
            flushed += 1
        else:
            still.append(rec)
    pending_marks[:] = still
    if flushed:
        try:
            db.refresh_upload_job_status(job_id)
        except Exception as e:
            logger.warning("refresh_upload_job_status job=%s: %s", job_id, e)
    return flushed


async def run_upload_job(
    *,
    job_id: int,
    session_path: Path,
    api_id: int,
    api_hash: str,
    delay_s: float = 3.0,
    dry_run: bool = False,
    on_progress: ProgressFn | None = None,
    cancel_check: CancelFn | None = None,
    pending_marks: list[dict[str, Any]] | None = None,
    defer_db_writes: bool = False,
) -> dict:
    """
    Upload job items with decision upload/force to target channel.
    Returns summary dict: ok, fail, total, skipped_missing, db_deferred.

    When defer_db_writes is True (bot UI), item marks are queued in pending_marks
    during the Telethon loop and flushed after all files are sent — uploads never
    fail because SQLite is locked.
    """
    db = Database()
    job = db.get_upload_job(job_id)
    if not job:
        raise RuntimeError(f"Job #{job_id} not found")
    if not job.target_channel_id:
        raise RuntimeError("Job has no target channel — set one in Upload pipeline → job")

    items = db.get_upload_job_items(job_id)
    to_send = [it for it in items if it.decision in ("upload", "force") and it.local_path]
    if not to_send:
        raise RuntimeError("No items with decision=upload and a local file path")

    total = len(to_send)
    channel_id = str(job.target_channel_id)

    async def _report(**kwargs) -> None:
        if on_progress:
            await on_progress({"job_id": job_id, "total": total, **kwargs})

    if dry_run:
        await _report(phase="dry_run", done=0, ok=0, fail=0)
        return {"ok": 0, "fail": 0, "total": total, "dry_run": True}

    from telethon_gateway import run_telethon

    async def _upload_with_client(client):
        nonlocal ok, fail, skipped_missing, skipped_oversize, stopped
        dest = await resolve_entity(
            client, job.target_channel_id, display_name="target"
        )
        if not db.set_upload_job_status(job_id, "uploading"):
            logger.warning("Could not set job #%s to uploading (DB busy) — continuing", job_id)
        await _report(phase="uploading", done=0, ok=0, fail=0, current="")

        for i, it in enumerate(to_send, start=1):
            if cancel_check and cancel_check():
                stopped = True
                break
            path = Path(it.local_path)
            label = it.lesson_title or it.file_name
            if not path.is_file():
                skipped_missing += 1
                fail += 1
                failed_items.append({"file": path.name, "reason": "missing local file"})
                await _report(
                    phase="uploading",
                    done=i,
                    ok=ok,
                    fail=fail,
                    current=f"missing: {path.name}",
                )
                continue
            try:
                size = int(path.stat().st_size)
            except Exception:
                size = None
            if size is not None and size > TELEGRAM_MAX_UPLOAD_BYTES:
                skipped_oversize += 1
                fail += 1
                failed_items.append({"file": path.name, "reason": "over Telegram 4 GB limit"})
                await _report(
                    phase="uploading",
                    done=i,
                    ok=ok,
                    fail=fail,
                    current=f"too large (>4GB): {path.name}",
                )
                logger.warning(
                    "Skipping oversize file for job %s: %s (%s bytes > 4 GiB)",
                    job_id,
                    path,
                    size,
                )
                continue
            try:
                msg = await client.send_file(
                    dest,
                    str(path),
                    caption=label,
                    force_document=True,
                )
                rec = {
                    "item_id": it.id,
                    "message_id": msg.id,
                    "job_id": job_id,
                    "channel_id": channel_id,
                    "file_name": it.file_name,
                    "file_size": it.file_size,
                }
                if defer_db_writes and pending_marks is not None:
                    pending_marks.append(rec)
                elif not db.mark_job_item_uploaded(it.id, msg.id):
                    if pending_marks is not None:
                        pending_marks.append(rec)
                    else:
                        logger.warning(
                            "DB mark failed for item %s — file is in channel; ingest will link later",
                            it.id,
                        )
                ok += 1
            except FloodWaitError as e:
                logger.warning("FloodWait %ss on job %s", e.seconds, job_id)
                import asyncio

                await asyncio.sleep(e.seconds + 2)
                fail += 1
                failed_items.append(
                    {"file": path.name, "reason": f"FloodWait ({e.seconds}s), retry not attempted"}
                )
            except Exception as e:
                logger.warning("Upload failed %s: %s", path.name, e)
                fail += 1
                failed_items.append({"file": path.name, "reason": str(e)[:120]})
            await _report(
                phase="uploading",
                done=i,
                ok=ok,
                fail=fail,
                current=path.name[:48],
            )
            if delay_s > 0:
                import asyncio

                await asyncio.sleep(delay_s)

    ok = fail = skipped_missing = skipped_oversize = 0
    failed_items: list[dict[str, str]] = []
    stopped = False
    await run_telethon(f"upload-job-{job_id}", _upload_with_client)

    deferred_remaining = 0
    if pending_marks:
        flushed = _flush_pending_marks(db, pending_marks, job_id=job_id)
        deferred_remaining = len(pending_marks)
        if flushed:
            logger.info("Flushed %s upload mark(s) for job #%s", flushed, job_id)
        if deferred_remaining:
            logger.warning(
                "Job #%s: %s item mark(s) still queued — channel posts will index when DB is free",
                job_id,
                deferred_remaining,
            )
    try:
        db.refresh_upload_job_status(job_id)
    except Exception as e:
        logger.warning("refresh_upload_job_status after job %s: %s", job_id, e)

    phase = "stopped" if stopped else "done"
    await _report(phase=phase, done=ok + fail, ok=ok, fail=fail, current="")
    return {
        "ok": ok,
        "fail": fail,
        "total": total,
        "skipped_missing": skipped_missing,
        "skipped_oversize": skipped_oversize,
        "failed_items": failed_items,
        "stopped": stopped,
        "db_deferred": deferred_remaining,
    }
