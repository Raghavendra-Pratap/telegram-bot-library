"""
Check whether indexed channel posts still exist (Telethon user session).

Used for:
- Admin periodic sweep (verify_uploads.py / bot menu)
- On-demand checks when a user opens Watch
"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import RPCError
from telethon.tl.types import MessageEmpty

from forward_ingest import resolve_entity

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
load_dotenv(_ROOT / ".env")


def telethon_session_path() -> Path:
    session_name = os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session")
    path = Path(session_name)
    if not path.is_absolute():
        path = _ROOT / path
    return path


def telethon_configured() -> bool:
    api_id = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()
    return bool(api_id and api_hash and api_id != "your_telegram_api_id")


def _message_is_available(msg) -> bool:
    if msg is None:
        return False
    if isinstance(msg, MessageEmpty):
        return False
    return bool(getattr(msg, "id", None))


def upload_needs_verify(upload, *, max_age_minutes: int = 15) -> bool:
    """True if we should re-check this row (never checked or stale)."""
    checked = getattr(upload, "message_checked_at", None)
    if checked is None:
        return True
    if isinstance(checked, str):
        return True
    age = datetime.utcnow() - checked
    return age > timedelta(minutes=max_age_minutes)


async def check_messages_batch(
    client: TelegramClient,
    channel_id: str,
    message_ids: list[int],
) -> dict[int, bool | None]:
    """
    Return message_id -> available (True/False) or None if channel could not be resolved.
    """
    if not message_ids:
        return {}
    try:
        entity = await resolve_entity(
            client, str(channel_id), peer_id=channel_id
        )
    except Exception as e:
        logger.warning("Cannot resolve channel %s: %s", channel_id, e)
        return {mid: None for mid in message_ids}

    out: dict[int, bool | None] = {}
    try:
        msgs = await client.get_messages(entity, ids=message_ids)
    except RPCError as e:
        err = str(e).upper()
        if "MESSAGE_ID_INVALID" in err or "MSG_ID_INVALID" in err:
            return {mid: False for mid in message_ids}
        logger.warning("get_messages failed for %s: %s", channel_id, e)
        return {mid: None for mid in message_ids}
    except Exception as e:
        logger.warning("get_messages failed for %s: %s", channel_id, e)
        return {mid: None for mid in message_ids}

    if not isinstance(msgs, list):
        msgs = [msgs]
    by_id = {}
    for i, mid in enumerate(message_ids):
        msg = msgs[i] if i < len(msgs) else None
        by_id[mid] = _message_is_available(msg)
    for mid in message_ids:
        out[mid] = by_id.get(mid, False)
    return out


async def verify_upload_rows(
    client: TelegramClient,
    uploads: Iterable,
    db,
    *,
    force: bool = False,
    max_age_minutes: int = 15,
) -> dict[int, bool | None]:
    """
    Check uploads via Telethon and persist message_available / message_checked_at.
    Returns upload.id -> availability (None = could not verify).
    """
    to_check = [
        u
        for u in uploads
        if force or upload_needs_verify(u, max_age_minutes=max_age_minutes)
    ]
    results: dict[int, bool | None] = {}
    if not to_check:
        for u in uploads:
            avail = getattr(u, "message_available", None)
            if avail is False:
                results[u.id] = False
            elif avail is True:
                results[u.id] = True
        return results

    by_channel: dict[str, list] = defaultdict(list)
    for u in to_check:
        by_channel[str(u.channel_id)].append(u)

    now = datetime.utcnow()
    for channel_id, ch_uploads in by_channel.items():
        ids = [u.message_id for u in ch_uploads]
        batch = await check_messages_batch(client, channel_id, ids)
        for u in ch_uploads:
            available = batch.get(u.message_id)
            if available is not None:
                db.set_upload_message_status(u.id, available, checked_at=now)
                u.message_available = available
                u.message_checked_at = now
            results[u.id] = available

    for u in uploads:
        if u.id not in results:
            if getattr(u, "message_available", None) is False:
                results[u.id] = False
            else:
                results[u.id] = True if u.message_available is not False else False
    return results


def filter_watchable_uploads(uploads: list) -> list:
    """Hide posts confirmed deleted; keep unchecked (NULL) and available."""
    return [u for u in uploads if getattr(u, "message_available", None) is not False]


async def run_verify_sweep(
    db,
    *,
    limit: int = 500,
    stale_hours: float = 24,
    force: bool = False,
    api_id: int | None = None,
    api_hash: str | None = None,
    session_path: Path | None = None,
    progress_callback=None,
) -> tuple[int, int, int, int]:
    """
    Verify up to `limit` uploads. Returns (checked, available, unavailable, skipped).
    """
    if not telethon_configured():
        raise RuntimeError(
            "Set API_ID and API_HASH in .env and run python telethon_login.py"
        )

    uploads = db.get_uploads_for_verify(
        limit=limit, stale_hours=0 if force else stale_hours
    )
    if not uploads:
        return 0, 0, 0, 0

    api_id = api_id or int(str(os.getenv("API_ID")).strip())
    api_hash = api_hash or str(os.getenv("API_HASH")).strip()
    session_path = session_path or telethon_session_path()

    checked = available = unavailable = skipped = 0
    async with TelegramClient(str(session_path), api_id, api_hash) as client:
        chunk_size = 80
        for start in range(0, len(uploads), chunk_size):
            chunk = uploads[start : start + chunk_size]
            results = await verify_upload_rows(
                client, chunk, db, force=True, max_age_minutes=0
            )
            for avail in results.values():
                if avail is None:
                    skipped += 1
                else:
                    checked += 1
                    if avail:
                        available += 1
                    else:
                        unavailable += 1
            if progress_callback:
                await progress_callback(
                    min(start + chunk_size, len(uploads)), len(uploads)
                )

    return checked, available, unavailable, skipped


async def verify_upload_list_for_watch(
    uploads: list,
    db,
    *,
    max_age_minutes: int = 15,
) -> list:
    """
    Verify stale rows then return uploads still watchable (not marked deleted).
    If Telethon is not configured, returns uploads unchanged.
    """
    if not uploads:
        return uploads
    if not telethon_configured() or not telethon_session_path().exists():
        return filter_watchable_uploads(uploads)

    api_id = int(str(os.getenv("API_ID")).strip())
    api_hash = str(os.getenv("API_HASH")).strip()
    session_path = telethon_session_path()

    async with TelegramClient(str(session_path), api_id, api_hash) as client:
        await verify_upload_rows(
            client, uploads, db, force=False, max_age_minutes=max_age_minutes
        )
    return filter_watchable_uploads(uploads)
