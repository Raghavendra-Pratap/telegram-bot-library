"""
Async queue manager for download and upload jobs.
Workers process jobs in background; handlers return immediately after enqueue.
"""
import asyncio
import logging
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from config import MAX_BOT_UPLOAD_BYTES, MAX_BOT_UPLOAD_MB

logger = logging.getLogger(__name__)


@dataclass
class DownloadJob:
    """Single-file download job (video or audio)."""
    url: str
    downloader: Any
    quality: str
    audio_only: bool
    format_type: str            # 'video' or 'audio'
    platform_str: str
    url_hash: str
    chat_id: int
    status_message_id: int
    on_complete: Callable       # async (file_path: Path, size_text: str) -> None
    on_error: Callable          # async (error_msg: str) -> None
    on_begin: Optional[Callable[[], Awaitable[None]]] = None
    progress_cb: Optional[Callable] = None  # sync (percent, speed, eta) -> None


@dataclass
class PlaylistDownloadJob:
    """YouTube playlist download job."""
    url: str
    downloader: Any
    quality: str
    url_hash: str
    chat_id: int
    status_message_id: int
    on_complete: Callable       # async (files: list[Path], size_text: str) -> None
    on_error: Callable          # async (error_msg: str) -> None
    on_begin: Optional[Callable[[], Awaitable[None]]] = None


@dataclass
class UploadJob:
    """Single-file upload job."""
    file_path: Path
    format_type: str            # 'video' or 'audio'
    chat_id: int
    reply_to_message_id: Optional[int]
    size_text: str
    bot: Any
    on_done: Callable           # async (success: bool, msg: str) -> None


@dataclass
class AnalyzeUrlJob:
    """Renders URL → format keyboard; run in analyzer pool for fast user ack."""
    run: Callable[[], Awaitable[None]]


@dataclass
class PlaylistUploadJob:
    """Playlist upload batch; one slot in the upload queue until all files finish."""
    run: Callable[[], Awaitable[None]]


UploadQueueItem = Union[UploadJob, PlaylistUploadJob]


