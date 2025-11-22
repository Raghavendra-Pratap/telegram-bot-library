"""
Instagram Reels downloader using instaloader and yt-dlp (fallback)
Note: Stories require authentication and are time-sensitive
"""
import instaloader
import yt_dlp
import time
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import requests
from .base_downloader import BaseDownloader
from config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD

logger = logging.getLogger(__name__)


class InstagramDownloader(BaseDownloader):
    """Downloader for Instagram Reels"""
    
    def __init__(self, download_dir: Path):
        super().__init__(download_dir)
        self.loader = None
        self._initialize_loader()
    
    def _initialize_loader(self):
        """Initialize instaloader with credentials if available"""
        try:
            self.loader = instaloader.Instaloader(
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                dirname_pattern=str(self.download_dir)
            )
            
            # Login if credentials provided
            if INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD:
                try:
                    self.loader.login(INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                    logger.info("Instagram login successful")
                except Exception as e:
                    logger.warning(f"Instagram login failed: {str(e)}")
                    logger.warning("Continuing without authentication (public content only)")
        except Exception as e:
            logger.error(f"Error initializing instaloader: {str(e)}")
            self.loader = None
    
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """
        Download Instagram Reel
        
        Note: Instagram doesn't support quality selection or audio extraction
        Uses instaloader first, falls back to yt-dlp if that fails
        """
        before_download = time.time()
        
        # Try instaloader first
        if self.loader:
            try:
                downloaded_file = self._download_with_instaloader(url, before_download, audio_only)
                if downloaded_file:
                    return downloaded_file
            except Exception as e:
                logger.warning(f"Instaloader failed: {str(e)}, trying yt-dlp fallback")
        
        # Fallback to yt-dlp
        try:
            return self._download_with_ytdlp(url, before_download, audio_only)
        except Exception as e:
            logger.error(f"yt-dlp also failed: {str(e)}")
            return None
    
    def _download_with_instaloader(
        self, 
        url: str, 
        before_download: float,
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download using instaloader"""
        # Extract shortcode from URL
        shortcode = None
        if '/reel/' in url:
            shortcode = url.split('/reel/')[-1].split('/')[0].split('?')[0]
        elif '/p/' in url:
            shortcode = url.split('/p/')[-1].split('/')[0].split('?')[0]
        
        if not shortcode:
            logger.error("Could not extract shortcode from URL")
            return None
        
        logger.info(f"Downloading Instagram Reel with instaloader: {shortcode}")
        
        # Download the post/reel
        post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
        
        # Download video
        self.loader.download_post(post, target=str(self.download_dir))
        
        # Wait a bit for file system to update
        time.sleep(2)
        
        # Find the downloaded file using timestamp-based detection
        # Instaloader saves files with timestamp pattern: YYYY-MM-DD_HH-MM-SS_UTC.mp4
        # Try to find by shortcode first, then by timestamp
        downloaded_file = None
        
        # First, try to find files with shortcode in name (if instaloader uses it)
        for file in self.download_dir.glob(f"*{shortcode}*.mp4"):
            if file.exists():
                stat = file.stat()
                file_time = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime
                if file_time >= before_download - 2:
                    downloaded_file = file
                    logger.info(f"Found file by shortcode: {downloaded_file}")
                    break
        
        # If not found, use timestamp-based detection
        if not downloaded_file:
            downloaded_file = self.find_downloaded_file(before_download, shortcode)
        
        if downloaded_file and downloaded_file.exists():
            logger.info(f"Downloaded with instaloader: {downloaded_file}")
            return downloaded_file
        else:
            logger.warning("File not found after instaloader download")
            return None
    
    def _download_with_ytdlp(
        self, 
        url: str, 
        before_download: float,
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download using yt-dlp as fallback"""
        logger.info(f"Downloading Instagram Reel with yt-dlp: {url}")
        
        # Store the actual filename from yt-dlp
        downloaded_filename = None
        
        def postprocessor_hook(d):
            """Hook to capture the final filename after processing"""
            nonlocal downloaded_filename
            if d['status'] == 'finished':
                downloaded_filename = d.get('filename')
                logger.info(f"Post-processed file: {downloaded_filename}")
        
        if audio_only:
            format_selector = "bestaudio/best"
            output_template = str(self.download_dir / "%(title)s.%(ext)s")
        else:
            format_selector = "best"
            output_template = str(self.download_dir / "%(title)s.mp4")
        
        opts = {
            'format': format_selector,
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'extractaudio': audio_only,
            'audioformat': 'mp3' if audio_only else None,
            'progress_hooks': [postprocessor_hook],
        }
        
        # Convert to MP4 for video files
        if not audio_only:
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
            output_template = str(self.download_dir / "%(title)s.mp4")
            opts['outtmpl'] = output_template
        
        # Remove None values
        opts = {k: v for k, v in opts.items() if v is not None}
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
        
        # Wait for file system
        time.sleep(0.5)
        
        # Method 1: Use the filename from postprocessor hook (most accurate)
        if downloaded_filename:
            downloaded_file = Path(downloaded_filename)
            if downloaded_file.exists():
                logger.info(f"Found file from postprocessor: {downloaded_file}")
                return downloaded_file
        
        # Method 2: Find downloaded file using timestamp
        downloaded_file = self.find_downloaded_file(before_download)
        
        if downloaded_file and downloaded_file.exists():
            logger.info(f"Downloaded with yt-dlp: {downloaded_file}")
            return downloaded_file
        else:
            logger.error("File not found after yt-dlp download")
            return None
    
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get video information"""
        # Try instaloader first
        if self.loader:
            try:
                # Extract shortcode
                shortcode = None
                if '/reel/' in url:
                    shortcode = url.split('/reel/')[-1].split('/')[0].split('?')[0]
                elif '/p/' in url:
                    shortcode = url.split('/p/')[-1].split('/')[0].split('?')[0]
                
                if shortcode:
                    post = instaloader.Post.from_shortcode(self.loader.context, shortcode)
                    
                    return {
                        'title': post.caption[:100] if post.caption else 'Instagram Reel',
                        'duration': 0,  # Instagram doesn't provide duration easily
                        'uploader': post.owner_username,
                        'view_count': post.video_view_count if post.is_video else 0,
                        'thumbnail': post.url,
                        'url': url,
                    }
            except Exception as e:
                logger.warning(f"Instaloader info fetch failed: {str(e)}, trying yt-dlp")
        
        # Fallback to yt-dlp
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'title': info.get('title', 'Instagram Reel')[:100],
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'view_count': info.get('view_count', 0),
                    'thumbnail': info.get('thumbnail', ''),
                    'url': url,
                }
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return None

