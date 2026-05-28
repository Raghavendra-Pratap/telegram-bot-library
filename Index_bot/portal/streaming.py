"""Browser playback: stream library files from Telegram with HTTP Range support."""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from typing import AsyncIterator

from fastapi import HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from telegram import Bot

from config import Config
from database import Database
from message_verify import telethon_configured
from portal.stream_progress import add as progress_add
from portal.stream_progress import begin as progress_begin
from portal.stream_progress import fail as progress_fail
from portal.stream_progress import finish as progress_finish

logger = logging.getLogger(__name__)
_db = Database()
_client = None
_client_lock = asyncio.Lock()


def telethon_stream_ready() -> bool:
    from message_verify import telethon_portal_session_path

    return telethon_configured() and telethon_portal_session_path().is_file()


def can_stream_in_browser(upload) -> bool:
    if not upload:
        return False
    if telethon_stream_ready():
        return True
    size = int(upload.file_size or 0)
    return bool(upload.file_id) and 0 < size <= 20 * 1024 * 1024


def browser_friendly_video(file_name: str | None) -> bool:
    """HTML5 video plays these natively without ffmpeg."""
    low = (file_name or "").lower()
    return low.endswith((".mp4", ".m4v", ".webm"))


def can_play_in_browser(upload) -> bool:
    """Whether portal can play this upload in the browser (native or ffmpeg transcode)."""
    if not can_stream_in_browser(upload):
        return False
    if browser_friendly_video(upload.file_name):
        return True
    from portal.transcode_stream import can_transcode_upload

    return can_transcode_upload(upload)


def content_type_for_filename(file_name: str | None) -> str:
    mt, _ = mimetypes.guess_type(file_name or "")
    if mt:
        return mt
    low = (file_name or "").lower()
    if low.endswith((".mkv", ".mka")):
        return "video/x-matroska"
    if low.endswith((".mp4", ".m4v")):
        return "video/mp4"
    if low.endswith(".webm"):
        return "video/webm"
    return "application/octet-stream"


def _parse_range(range_header: str | None, total: int) -> tuple[int, int, bool]:
    """Return (start, end inclusive, is_partial)."""
    if total <= 0:
        return 0, 0, False
    if not range_header or not range_header.strip().lower().startswith("bytes="):
        return 0, total - 1, False
    spec = range_header.strip()[6:].split(",", 1)[0].strip()
    if spec.startswith("-"):
        suffix = int(spec[1:] or "0")
        start = max(0, total - suffix)
        return start, total - 1, True
    if "-" not in spec:
        raise HTTPException(416, "Invalid Range")
    start_s, end_s = spec.split("-", 1)
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else total - 1
    if start >= total or start > end:
        raise HTTPException(
            416,
            "Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{total}"},
        )
    end = min(end, total - 1)
    return start, end, True


async def _get_telethon_client():
    global _client
    from telethon import TelegramClient

    api_id = os.getenv("API_ID", "").strip()
    api_hash = os.getenv("API_HASH", "").strip()
    if not api_id or not api_hash:
        raise HTTPException(503, "Telethon not configured (API_ID / API_HASH)")
    async with _client_lock:
        if _client is None or not _client.is_connected():
            from message_verify import telethon_portal_session_path

            _client = TelegramClient(
                str(telethon_portal_session_path()),
                int(api_id),
                api_hash,
            )
            await _client.connect()
            if not await _client.is_user_authorized():
                raise HTTPException(
                    503,
                    "Telethon not logged in for portal — run: python telethon_login_portal.py",
                )
    return _client


async def _resolve_telethon_message(upload):
    """Find the Telegram message with media (source channel first for forwards)."""
    from forward_ingest import resolve_entity
    from watch_library import upload_stream_channel_ids

    client = await _get_telethon_client()
    mid = int(upload.message_id)
    last_err: Exception | None = None
    for cid in upload_stream_channel_ids(upload):
        ch = _db.get_channel(cid)
        ref = (ch.channel_username if ch and ch.channel_username else None) or cid
        ch_label = None
        if ch:
            ch_label = getattr(ch, "channel_title", None) or getattr(
                ch, "channel_username", None
            )
        try:
            entity = await resolve_entity(
                client,
                str(ref),
                peer_id=cid,
                display_name=ch_label or str(cid),
            )
            msg = await client.get_messages(entity, ids=mid)
            if msg and getattr(msg, "media", None):
                return msg
        except Exception as e:
            last_err = e
            logger.warning(
                "stream resolve upload %s channel %s: %s",
                upload.id,
                cid,
                e,
            )
    if last_err:
        logger.warning(
            "stream message not found upload %s (tried %s): %s",
            upload.id,
            upload_stream_channel_ids(upload),
            last_err,
        )
    return None


async def _iter_telethon_bytes(
    upload, start: int, end: int, *, msg=None
) -> AsyncIterator[bytes]:
    if msg is None:
        msg = await _resolve_telethon_message(upload)
    if not msg or not getattr(msg, "media", None):
        progress_fail(upload.id, "Media not found in channel")
        return

    client = await _get_telethon_client()
    limit = end - start + 1
    file_size = int(upload.file_size or 0)
    progress_begin(upload.id, start, end, file_size)
    try:
        async for chunk in client.iter_download(
            msg.media,
            offset=start,
            limit=limit,
            request_size=512 * 1024,
        ):
            if chunk:
                progress_add(upload.id, len(chunk))
                yield chunk
    except Exception as e:
        progress_fail(upload.id, str(e))
        logger.exception("Telethon stream failed upload %s: %s", upload.id, e)
        return
    finally:
        progress_finish(upload.id)


def _stream_headers(
    upload,
    *,
    start: int,
    end: int,
    total: int,
    partial: bool,
) -> dict[str, str]:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": content_type_for_filename(upload.file_name),
        "Content-Disposition": f'inline; filename="{os.path.basename(upload.file_name or "video")}"',
    }
    length = end - start + 1
    headers["Content-Length"] = str(length)
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return headers


async def stream_upload(
    upload,
    *,
    range_header: str | None,
    bot: Bot,
):
    from portal.transcode_stream import can_transcode_upload, stream_transcoded_upload

    total = int(upload.file_size or 0)

    if telethon_stream_ready():
        msg = await _resolve_telethon_message(upload)
        if not msg:
            raise HTTPException(
                404,
                "Media not found in channel — message may have been deleted, or try Telegram play",
            )
        client = await _get_telethon_client()
        if can_transcode_upload(upload):
            return await stream_transcoded_upload(
                upload, msg, range_header=range_header, client=client
            )
        start, end, partial = _parse_range(range_header, total)
        status = 206 if partial else 200
        return StreamingResponse(
            _iter_telethon_bytes(upload, start, end, msg=msg),
            status_code=status,
            headers=_stream_headers(
                upload, start=start, end=end, total=total, partial=partial
            ),
        )

    if not upload.file_id or total <= 0 or total > 20 * 1024 * 1024:
        raise HTTPException(
            503,
            "Large files need Telethon for browser play — set API_ID/API_HASH and run telethon_login.py",
        )
    try:
        tg_file = await bot.get_file(upload.file_id)
        url = tg_file.file_path
        if not url:
            raise HTTPException(502, "Could not resolve file")
        if not url.startswith("http"):
            url = f"https://api.telegram.org/file/bot{Config.BOT_TOKEN}/{url}"
        return RedirectResponse(url)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("bot stream %s: %s", upload.id, e)
        raise HTTPException(502, str(e)[:120]) from e
