"""Route classified ingest uploads to per-lane pipeline source channels (Telethon forward)."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from config import Config
from pipeline_setup import resolve_source_channel_for_upload_type

logger = logging.getLogger(__name__)


def route_target_for_upload(db, upload) -> str | None:
    """Pipeline source channel for this upload's content lane."""
    lane = getattr(upload, "content_lane", None) or "media"
    return resolve_source_channel_for_upload_type(lane, db=db)


def should_auto_route_upload(db, upload) -> tuple[bool, str | None]:
    if not Config.PIPELINE_AUTO_ROUTE:
        return False, None
    if (getattr(upload, "ingest_state", None) or "") != "normal":
        return False, None
    ch = db.get_channel(str(upload.channel_id))
    if not ch or not getattr(ch, "is_ingest_channel", False):
        return False, None
    target = route_target_for_upload(db, upload)
    if not target or str(target) == str(upload.channel_id):
        return False, None
    return True, target


def maybe_queue_route_after_index(db, upload) -> dict:
    """Mark pending route after ingest index; caller schedules Telethon job."""
    ok, target = should_auto_route_upload(db, upload)
    if not ok or not target:
        return {"queued": False}
    db.set_upload_pipeline_route(
        upload.id, status="pending", target_channel_id=target
    )
    return {"queued": True, "target_channel_id": target, "upload_id": upload.id}


async def forward_upload_to_bucket(upload_id: int, *, db=None) -> dict:
    from database import Database
    from forward_ingest import resolve_entity
    from telethon.errors import FloodWaitError

    db = db or Database()
    upload = db.get_file_upload(upload_id)
    if not upload:
        return {"ok": False, "error": "upload not found"}

    target = upload.pipeline_route_target_channel_id or route_target_for_upload(
        db, upload
    )
    if not target:
        db.set_upload_pipeline_route(upload_id, status="skipped", error="no target")
        return {"ok": False, "error": "no pipeline source for lane"}

    if str(target) == str(upload.channel_id):
        db.set_upload_pipeline_route(upload_id, status="skipped", error="same channel")
        return {"ok": False, "error": "already on target channel"}

    api_id = os.getenv("API_ID")
    api_hash = os.getenv("API_HASH")
    if not api_id or not api_hash:
        db.set_upload_pipeline_route(upload_id, status="failed", error="missing API_ID")
        return {"ok": False, "error": "Telethon not configured"}

    from message_verify import telethon_session_path
    from telethon_gateway import run_telethon

    session = telethon_session_path()
    if not session.is_file():
        db.set_upload_pipeline_route(
            upload_id, status="failed", error="run telethon_login.py"
        )
        return {"ok": False, "error": "no Telethon session"}

    async def _forward_with_client(client):
        src = await resolve_entity(
            client, str(upload.channel_id), display_name="ingest"
        )
        dest = await resolve_entity(client, str(target), display_name="bucket")
        try:
            result = await client.forward_messages(
                dest, upload.message_id, from_peer=src
            )
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
            result = await client.forward_messages(
                dest, upload.message_id, from_peer=src
            )
        new_msg = result[0] if isinstance(result, list) else result
        new_id = int(getattr(new_msg, "id", 0) or 0)
        if not new_id:
            raise RuntimeError("forward returned no message id")
        db.relocate_upload_message(upload_id, str(target), new_id)
        db.set_upload_pipeline_route(upload_id, status="routed", error=None)
        return {"ok": True, "channel_id": str(target), "message_id": new_id}

    try:
        return await run_telethon(f"route:{upload_id}", _forward_with_client)
    except Exception as e:
        logger.exception("forward_upload_to_bucket #%s", upload_id)
        err = str(e)[:500]
        if "database is locked" in err.lower():
            err = "Telethon session busy (retry route in a minute)"
        db.set_upload_pipeline_route(upload_id, status="failed", error=err)
        return {"ok": False, "error": err}


def schedule_pipeline_route(app, upload_id: int) -> None:
    """Queue background Telethon forward (bot application)."""

    async def _job() -> None:
        await forward_upload_to_bucket(upload_id)

    async def _run() -> None:
        from job_queue import enqueue_background

        await enqueue_background(app, f"route:{upload_id}", _job, exclusive=False)

    app.create_task(_run())


def try_complete_route_on_bucket_post(
    db, *, channel_id: str, message_id: int, fingerprint: str
) -> bool:
    """
    When a forward lands in a bucket channel, attach message to pending upload
    instead of creating a duplicate index row.
    """
    pending = db.find_upload_pending_route(fingerprint, channel_id)
    if not pending:
        return False
    db.relocate_upload_message(pending.id, channel_id, message_id)
    db.set_upload_pipeline_route(pending.id, status="routed", error=None)
    return True
