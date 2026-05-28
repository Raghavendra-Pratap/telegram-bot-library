#!/usr/bin/env python3
"""
Upload pipeline worker (no bot polling, no portal).

Run this on a file host (e.g. Mac) that has:
- access to the shared DATABASE_URL
- local media files referenced by upload job `local_path`
- Telethon credentials/session
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import socket
from pathlib import Path

from database import Database
from message_verify import telethon_configured, telethon_session_path
from upload_job_runner import run_upload_job

logging.basicConfig(
    level=getattr(logging, os.getenv("UPLOAD_WORKER_LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("upload_worker")


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _acquire_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(f"Another upload worker is already running ({lock_path}).")
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def _runnable_job_id(db: Database, scan_limit: int) -> int | None:
    jobs = db.list_upload_jobs(limit=scan_limit)
    jobs = sorted(jobs, key=lambda j: int(getattr(j, "id", 0) or 0))
    for job in jobs:
        if str(getattr(job, "status", "")) not in ("planned", "uploading", "failed"):
            continue
        if not getattr(job, "target_channel_id", None):
            continue
        items = db.get_upload_job_items(int(job.id))
        candidates = [it for it in items if it.decision in ("upload", "force") and it.local_path]
        if not candidates:
            continue
        local_ready = 0
        for it in candidates:
            try:
                if Path(str(it.local_path)).is_file():
                    local_ready += 1
            except Exception:
                continue
        if local_ready > 0:
            return int(job.id)
    return None


async def _run_once(db: Database, *, api_id: int, api_hash: str, delay_s: float, scan_limit: int) -> bool:
    job_id = _runnable_job_id(db, scan_limit)
    if not job_id:
        return False
    logger.info("Picked upload job #%s", job_id)
    db.set_upload_job_status(job_id, "uploading")
    result = await run_upload_job(
        job_id=job_id,
        session_path=telethon_session_path(),
        api_id=api_id,
        api_hash=api_hash,
        delay_s=delay_s,
    )
    logger.info(
        "Job #%s finished: ok=%s fail=%s total=%s stopped=%s",
        job_id,
        result.get("ok"),
        result.get("fail"),
        result.get("total"),
        result.get("stopped"),
    )
    return True


async def main() -> int:
    enabled = (os.getenv("UPLOAD_WORKER_ENABLED", "true").strip().lower() in ("1", "true", "yes"))
    if not enabled:
        logger.info("UPLOAD_WORKER_ENABLED is false; exiting.")
        return 0

    if not telethon_configured():
        logger.error("Telethon not configured. Set API_ID/API_HASH in .env")
        return 1
    session = telethon_session_path()
    if not session.is_file():
        logger.error("Telethon session missing at %s. Run: python telethon_login.py", session)
        return 1

    api_id = int((os.getenv("API_ID") or "").strip())
    api_hash = (os.getenv("API_HASH") or "").strip()
    poll_s = max(2.0, _env_float("UPLOAD_WORKER_POLL_S", 12.0))
    delay_s = max(0.0, _env_float("UPLOAD_WORKER_SEND_DELAY_S", 3.0))
    scan_limit = max(5, _env_int("UPLOAD_WORKER_SCAN_LIMIT", 40))
    lock_path = Path(os.getenv("UPLOAD_WORKER_LOCK_PATH", ".upload_worker.lock")).expanduser().resolve()

    _lock_fh = _acquire_lock(lock_path)
    logger.info(
        "Upload worker started on %s (poll=%ss scan_limit=%s lock=%s)",
        socket.gethostname(),
        poll_s,
        scan_limit,
        lock_path,
    )
    db = Database()
    while True:
        try:
            ran = await _run_once(
                db, api_id=api_id, api_hash=api_hash, delay_s=delay_s, scan_limit=scan_limit
            )
            if not ran:
                await asyncio.sleep(poll_s)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Worker loop error: %s", e)
            await asyncio.sleep(min(30.0, poll_s))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
