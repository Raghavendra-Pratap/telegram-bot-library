"""
Single Telethon client + queue for all bot-side Telegram user-session work.

Prevents `forward_ingest.session` SQLite lock errors from parallel clients.
Portal uses a separate session file (see message_verify.telethon_portal_session_path).
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

from config import Config
from message_verify import telethon_configured, telethon_session_path

logger = logging.getLogger(__name__)

T = TypeVar("T")
ClientFn = Callable[[Any], Awaitable[T]]

_gateway: "TelethonGateway | None" = None


@dataclass
class _Op:
    name: str
    fn: ClientFn
    future: asyncio.Future


class TelethonGateway:
    """One connected Telethon client; all operations run serially on a worker task."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[_Op | None] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._client = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        if not Config.TELETHON_GATEWAY_ENABLED:
            logger.info("Telethon gateway disabled (TELETHON_GATEWAY_ENABLED=false)")
            return
        if not telethon_configured():
            logger.warning("Telethon gateway not started — API_ID/API_HASH missing")
            return
        session = telethon_session_path()
        if not session.is_file():
            logger.warning(
                "Telethon gateway not started — no session at %s (run telethon_login.py)",
                session,
            )
            return

        from telethon import TelegramClient

        api_id = int(os.getenv("API_ID", "").strip())
        api_hash = os.getenv("API_HASH", "").strip()
        self._client = TelegramClient(str(session), api_id, api_hash)
        import sqlite3

        last_err: BaseException | None = None
        for attempt in range(8):
            try:
                await self._client.start()
                last_err = None
                break
            except sqlite3.OperationalError as e:
                last_err = e
                if "database is locked" not in str(e).lower() or attempt >= 7:
                    raise
                logger.warning(
                    "Telethon session locked (attempt %s/8) — "
                    "stop portal/other Telethon clients using %s",
                    attempt + 1,
                    session.name,
                )
                await asyncio.sleep(min(2.0, 0.25 * (2**attempt)))
        if last_err:
            raise last_err
        if not await self._client.is_user_authorized():
            await self._client.disconnect()
            self._client = None
            logger.error("Telethon gateway: session not authorized — run telethon_login.py")
            return

        self._worker = asyncio.create_task(self._worker_loop(), name="telethon-gateway")
        self._started = True
        logger.info("Telethon gateway started (single client, queued ops)")

    async def stop(self) -> None:
        if not self._started:
            return
        if self._worker and not self._worker.done():
            await self._queue.put(None)
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None
        if self._client:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.debug("Telethon gateway disconnect: %s", e)
        self._client = None
        self._started = False
        logger.info("Telethon gateway stopped")

    async def _worker_loop(self) -> None:
        assert self._client is not None
        while True:
            op = await self._queue.get()
            try:
                if op is None:
                    break
                try:
                    result = await op.fn(self._client)
                    if not op.future.done():
                        op.future.set_result(result)
                except Exception as e:
                    if not op.future.done():
                        op.future.set_exception(e)
            finally:
                self._queue.task_done()

    async def run(self, name: str, fn: ClientFn[T]) -> T:
        """Run ``fn(client)`` on the shared client (queued)."""
        if not Config.TELETHON_GATEWAY_ENABLED or not self._started or self._client is None:
            return await run_telethon_fallback(name, fn)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        await self._queue.put(_Op(name=name, fn=fn, future=fut))
        return await fut

    @property
    def running(self) -> bool:
        return self._started and self._client is not None


def get_gateway() -> TelethonGateway:
    global _gateway
    if _gateway is None:
        _gateway = TelethonGateway()
    return _gateway


async def start_telethon_gateway() -> None:
    await get_gateway().start()


async def stop_telethon_gateway() -> None:
    await get_gateway().stop()


async def run_telethon_fallback(name: str, fn: ClientFn[T]) -> T:
    """Isolated session clone when gateway is off or unavailable."""
    import os

    from telethon_isolated import isolated_telethon_client

    api_id = int(os.getenv("API_ID", "").strip())
    api_hash = os.getenv("API_HASH", "").strip()
    logger.debug("Telethon fallback for %s (isolated session)", name)
    async with isolated_telethon_client(api_id, api_hash, prefix="idxbot-fb-") as client:
        return await fn(client)


async def run_telethon(name: str, fn: ClientFn[T]) -> T:
    """Preferred entry: gateway queue, else isolated session."""
    gw = get_gateway()
    if gw.running:
        return await gw.run(name, fn)
    if Config.TELETHON_GATEWAY_ENABLED and telethon_configured():
        await gw.start()
        if gw.running:
            return await gw.run(name, fn)
    return await run_telethon_fallback(name, fn)
