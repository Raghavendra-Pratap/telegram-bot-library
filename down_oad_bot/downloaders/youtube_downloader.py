"""
YouTube and YouTube Shorts downloader using yt-dlp
"""
import traceback
import yt_dlp
from yt_dlp.utils import DownloadError
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, List
import logging
from .base_downloader import BaseDownloader
from config import QUALITY_FORMAT, YOUTUBE_COOKIES_PATH

logger = logging.getLogger(__name__)


class YouTubeDownloader(BaseDownloader):
    """Downloader for YouTube and YouTube Shorts"""
    
    def __init__(self, download_dir: Path):
        super().__init__(download_dir)
        self.cookies_path = YOUTUBE_COOKIES_PATH if YOUTUBE_COOKIES_PATH else None
    
    @staticmethod
    def _quality_to_selector(quality: str) -> str:
        """Convert a compact quality key (e.g. '1080p', '1080p60') to a yt-dlp format
        selector.  Falls back gracefully for unknown values."""
        if quality in QUALITY_FORMAT:
            return QUALITY_FORMAT[quality]
        # Raw selectors passed directly (legacy / fallback)
        if '+' in quality or quality.startswith('best') or quality.isdigit():
            return quality
        # Dynamic: Xp or Xp60 patterns not yet in QUALITY_FORMAT
        m = re.match(r'^(\d+)p(60)?$', quality)
        if m:
            h, hfr = int(m.group(1)), bool(m.group(2))
            fps_clause = '[fps>50]' if hfr else '[fps<=55]'
            return (
                f"bestvideo[height<={h}]{fps_clause}+bestaudio"
                f"/bestvideo[height<={h}]+bestaudio"
            )
        return QUALITY_FORMAT["best"]

    def _get_ydl_opts(
        self,
        output_path: Path,
        quality: str = "best",
        audio_only: bool = False,
    ) -> Dict[str, Any]:
        """Get yt-dlp options"""
        if audio_only:
            format_selector = "bestaudio/best"
            output_template = str(output_path / "%(title)s.%(ext)s")
        else:
            format_selector = self._quality_to_selector(quality)
            output_template = str(output_path / "%(title)s.%(ext)s")
        
        opts = {
            'format': format_selector,
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'extractaudio': audio_only,
            'audioformat': 'mp3' if audio_only else None,
            'embed_subs': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }
        
        # Convert to MP4 format for video files
        if not audio_only:
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            # Update output template to use .mp4 extension
            output_template = str(output_path / "%(title)s.mp4")
            opts['outtmpl'] = output_template
        
        # Add cookies if available (for private videos)
        if self.cookies_path and Path(self.cookies_path).exists():
            opts['cookiefile'] = self.cookies_path
            logger.info(f"Using cookies from {self.cookies_path}")
        
        # Remove None values
        opts = {k: v for k, v in opts.items() if v is not None}
        
        return opts
    
    def _do_download(
        self,
        url: str,
        quality: str,
        audio_only: bool,
        before_download: float,
        progress_hooks: list,
        postprocessor_hooks: list,
        get_final_path,
    ) -> Optional[Path]:
        """Perform one download attempt with given quality. Returns path or None."""
        ydl_opts = self._get_ydl_opts(self.download_dir, quality, audio_only)
        ydl_opts['progress_hooks'] = progress_hooks
        ydl_opts['postprocessor_hooks'] = postprocessor_hooks
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id', '')
            logger.info(f"Downloading YouTube video: {info.get('title', 'video')}")
            ydl.download([url])
        time.sleep(0.5)
        # Prefer the postprocessor-captured path; fall back to timestamp scan
        return get_final_path() or self.find_downloaded_file(before_download, video_id)

    def download(
        self,
        url: str,
        quality: str = "best",
        audio_only: bool = False,
        progress_callback=None,
    ) -> Optional[Path]:
        """Download YouTube video. Falls back to 'best' if the requested format is
        unavailable (YouTube SABR / 403 restrictions)."""
        progress_hooks, postprocessor_hooks, get_final_path = self.make_ydl_hooks(progress_callback)
        before_download = time.time()
        # yt-dlp does not emit progress during extract_info; ping UI early for parallel clarity
        if progress_callback:
            progress_callback("—", "metadata", "—")

        for attempt_quality in (quality, "best"):
            try:
                result = self._do_download(
                    url, attempt_quality, audio_only,
                    before_download, progress_hooks, postprocessor_hooks, get_final_path,
                )
                if result:
                    return result
                if attempt_quality == "best":
                    break
            except DownloadError as e:
                msg = str(e).lower()
                if ("requested format is not available" in msg or "format is not available" in msg) \
                        and attempt_quality != "best":
                    logger.warning(
                        f"Format {quality} unavailable, retrying with best available."
                    )
                    continue
                logger.error(f"YouTube download error: {e}")
                logger.error(traceback.format_exc())
                return None
            except Exception as e:
                logger.error(f"YouTube download error: {e}")
                logger.error(traceback.format_exc())
                return None

        logger.error("Downloaded file not found after all attempts")
        return None
    
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get video information including available formats"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            if self.cookies_path and Path(self.cookies_path).exists():
                ydl_opts['cookiefile'] = self.cookies_path
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Check if it's a playlist
                if info.get('_type') == 'playlist' or 'entries' in info:
                    entries = info.get('entries', [])
                    playlist_title = info.get('title', 'Playlist')
                    playlist_id = info.get('id', '')
                    
                    # Get first video info for preview
                    first_video = entries[0] if entries else None
                    
                    return {
                        'title': playlist_title,
                        'duration': 0,
                        'uploader': info.get('uploader', 'Unknown'),
                        'view_count': 0,
                        'thumbnail': first_video.get('thumbnail', '') if first_video else '',
                        'formats': [],
                        'available_formats': [],
                        'url': url,
                        'is_playlist': True,
                        'playlist_id': playlist_id,
                        'video_count': len(entries),
                        'entries': entries[:10] if entries else [],  # Limit to first 10 for preview
                    }
                
                # Parse available video formats with resolutions and sizes
                available_formats = self._parse_formats(info.get('formats', []))
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'formats': info.get('formats', []),
                    'available_formats': available_formats,  # Parsed formats with resolutions
                    'url': url,
                    'is_playlist': False,
                }
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return None
    
    def _sanitize_folder_name(self, name: str) -> str:
        """Sanitize folder name to be filesystem-safe"""
        # Remove or replace invalid characters
        # Invalid characters: < > : " / \ | ? *
        invalid_chars = r'[<>:"/\\|?*]'
        sanitized = re.sub(invalid_chars, '_', name)
        
        # Remove leading/trailing spaces and dots
        sanitized = sanitized.strip(' .')
        
        # Limit length (Windows has 255 char limit, but we'll use 100 for safety)
        if len(sanitized) > 100:
            sanitized = sanitized[:100]
        
        # If empty after sanitization, use default name
        if not sanitized:
            sanitized = "Playlist"
        
        return sanitized
    
    def download_playlist(
        self,
        url: str,
        quality: str = "best",
        audio_only: bool = False
    ) -> List[Path]:
        """Download entire YouTube playlist into a dedicated folder"""
        downloaded_files = []
        
        try:
            # First, get playlist info to get the title
            ydl_opts_info = {
                'quiet': True,
                'no_warnings': True,
            }
            if self.cookies_path and Path(self.cookies_path).exists():
                ydl_opts_info['cookiefile'] = self.cookies_path
            
            playlist_title = "Playlist"
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(url, download=False)
                playlist_title = info.get('title', 'Playlist')
                entries = info.get('entries', [])
            
            # Sanitize playlist title for folder name
            folder_name = self._sanitize_folder_name(playlist_title)
            
            # Create playlist folder
            playlist_folder = self.download_dir / folder_name
            playlist_folder.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"Created playlist folder: {playlist_folder}")
            logger.info(f"Downloading playlist '{playlist_title}' with {len(entries)} videos to {playlist_folder}")
            
            # Get yt-dlp options with playlist folder as output
            ydl_opts = self._get_ydl_opts(playlist_folder, quality, audio_only)
            
            # Track downloaded files via postprocessor hook (captures post-FFmpeg paths)
            downloaded_filenames: list[str] = []

            def _pp_hook(d: dict) -> None:
                if d.get("status") == "finished":
                    info = d.get("info_dict", {})
                    fp = info.get("filepath") or info.get("filename")
                    if fp:
                        downloaded_filenames.append(fp)
                        logger.info(f"Downloaded: {Path(fp).name}")

            def _prog_hook(d: dict) -> None:
                if d["status"] == "finished" and not any(
                    f == d.get("filename") for f in downloaded_filenames
                ):
                    fn = d.get("filename")
                    if fn:
                        downloaded_filenames.append(fn)

            ydl_opts['progress_hooks'] = [_prog_hook]
            ydl_opts['postprocessor_hooks'] = [_pp_hook]
            
            before_download = time.time()
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Download all videos
                ydl.download([url])
            
            # Wait for file system to update
            time.sleep(1)
            
            # Get all downloaded files from the playlist folder
            if downloaded_filenames:
                # Use filenames from postprocessor hook
                for filename in downloaded_filenames:
                    file_path = Path(filename)
                    if file_path.exists():
                        downloaded_files.append(file_path)
            else:
                # Fallback: find files in playlist folder
                video_extensions = ['.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.opus', '.ogg']
                for ext in video_extensions:
                    for file in playlist_folder.glob(f"*{ext}"):
                        if file.is_file():
                            stat = file.stat()
                            file_time = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime
                            if file_time >= before_download - 5:  # 5 second buffer
                                downloaded_files.append(file)
            
            # Remove duplicates
            downloaded_files = list(set(downloaded_files))
            
            logger.info(f"Downloaded {len(downloaded_files)} files from playlist to {playlist_folder}")
            return downloaded_files
            
        except Exception as e:
            logger.error(f"Error downloading playlist: {str(e)}")
            logger.error(traceback.format_exc())
            return downloaded_files
    
    def _parse_formats(self, formats: list) -> list:
        """Return all distinct (height, fps-tier) options with accurate total size.

        Key fixes vs. previous version:
        - Deduplicates by (height, is_hfr) so 1080p@30 and 1080p@60 appear separately.
        - Total size = best video stream size + best audio stream size.
          YouTube DASH separates video and audio; showing video-only size was
          consistently 15–30% lower than the file you'd actually receive.
        - format_id is a compact key ("1080p60") that maps through QUALITY_FORMAT
          in _get_ydl_opts, keeping callback data well under Telegram's 64-byte limit.
        """
        if not formats:
            return [{'format_id': 'best', 'resolution': 'Best', 'height': 9999,
                     'filesize': 0, 'fps': None}]

        # ── Best audio size (added to every video estimate) ──────────────────
        best_audio_size = max(
            (f.get('filesize') or f.get('filesize_approx') or 0
             for f in formats
             if f.get('vcodec', 'none') == 'none' and f.get('acodec', 'none') != 'none'),
            default=0,
        )

        # ── Collect video streams, group by (height, is_hfr) ─────────────────
        # is_hfr: fps > 50  (covers 60 fps, 50 fps YouTube streams)
        # Within each bucket keep the stream with the largest known size
        # (larger size = higher bitrate = better quality indicator).
        buckets: dict[tuple[int, bool], dict] = {}

        for fmt in formats:
            if fmt.get('vcodec', 'none') == 'none':
                continue
            height = fmt.get('height')
            if not height:
                continue
            fps = fmt.get('fps') or 30
            is_hfr = fps > 50
            key = (height, is_hfr)

            size = fmt.get('filesize') or fmt.get('filesize_approx') or 0
            existing = buckets.get(key)
            if existing is None or size > (existing.get('_video_size') or 0):
                buckets[key] = {**fmt, '_video_size': size, '_is_hfr': is_hfr}

        # ── Build result list ─────────────────────────────────────────────────
        video_formats = []
        for (height, is_hfr), fmt in buckets.items():
            video_size = fmt.get('_video_size') or 0
            total_size = (video_size + best_audio_size) if video_size > 0 else 0

            fps_val = fmt.get('fps') or 30
            fps_label = f"{round(fps_val)}fps" if is_hfr else ""
            resolution = f"{height}p{fps_label}" if fps_label else f"{height}p"

            # Compact key: "1080p60" or "1080p" — maps through _quality_to_selector
            format_id = f"{height}p60" if is_hfr else f"{height}p"

            video_formats.append({
                'format_id': format_id,
                'resolution': resolution,
                'height': height,
                'fps': round(fps_val) if is_hfr else None,
                'filesize': total_size,  # video + audio combined estimate
                'size_note': '~' if total_size == 0 else '',
            })

        # Sort: height desc, then hfr before non-hfr at the same height
        video_formats.sort(key=lambda x: (x['height'], bool(x['fps'])), reverse=True)

        # Prepend "Best" — no size shown since the actual stream depends on availability
        video_formats.insert(0, {
            'format_id': 'best',
            'resolution': 'Best',
            'height': 9999,
            'fps': None,
            'filesize': 0,
            'size_note': '',
        })

        return video_formats

