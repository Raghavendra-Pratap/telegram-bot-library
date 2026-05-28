"""Background MKV/AVI → MP4 conversion with embedded + sidecar subtitles."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from threading import Lock
from typing import Any

from portal.ffmpeg_mp4 import ffmpeg_mp4_command
from portal.streaming import _get_telethon_client, _resolve_telethon_message, telethon_stream_ready
from portal.transcode_stream import (
    _cache_dir,
    _max_transcode_bytes,
    can_transcode_upload,
    ffmpeg_available,
    needs_browser_transcode,
    transcode_cache_path,
)

logger = logging.getLogger(__name__)

_lock = Lock()
_jobs: dict[int, dict[str, Any]] = {}
_tasks: dict[int, asyncio.Task] = {}


def _include_external_subs() -> bool:
    raw = os.getenv("PORTAL_CONVERT_EXTERNAL_SUBS", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def convert_status(upload_id: int) -> dict | None:
    with _lock:
        st = _jobs.get(int(upload_id))
        return dict(st) if st else None


def can_convert_upload(upload) -> bool:
    if not upload or not ffmpeg_available() or not telethon_stream_ready():
        return False
    if not needs_browser_transcode(upload.file_name):
        return False
    return can_transcode_upload(upload)


def mp4_cache_ready(upload_id: int) -> bool:
    p = transcode_cache_path(int(upload_id))
    return p.exists() and p.stat().st_size > 0


async def _download_message_to_path(client, msg, dest: Path, upload_id: int) -> None:
    from portal.stream_progress import add as progress_add
    from portal.stream_progress import begin as progress_begin
    from portal.stream_progress import finish as progress_finish

    dest.parent.mkdir(parents=True, exist_ok=True)
    file_size = int(getattr(msg, "file", None) and getattr(msg.file, "size", 0) or 0)
    progress_begin(upload_id, 0, max(0, file_size - 1), file_size)
    loop = asyncio.get_running_loop()
    with dest.open("wb") as f:
        async for chunk in client.iter_download(msg.media, request_size=512 * 1024):
            if chunk:
                await loop.run_in_executor(None, f.write, chunk)
                progress_add(upload_id, len(chunk))
    progress_finish(upload_id)


def _run_ffmpeg_file(
    src: Path,
    dest: Path,
    *,
    reencode: bool,
    include_embedded_subs: bool,
    extra_subs: list[str],
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    cmd = ffmpeg_mp4_command(
        input_path=str(src),
        output_path=str(part),
        reencode=reencode,
        include_embedded_subs=include_embedded_subs,
        extra_subtitle_paths=extra_subs,
        streaming=False,
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[:400]
        raise RuntimeError(err or f"ffmpeg exit {proc.returncode}")
    part.replace(dest)


async def _convert_worker(upload_id: int, db) -> None:
    uid = int(upload_id)
    upload = db.get_file_upload(uid)
    if not upload:
        _set_job(uid, phase="failed", error="Upload not found")
        return
    if int(upload.file_size or 0) > _max_transcode_bytes():
        _set_job(uid, phase="failed", error="File too large for conversion")
        return

    out_path = transcode_cache_path(uid)
    if out_path.exists() and out_path.stat().st_size > 0:
        _set_job(uid, phase="complete", output_path=str(out_path), cached=True)
        return

    _set_job(uid, phase="downloading", bytes_done=0)
    try:
        msg = await _resolve_telethon_message(upload)
        if not msg:
            raise RuntimeError("Media not found in Telegram channel")
        client = await _get_telethon_client()
        ext = Path(upload.file_name or "video.mkv").suffix or ".mkv"
        src_path = _cache_dir() / f"{uid}.src{ext}"
        await _download_message_to_path(client, msg, src_path, uid)

        extra_paths: list[str] = []
        if _include_external_subs():
            _set_job(uid, phase="fetching_subtitles")
            for sub_up in db.find_subtitle_sidecar_uploads(upload)[:4]:
                sub_msg = await _resolve_telethon_message(sub_up)
                if not sub_msg:
                    continue
                sub_dest = _cache_dir() / f"{uid}.sub{Path(sub_up.file_name).suffix}"
                await _download_message_to_path(client, sub_msg, sub_dest, uid)
                extra_paths.append(str(sub_dest))

        _set_job(uid, phase="converting")
        attempts = (
            (False, True, extra_paths),
            (False, False, extra_paths),
            (True, True, extra_paths),
            (True, True, []),
            (True, False, []),
        )
        last_err = ""
        for reencode, include_subs, extras in attempts:
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda r=reencode, s=include_subs, e=extras: _run_ffmpeg_file(
                        src_path,
                        out_path,
                        reencode=r,
                        include_embedded_subs=s,
                        extra_subs=e,
                    ),
                )
                _set_job(
                    uid,
                    phase="complete",
                    output_path=str(out_path),
                    subtitle_tracks=len(extras) + (1 if include_subs else 0),
                )
                return
            except Exception as e:
                last_err = str(e)
                logger.warning(
                    "convert upload %s reencode=%s subs=%s extras=%s: %s",
                    uid,
                    reencode,
                    include_subs,
                    len(extras),
                    e,
                )
                out_path.unlink(missing_ok=True)
        _set_job(uid, phase="failed", error=last_err[:200] or "Conversion failed")
    except Exception as e:
        logger.exception("convert upload %s failed: %s", uid, e)
        _set_job(uid, phase="failed", error=str(e)[:200])
    finally:
        for pattern in (f"{uid}.src*", f"{uid}.sub*"):
            for p in _cache_dir().glob(pattern):
                p.unlink(missing_ok=True)
        with _lock:
            _tasks.pop(uid, None)


def _set_job(upload_id: int, **fields: Any) -> None:
    with _lock:
        st = _jobs.setdefault(int(upload_id), {"upload_id": int(upload_id)})
        st.update(fields)


def schedule_convert(upload_id: int, db) -> dict[str, Any]:
    uid = int(upload_id)
    upload = db.get_file_upload(uid)
    if not upload:
        return {"ok": False, "error": "Upload not found"}
    if not can_convert_upload(upload):
        return {
            "ok": False,
            "error": "Conversion unavailable (needs ffmpeg, Telethon, and a supported video format under size limit)",
        }
    if mp4_cache_ready(uid):
        return {
            "ok": True,
            "upload_id": uid,
            "phase": "complete",
            "cached": True,
            "message": "MP4 already converted",
        }
    with _lock:
        existing = _tasks.get(uid)
        if existing and not existing.done():
            return {
                "ok": True,
                "upload_id": uid,
                "phase": _jobs.get(uid, {}).get("phase", "queued"),
                "message": "Conversion already running",
            }
    _set_job(uid, phase="queued")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return {"ok": False, "error": "No async event loop"}
    task = loop.create_task(_convert_worker(uid, db))
    with _lock:
        _tasks[uid] = task
    return {"ok": True, "upload_id": uid, "phase": "queued", "message": "Conversion started"}