class QueueManager:
    """
    Manages separate asyncio queues and worker pools for downloads and uploads.

    Workers start via `await queue_manager.start()` (call from PTB post_init).
    Each handler enqueues a job and returns immediately — users get instant feedback.
    """

    def __init__(
        self,
        download_workers: int = 3,
        upload_workers: int = 2,
        analyze_workers: int = 3,
    ):
        self._download_workers = download_workers
        self._upload_workers = upload_workers
        self._analyze_workers = analyze_workers

        self._download_queue: asyncio.Queue = asyncio.Queue()
        self._upload_queue: asyncio.Queue[UploadQueueItem] = asyncio.Queue()
        self._analyze_queue: asyncio.Queue[AnalyzeUrlJob] = asyncio.Queue()
        self._worker_tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start all worker tasks. Must be called from an async context (e.g. post_init)."""
        for i in range(self._download_workers):
            t = asyncio.create_task(
                self._download_worker(i), name=f"dl-worker-{i}"
            )
            self._worker_tasks.append(t)
        for i in range(self._upload_workers):
            t = asyncio.create_task(
                self._upload_worker(i), name=f"ul-worker-{i}"
            )
            self._worker_tasks.append(t)
        for i in range(self._analyze_workers):
            t = asyncio.create_task(
                self._analyze_worker(i), name=f"analyze-worker-{i}"
            )
            self._worker_tasks.append(t)
        logger.info(
            f"QueueManager started: {self._analyze_workers} analyze + "
            f"{self._download_workers} download + {self._upload_workers} upload workers"
        )

    async def stop(self) -> None:
        """Cancel all workers gracefully."""
        for t in self._worker_tasks:
            t.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        logger.info("QueueManager stopped")

    @property
    def download_pending(self) -> int:
        return self._download_queue.qsize()

    @property
    def upload_pending(self) -> int:
        return self._upload_queue.qsize()

    @property
    def analyze_pending(self) -> int:
        return self._analyze_queue.qsize()

    async def enqueue_analyze(self, job: AnalyzeUrlJob) -> int:
        await self._analyze_queue.put(job)
        return self._analyze_queue.qsize()

    async def enqueue_download(self, job) -> int:
        """Enqueue a DownloadJob or PlaylistDownloadJob. Returns queue depth."""
        await self._download_queue.put(job)
        return self._download_queue.qsize()

    async def enqueue_upload(self, job: UploadQueueItem) -> int:
        """Enqueue a single-file or playlist upload job. Returns queue depth."""
        await self._upload_queue.put(job)
        return self._upload_queue.qsize()

    # ── Workers ───────────────────────────────────────────────────────────────

    async def _analyze_worker(self, worker_id: int) -> None:
        logger.info(f"Analyze worker {worker_id} ready")
        while True:
            job: AnalyzeUrlJob = await self._analyze_queue.get()
            try:
                await job.run()
            except asyncio.CancelledError:
                self._analyze_queue.task_done()
                break
            except Exception as e:
                logger.error(f"Analyze worker {worker_id}: {e}\n{traceback.format_exc()}")
            finally:
                self._analyze_queue.task_done()

    async def _download_worker(self, worker_id: int) -> None:
        logger.info(f"Download worker {worker_id} ready")
        while True:
            job = await self._download_queue.get()
            url_hint = getattr(job, "url", "")[:70]
            logger.info(f"DL worker {worker_id} picked job url={url_hint!r}")
            try:
                if isinstance(job, PlaylistDownloadJob):
                    await self._run_playlist_download(job)
                else:
                    await self._run_download(job)
            except asyncio.CancelledError:
                self._download_queue.task_done()
                break
            except Exception as e:
                logger.error(f"DL worker {worker_id}: {e}\n{traceback.format_exc()}")
                try:
                    await job.on_error(str(e)[:300])
                except Exception:
                    pass
            finally:
                self._download_queue.task_done()

    async def _upload_worker(self, worker_id: int) -> None:
        logger.info(f"Upload worker {worker_id} ready")
        while True:
            job: UploadQueueItem = await self._upload_queue.get()
            try:
                if isinstance(job, PlaylistUploadJob):
                    await job.run()
                else:
                    await self._run_upload(job)
            except asyncio.CancelledError:
                self._upload_queue.task_done()
                break
            except Exception as e:
                logger.error(f"UL worker {worker_id}: {e}")
                if isinstance(job, UploadJob):
                    try:
                        await job.on_done(False, str(e)[:200])
                    except Exception:
                        pass
            finally:
                self._upload_queue.task_done()

    # ── Job execution ─────────────────────────────────────────────────────────

    async def _run_download(self, job: DownloadJob) -> None:
        loop = asyncio.get_running_loop()

        def _proxy_progress(percent: str, speed: str, eta: str) -> None:
            if job.progress_cb:
                job.progress_cb(percent, speed, eta)

        if job.on_begin:
            try:
                await job.on_begin()
            except Exception:
                pass

        try:
            file_path: Optional[Path] = await asyncio.to_thread(
                job.downloader.download,
                job.url,
                job.quality,
                job.audio_only,
                _proxy_progress,
            )

            if not file_path or not file_path.exists():
                await job.on_error("Download failed — file not found after download.")
                return

            size = file_path.stat().st_size
            size_text = (
                f"{size / (1024 ** 2):.2f} MB"
                if size < 1024 ** 3
                else f"{size / (1024 ** 3):.2f} GB"
            )
            await job.on_complete(file_path, size_text)

        except Exception as e:
            logger.error(f"Download error for {job.url}: {e}\n{traceback.format_exc()}")
            await job.on_error(str(e)[:300])

    async def _run_playlist_download(self, job: PlaylistDownloadJob) -> None:
        if job.on_begin:
            try:
                await job.on_begin()
            except Exception:
                pass

        try:
            files: list[Path] = await asyncio.to_thread(
                job.downloader.download_playlist,
                job.url,
                job.quality,
                False,  # audio_only always False for playlist
            )

            if not files:
                await job.on_error("Playlist download failed — no files were downloaded.")
                return

            total_size = sum(f.stat().st_size for f in files if f.exists())
            size_text = (
                f"{total_size / (1024 ** 2):.1f} MB"
                if total_size < 1024 ** 3
                else f"{total_size / (1024 ** 3):.2f} GB"
            )
            await job.on_complete(files, size_text)

        except Exception as e:
            logger.error(f"Playlist download error: {e}\n{traceback.format_exc()}")
            await job.on_error(str(e)[:300])

    async def _run_upload(self, job: UploadJob) -> None:
        MAX_RETRIES = 3
        _too_large_hint = (
            f"Bot API limit is ~{MAX_BOT_UPLOAD_MB} MB per file (Premium does not change this). "
            f"File kept locally — try lower quality or a local Bot API server."
        )

        if not job.file_path.exists():
            await job.on_done(False, "File not found.")
            return

        file_size = job.file_path.stat().st_size
        if file_size > MAX_BOT_UPLOAD_BYTES:
            mb = file_size / (1024 ** 2)
            await job.on_done(
                False,
                f"File is {mb:.1f} MB — {_too_large_hint}",
            )
            return

        send_kwargs: dict = {
            "chat_id": job.chat_id,
            "caption": f"✅ {job.file_path.name}\n📦 {job.size_text}",
            "connect_timeout": 30,
            "read_timeout": 600,
            "write_timeout": 600,
            "pool_timeout": 30,
        }
        if job.reply_to_message_id:
            send_kwargs["reply_to_message_id"] = job.reply_to_message_id

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with open(job.file_path, "rb") as fh:
                    if job.format_type == "audio":
                        await asyncio.wait_for(
                            job.bot.send_audio(audio=fh, **send_kwargs),
                            timeout=700,
                        )
                    else:
                        await asyncio.wait_for(
                            job.bot.send_video(
                                video=fh,
                                supports_streaming=True,
                                **send_kwargs,
                            ),
                            timeout=700,
                        )
                await job.on_done(True, "")
                return  # success

            except asyncio.TimeoutError:
                logger.warning(
                    f"Upload timeout attempt {attempt}/{MAX_RETRIES}: {job.file_path.name}"
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(5 * attempt)
                else:
                    await job.on_done(
                        False, f"Upload timed out after {MAX_RETRIES} attempts."
                    )
                    return

            except Exception as exc:
                err = str(exc)
                logger.error(f"Upload error attempt {attempt}/{MAX_RETRIES}: {err}")
                el = err.lower()
                if "entity too large" in el or "request entity too large" in el:
                    await job.on_done(False, f"Request too large for cloud Bot API. {_too_large_hint}")
                    return
                if attempt < MAX_RETRIES and any(
                    kw in el
                    for kw in ("read error", "connection", "network", "timeout")
                ):
                    await asyncio.sleep(5 * attempt)
                    continue
                await job.on_done(False, err[:200])
                return
