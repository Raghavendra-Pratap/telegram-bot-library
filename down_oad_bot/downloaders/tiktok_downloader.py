"""
TikTok video downloader using yt-dlp
"""
import traceback
import yt_dlp
import time
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from .base_downloader import BaseDownloader
from config import QUALITY_FORMAT

logger = logging.getLogger(__name__)


class TikTokDownloader(BaseDownloader):
    """Downloader for TikTok videos"""

    def _get_ydl_opts(
        self,
        output_path: Path,
        quality: str = "best",
        audio_only: bool = False,
    ) -> Dict[str, Any]:
        format_selector = "bestaudio/best" if audio_only else QUALITY_FORMAT.get(quality, QUALITY_FORMAT["best"])
        output_template = str(output_path / ("%(title)s.%(ext)s" if audio_only else "%(title)s.mp4"))

        opts: Dict[str, Any] = {
            'format': format_selector,
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'extractaudio': audio_only,
            'audioformat': 'mp3' if audio_only else None,
            # TikTok sometimes returns watermarked streams; prefer non-watermarked
            'extractor_args': {'tiktok': {'api_hostname': 'api22-normal-c-alisg.tiktokv.com'}},
        }
        if not audio_only:
            opts['postprocessors'] = [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}]

        return {k: v for k, v in opts.items() if v is not None}

    def download(
        self,
        url: str,
        quality: str = "best",
        audio_only: bool = False,
        progress_callback=None,
    ) -> Optional[Path]:
        """Download TikTok video."""
        try:
            before_download = time.time()
            progress_hooks, postprocessor_hooks, get_final_path = self.make_ydl_hooks(progress_callback)
            if progress_callback:
                progress_callback("—", "metadata", "—")

            ydl_opts = self._get_ydl_opts(self.download_dir, quality, audio_only)
            ydl_opts['progress_hooks'] = progress_hooks
            ydl_opts['postprocessor_hooks'] = postprocessor_hooks

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_id = info.get('id', '')
                logger.info(f"Downloading TikTok video: {info.get('title', url)}")
                ydl.download([url])

            time.sleep(0.5)
            result = get_final_path() or self.find_downloaded_file(before_download, video_id)
            if result:
                logger.info(f"Downloaded: {result}")
                return result
            logger.error("Downloaded TikTok file not found")
            return None

        except Exception as e:
            logger.error(f"Error downloading TikTok video: {e}")
            logger.error(traceback.format_exc())
            return None

    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return {
                    'title': info.get('title', 'TikTok Video'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader') or info.get('creator', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'url': url,
                }
        except Exception as e:
            logger.error(f"Error getting TikTok video info: {e}")
            return None
