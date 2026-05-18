"""
Async job queues — heavy work off the update handler with transient retries.

Lanes:
  INTERACTIVE — TMDB pick / per-user lookups (parallel workers)
  BACKGROUND  — publish, verify, discover (exclusive heavy jobs, full retries)
  INGEST      — channel file indexing (rate-limited, full retries on TMDB blips)

Permanent errors (invalid buttons, bad HTML) fail immediately.
Transient errors (flood, timeout, connection reset) retry with backoff.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Awaitable, Callable

from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from config import Config

logger = logging.getLogger(__name__)

_QUEUE_KEY = "job_queue"


class Lane(IntEnum):
    INTERACTIVE = 0
    BACKGROUND = 10
    INGEST = 20


@dataclass
class Job:
    name: str
    coro_factory: Callable[[], Awaitable[Any]]
    lane: Lane = Lane.BACKGROUND
    exclusive: bool = False
    max_retries: int = 0
    seq: int = 0


def is_transient_error(exc: BaseException) -> bool:
    """Whether a failed job step should be retried."""
    if isinstance(exc, (RetryAfter, TimedOut, NetworkError)):
        return True
    if isinstance(exc, BadRequest):
        from telegram_flood import (
            _is_flood_bad_request,
            _is_permanent_bad_request,
            is_unchanged_message_error,
        )

        if _is_permanent_bad_request(exc) or is_unchanged_message_error(exc):
            return False
        if _is_flood_bad_request(exc):
            return True
        return False
    msg = str(exc).lower()
    transient_markers = (
        "connection reset",
        "timed out",
        "temporary failure",
        "errno 54",
        "errno 60",
        "broken pipe",
        "name or service not known",
    )
    return any(m in msg for m in transient_markers)


def _backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    if retry_after is not None:
        base = min(90.0, retry_after + 1.5)
    else:
        base = min(60.0, 2.0 ** attempt + 1.0)
    return base + random.uniform(0.2, 0.9)


class JobQueueService:
    def __init__(self) -> None:
        self._queues: dict[Lane, asyncio.Queue[Job]] = {
            Lane.INTERACTIVE: asyncio.Queue(),
            Lane.BACKGROUND: asyncio.Queue(),
            Lane.INGEST: asyncio.Queue(),
        }
        self._seq = 0
        self._exclusive_lock = asyncio.Lock()
        self._running_exclusive: str | None = None
        self._workers: list[asyncio.Task] = []
        self._application = None

    def attach(self, application) -> None:
        self._application = application
        application.bot_data[_QUEUE_KEY] = self

    @staticmethod
    def get(application) -> JobQueueService | None:
        return application.bot_data.get(_QUEUE_KEY)

    def exclusive_label(self) -> str | None:
        return self._running_exclusive

    def pending_count(self) -> int:
        return sum(q.qsize() for q in self._queues.values())

    async def start(self, application) -> None:
        self.attach(application)
        import bot_busy

        bot_busy.release(application)
        n_i = Config.JOB_QUEUE_INTERACTIVE_WORKERS
        n_b = Config.JOB_QUEUE_BACKGROUND_WORKERS
        n_g = Config.JOB_QUEUE_INGEST_WORKERS
        for _ in range(n_i):
            self._workers.append(asyncio.create_task(self._worker_loop(Lane.INTERACTIVE)))
        for _ in range(n_b):
            self._workers.append(asyncio.create_task(self._worker_loop(Lane.BACKGROUND)))
        for _ in range(n_g):
            self._workers.append(asyncio.create_task(self._worker_loop(Lane.INGEST)))
        logger.info(
            "Job queue started (interactive=%s background=%s ingest=%s)",
            n_i,
            n_b,
            n_g,
        )

    async def enqueue(self, job: Job) -> int:
        """Return 1-based position in that lane's queue (including running)."""
        self._seq += 1
        job.seq = self._seq
        q = self._queues[job.lane]
        await q.put(job)
        return q.qsize()

    async def _worker_loop(self, lane: Lane) -> None:
        q = self._queues[lane]
        while True:
            job = await q.get()
            try:
                await self._run_job(job)
            except Exception:
                logger.exception("Job crashed in worker: %s", job.name)
            finally:
                q.task_done()

    async def _run_job(self, job: Job) -> None:
        if job.exclusive:
            async with self._exclusive_lock:
                self._running_exclusive = job.name
                if self._application:
                    self._application.bot_data["heavy_task"] = job.name
                try:
                    await self._run_with_retry(job)
                finally:
                    self._running_exclusive = None
                    if self._application:
                        self._application.bot_data.pop("heavy_task", None)
        else:
            await self._run_with_retry(job)

    async def _run_with_retry(self, job: Job) -> None:
        max_retries = job.max_retries or Config.JOB_MAX_RETRIES
        last_exc: BaseException | None = None
        for attempt in range(max_retries):
            try:
                await job.coro_factory()
                if attempt > 0:
                    logger.info("Job %s succeeded after %s retries", job.name, attempt)
                return
            except RetryAfter as e:
                last_exc = e
                if attempt >= max_retries - 1:
                    break
                wait = _backoff_seconds(attempt, float(e.retry_after))
                logger.warning(
                    "Job %s RetryAfter, sleep %.1fs (%s/%s)",
                    job.name,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait)
            except Exception as e:
                last_exc = e
                if not is_transient_error(e) or attempt >= max_retries - 1:
                    logger.error("Job %s failed permanently: %s", job.name, e)
                    raise
                wait = _backoff_seconds(attempt)
                logger.warning(
                    "Job %s transient %s, sleep %.1fs (%s/%s)",
                    job.name,
                    type(e).__name__,
                    wait,
                    attempt + 1,
                    max_retries,
                )
                await asyncio.sleep(wait)
        if last_exc is not None:
            raise last_exc


async def start_job_queue(application) -> None:
    service = JobQueueService()
    await service.start(application)


def get_job_queue(application) -> JobQueueService | None:
    return JobQueueService.get(application)


async def enqueue_job(
    application,
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    lane: Lane = Lane.BACKGROUND,
    exclusive: bool = False,
    max_retries: int | None = None,
) -> int:
    service = get_job_queue(application)
    if not service:
        logger.warning("Job queue missing — running %s inline", name)
        await coro_factory()
        return 0
    job = Job(
        name=name,
        coro_factory=coro_factory,
        lane=lane,
        exclusive=exclusive,
        max_retries=max_retries or 0,
    )
    return await service.enqueue(job)


async def enqueue_background(
    application,
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    exclusive: bool = True,
    max_retries: int | None = None,
) -> int:
    return await enqueue_job(
        application,
        name,
        coro_factory,
        lane=Lane.BACKGROUND,
        exclusive=exclusive,
        max_retries=max_retries,
    )


async def enqueue_interactive(
    application,
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    max_retries: int | None = None,
) -> int:
    return await enqueue_job(
        application,
        name,
        coro_factory,
        lane=Lane.INTERACTIVE,
        exclusive=False,
        max_retries=max_retries,
    )


async def enqueue_ingest(
    application,
    name: str,
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    max_retries: int | None = None,
) -> int:
    return await enqueue_job(
        application,
        name,
        coro_factory,
        lane=Lane.INGEST,
        exclusive=False,
        max_retries=max_retries,
    )
