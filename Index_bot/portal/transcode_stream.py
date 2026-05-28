"""ffmpeg remux/transcode for in-browser play (MKV, AVI, MOV, etc.)."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import AsyncIterator

from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from portal.ffmpeg_mp4 import ffmpeg_mp4_pipe_command
from portal.stream_progress import add as progress_add
from portal.stream_progress import begin as progress_begin
from portal.stream_progress import fail as progress_fail
from portal.stream_progress import finish as progress_finish
from portal.streaming import _parse_range, browser_friendly_video

logger = logging.getLogger(__name__)

TRANSCODE_VIDEO_EXT = frozenset(
    {
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".ts",
        ".m2ts",
        ".mpg",
        ".mpeg",
        ".divx",
        ".xvid",
    }
)


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _cache_dir() -> Path:
    raw = os.getenv("PORTAL_TRANSCODE_CACHE", "portal_transcode_cache").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _max_transcode_bytes() -> int:
    try:
        mb = int(os.getenv("PORTAL_TRANSCODE_MAX_MB", "2048"))
    except ValueError:
        mb = 2048
    return max(100, mb) * 1024 * 1024


def needs_browser_transcode(file_name: str | None) -> bool:
    if browser_friendly_video(file_name):
        return False
    low = (file_name or "").lower()
    return any(low.endswith(ext) for ext in TRANSCODE_VIDEO_EXT)


def transcode_cache_path(upload_id: int) -> Path:
    return _cache_dir() / f"{int(upload_id)}.mp4"


def transcode_cache_part_path(upload_id: int) -> Path:
    return _cache_dir() / f"{int(upload_id)}.mp4.part"


def can_transcode_upload(upload) -> bool:
    if not upload or not ffmpeg_available():
        return False
    if not needs_browser_transcode(upload.file_name):
        return False
    size = int(upload.file_size or 0)
    if size > _max_transcode_bytes():
        return False
    return True


def _ffmpeg_cmd(*, reencode: bool, include_subtitles: bool = True) -> list[str]:
    return ffmpeg_mp4_pipe_command(reencode=reencode, include_subtitles=include_subtitles)


async def _write_stdin_from_telethon(
    proc: asyncio.subprocess.Process, client, msg, upload_id: int
) -> None:
    loop = asyncio.get_running_loop()
    try:
        async for chunk in client.iter_download(msg.media, request_size=512 * 1024):
            if not chunk:
                continue
            await loop.run_in_executor(None, proc.stdin.write, chunk)
            progress_add(upload_id, len(chunk))
    finally:
        if proc.stdin:
            proc.stdin.close()


async def _iter_transcode_attempt(
    client,
    msg,
    upload_id: int,
    *,
    reencode: bool,
    include_subtitles: bool = True,
) -> AsyncIterator[bytes]:
    part = transcode_cache_part_path(upload_id)
    part.unlink(missing_ok=True)

    proc = await asyncio.create_subprocess_exec(
        *_ffmpeg_cmd(reencode=reencode, include_subtitles=include_subtitles),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    if not proc.stdin or not proc.stdout:
        raise RuntimeError("ffmpeg failed to start")

    feed = asyncio.create_task(_write_stdin_from_telethon(proc, client, msg, upload_id))
    loop = asyncio.get_running_loop()
    cache_f = part.open("wb")
    got_bytes = False
    try:
        while True:
            chunk = await loop.run_in_executor(None, proc.stdout.read, 256 * 1024)
            if not chunk:
                break
            got_bytes = True
            cache_f.write(chunk)
            yield chunk
    finally:
        cache_f.close()
        await feed
        stderr = b""
        if proc.stderr:
            stderr = await proc.stderr.read()
        rc = await proc.wait()
        if rc != 0 and not got_bytes:
            err = stderr.decode(errors="replace")[:300]
            raise RuntimeError(err or f"ffmpeg exit {rc}")

        if got_bytes and part.exists() and part.stat().st_size > 0:
            part.replace(transcode_cache_path(upload_id))


async def _iter_transcode_live(client, msg, upload_id: int) -> AsyncIterator[bytes]:
    file_size = int(getattr(msg, "file", None) and getattr(msg.file, "size", 0) or 0)
    progress_begin(upload_id, 0, max(0, file_size - 1), file_size)
    last_err = ""
    attempts = (
        (False, True),
        (False, False),
        (True, True),
        (True, False),
    )
    try:
        for reencode, include_subs in attempts:
            try:
                async for chunk in _iter_transcode_attempt(
                    client,
                    msg,
                    upload_id,
                    reencode=reencode,
                    include_subtitles=include_subs,
                ):
                    yield chunk
                progress_finish(upload_id)
                return
            except Exception as e:
                last_err = str(e)
                logger.warning(
                    "transcode upload %s reencode=%s subs=%s: %s",
                    upload_id,
                    reencode,
                    include_subs,
                    e,
                )
                transcode_cache_part_path(upload_id).unlink(missing_ok=True)
        progress_fail(upload_id, last_err[:200])
        raise HTTPException(
            503,
            "Could not convert for browser play — try Telegram play",
        )
    except HTTPException:
        raise
    except Exception as e:
        progress_fail(upload_id, str(e)[:200])
        raise HTTPException(503, "Transcode failed") from e


async def _iter_file_range(path: Path, start: int, end: int) -> AsyncIterator[bytes]:
    chunk = 512 * 1024
    with path.open("rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def _mp4_stream_headers(*, start: int, end: int, total: int, partial: bool) -> dict[str, str]:
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": "video/mp4",
        "Content-Disposition": 'inline; filename="play.mp4"',
        "Content-Length": str(end - start + 1),
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return headers


async def stream_transcoded_upload(
    upload,
    msg,
    *,
    range_header: str | None,
    client,
) -> StreamingResponse:
    """Serve MP4 from cache or live ffmpeg transcode."""
    uid = int(upload.id)
    cached = transcode_cache_path(uid)
    if cached.exists() and cached.stat().st_size > 0:
        total = cached.stat().st_size
        start, end, partial = _parse_range(range_header, total)
        status = 206 if partial else 200
        return StreamingResponse(
            _iter_file_range(cached, start, end),
            status_code=status,
            headers=_mp4_stream_headers(
                start=start, end=end, total=total, partial=partial
            ),
        )

    if range_header and range_header.strip().lower().startswith("bytes="):
        raise HTTPException(
            503,
            "Seek not available until conversion finishes — start playback from the beginning",
        )

    return StreamingResponse(
        _iter_transcode_live(client, msg, uid),
        status_code=200,
        headers={
            "Content-Type": "video/mp4",
            "Cache-Control": "no-store",
            "Transfer-Encoding": "chunked",
        },
    )
