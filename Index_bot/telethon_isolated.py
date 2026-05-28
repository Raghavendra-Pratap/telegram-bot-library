"""
Clone Telethon session files so short jobs don't fight member-watch / portal streaming.

Telethon stores auth in a SQLite file (`forward_ingest.session`). Only one writer
should touch that file at a time. Long-lived clients (member watch tick, portal stream)
keep the canonical session open; upload/route jobs use a temporary copy.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from message_verify import telethon_session_path

logger = logging.getLogger(__name__)


def clone_telethon_session(
    source: Path | None = None,
    *,
    prefix: str = "idxbot-telethon-",
) -> tuple[Path, Path | None]:
    """
    Copy session (+ journal if present) to a temp dir.

    Returns (path_for_TelegramClient, temp_dir_to_delete_or_None).
  """
    source = source or telethon_session_path()
    if not source.is_file():
        return source, None
    tmp_dir = Path(tempfile.mkdtemp(prefix=prefix))
    dest = tmp_dir / source.name
    try:
        shutil.copy2(source, dest)
        journal = Path(f"{source}-journal")
        if journal.is_file():
            shutil.copy2(journal, Path(f"{dest}-journal"))
    except Exception as e:
        logger.warning("Could not clone Telethon session %s: %s", source, e)
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return source, None
    return dest, tmp_dir


def _is_session_locked_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "database is locked" in msg or "database is busy" in msg


@asynccontextmanager
async def isolated_telethon_client(
    api_id: int | str,
    api_hash: str,
    *,
    session_path: Path | None = None,
    prefix: str = "idxbot-telethon-",
    start_retries: int = 5,
) -> AsyncIterator:
    """Connected Telethon client using a cloned session file."""
    from telethon import TelegramClient

    use_path, tmp_dir = clone_telethon_session(session_path, prefix=prefix)
    client = TelegramClient(str(use_path), int(api_id), api_hash)
    last_err: BaseException | None = None
    try:
        for attempt in range(start_retries):
            try:
                await client.start()
                last_err = None
                break
            except Exception as e:
                last_err = e
                if not _is_session_locked_error(e) or attempt >= start_retries - 1:
                    raise
                wait = min(4.0, 0.4 * (2**attempt))
                logger.warning(
                    "Telethon session busy (attempt %s/%s), retry in %.1fs",
                    attempt + 1,
                    start_retries,
                    wait,
                )
                await asyncio.sleep(wait)
        if last_err is not None:
            raise last_err
        yield client
    finally:
        try:
            await client.disconnect()
        except Exception as e:
            logger.debug("Telethon disconnect: %s", e)
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
