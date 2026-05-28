"""
Poll registered source channels via Telethon (user session) when the bot is not admin.

Indexes new media posts directly (channel_id + message_id in the source archive).
Only messages newer than the last seen id are processed — use historical ingest for old posts.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import TYPE_CHECKING

from config import Config
from forward_ingest import extract_telethon_message_file, resolve_entity
from message_verify import telethon_configured, telethon_session_path
from upload_pipeline import index_channel_upload

if TYPE_CHECKING:
    from telegram.ext import Application

logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


def _telethon_ready() -> bool:
    return telethon_configured() and telethon_session_path().exists()


async def _get_client():
    import os

    from telethon import TelegramClient

    api_id = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()
    if not api_id or not api_hash:
        return None
    client = TelegramClient(str(telethon_session_path()), int(api_id), api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        return None
    return client


def _telethon_extracted(message) -> dict | None:
    info = extract_telethon_message_file(message)
    if not info:
        return None
    from media_utils import detect_file_kind

    return {
        "file_name": info["file_name"],
        "file_size": info.get("file_size"),
        "file_id": None,
        "file_unique_id": info.get("file_unique_id"),
        "file_kind": detect_file_kind(info["file_name"]),
    }


async def _after_index_hooks(application: "Application", upload_id: int, meta: dict) -> None:
    from bot import db, parser, tmdb_helper
    from tmdb_ingest_retry import schedule_tmdb_ingest_retry, should_queue_tmdb_retry
    from watch_channel import schedule_watch_publish

    if should_queue_tmdb_retry(meta, tmdb_helper=tmdb_helper):
        schedule_tmdb_ingest_retry(
            application,
            upload_id,
            db=db,
            parser=parser,
            tmdb_helper=tmdb_helper,
        )
    if meta.get("library_visible"):
        schedule_watch_publish(application, upload_id, library_visible=True)


async def _ingest_telethon_message(
    application: "Application",
    *,
    channel_id: str,
    message,
    extracted: dict,
) -> bool:
    """Index one new post; return True if a row was created or updated."""
    from bot import db, parser, tmdb_helper

    msg_id = int(message.id)
    if db.file_exists(channel_id, msg_id):
        return False

    upload, info = await asyncio.to_thread(
        functools.partial(
            index_channel_upload,
            db,
            parser,
            tmdb_helper,
            channel_id=channel_id,
            message_id=msg_id,
            source_channel_id=None,
            extracted=extracted,
        ),
    )
    if info.get("status") == "duplicate_hold":
        return False
    upload_id = upload.id if upload else None
    meta = info.get("meta") or {}
    if upload_id:
        await _after_index_hooks(application, upload_id, meta)
    logger.info(
        "Member watch indexed %s in channel %s (upload #%s)",
        extracted.get("file_name"),
        channel_id,
        upload_id or "?",
    )
    return bool(upload_id)


async def _poll_one_channel(
    client,
    application: "Application",
    channel,
    *,
    db,
) -> tuple[int, int]:
    """
    Check for new indexable posts. Returns (indexed_count, new_last_seen_id).
    """
    channel_id = str(channel.channel_id)
    last_seen = getattr(channel, "telethon_last_seen_message_id", None)
    try:
        last_seen = int(last_seen) if last_seen is not None else None
    except (TypeError, ValueError):
        last_seen = None

    entity = await resolve_entity(
        client,
        channel.channel_username or channel_id,
        peer_id=channel_id,
        display_name=channel.channel_title or channel_id,
    )

    if last_seen is None:
        async for message in client.iter_messages(entity, limit=1):
            mid = int(message.id)
            db.set_telethon_last_seen_message_id(channel_id, mid)
            db.set_telethon_poll_result(channel_id, last_seen_message_id=mid, indexed_count=0)
            logger.info(
                "Member watch baseline for %s at message id %s (new posts only)",
                channel.channel_title or channel_id,
                message.id,
            )
            return 0, mid
        db.set_telethon_poll_result(channel_id, indexed_count=0)
        return 0, 0

    indexed = 0
    max_id = last_seen
    batch = max(5, Config.TELETHON_MEMBER_WATCH_BATCH)
    pending: list = []

    async for message in client.iter_messages(
        entity,
        min_id=last_seen,
        reverse=True,
        limit=batch,
    ):
        mid = int(message.id)
        if mid <= last_seen:
            continue
        max_id = max(max_id, mid)
        extracted = _telethon_extracted(message)
        if not extracted:
            continue
        pending.append((message, extracted))

    for message, extracted in pending:
        if await _ingest_telethon_message(
            application,
            channel_id=channel_id,
            message=message,
            extracted=extracted,
        ):
            indexed += 1

    if max_id > last_seen:
        db.set_telethon_last_seen_message_id(channel_id, max_id)
    db.set_telethon_poll_result(
        channel_id,
        last_seen_message_id=max_id if max_id > (last_seen or 0) else last_seen,
        indexed_count=indexed,
    )
    return indexed, max_id


async def run_member_watch_tick(application: "Application") -> dict:
    """One poll pass over all enabled channels."""
    from bot import db
    import bot_busy
    from telethon_gateway import run_telethon

    stats = {"channels": 0, "indexed": 0, "skipped": 0, "errors": 0}
    if not Config.TELETHON_MEMBER_WATCH_ENABLED:
        return stats
    if not _telethon_ready():
        return stats
    if bot_busy.is_busy(application):
        stats["skipped"] = 1
        return stats

    channels = await asyncio.to_thread(db.list_telethon_watch_channels)
    if not channels:
        return stats

    async def _tick_with_client(client):
        out = {"channels": 0, "indexed": 0, "skipped": 0, "errors": 0}
        for channel in channels:
            out["channels"] += 1
            try:
                n, _ = await _poll_one_channel(
                    client, application, channel, db=db
                )
                out["indexed"] += n
            except Exception as e:
                out["errors"] += 1
                logger.warning(
                    "Member watch failed for %s: %s",
                    getattr(channel, "channel_title", None) or channel.channel_id,
                    e,
                )
            await asyncio.sleep(0.35)
        return out

    try:
        stats = await run_telethon("member-watch-tick", _tick_with_client)
    except Exception as e:
        logger.warning("Member watch tick failed: %s", e)
        stats["errors"] += 1

    if stats["indexed"]:
        logger.info(
            "Member watch tick: %s new file(s) across %s channel(s)",
            stats["indexed"],
            stats["channels"],
        )
    application.bot_data["member_watch_last_stats"] = stats
    return stats


async def _worker_loop(application: "Application") -> None:
    tick = max(60.0, Config.TELETHON_MEMBER_WATCH_INTERVAL_S)
    logger.info("Telethon member watch started (tick=%ss)", tick)
    while True:
        try:
            await asyncio.sleep(tick)
            await run_member_watch_tick(application)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Member watch worker tick failed")


def start_member_watch_worker(application: "Application") -> None:
    """Start background polling for member-only source channels."""
    global _worker_task
    if not Config.TELETHON_MEMBER_WATCH_ENABLED:
        logger.info("Telethon member watch disabled (TELETHON_MEMBER_WATCH_ENABLED)")
        return
    if _worker_task and not _worker_task.done():
        return
    _worker_task = application.create_task(_worker_loop(application))


async def stop_member_watch_worker() -> None:
    global _worker_task
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    _worker_task = None
