"""
Twitter/X video downloader using yt-dlp
"""
import yt_dlp
import time
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from .base_downloader import BaseDownloader
from config import QUALITY_FORMAT

logger = logging.getLogger(__name__)


class TwitterDownloader(BaseDownloader):
    """Downloader for Twitter/X videos"""
    
    def _get_ydl_opts(
        self, 
        output_path: Path, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Dict[str, Any]:
        """Get yt-dlp options"""
        format_selector = QUALITY_FORMAT.get(quality, QUALITY_FORMAT["best"])
        
        if audio_only:
            format_selector = "bestaudio/best"
        
        if audio_only:
            output_template = str(output_path / "%(title)s.%(ext)s")
        else:
            # Convert to MP4 format for video files
            output_template = str(output_path / "%(title)s.mp4")
        
        opts = {
            'format': format_selector,
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'extractaudio': audio_only,
            'audioformat': 'mp3' if audio_only else None,
        }
        
        # Convert to MP4 format for video files
        if not audio_only:
            opts['postprocessors'] = [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }]
        
        # Remove None values
        opts = {k: v for k, v in opts.items() if v is not None}
        
        return opts
    
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download Twitter/X video"""
        try:
            before_download = time.time()
            
            ydl_opts = self._get_ydl_opts(self.download_dir, quality, audio_only)
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get video info first
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'twitter_video')
                video_id = info.get('id', '')
                
                # Download
                logger.info(f"Downloading Twitter video: {title}")
                ydl.download([url])
            
            # Small delay to ensure file system has updated
            time.sleep(0.5)
            
            # Find the downloaded file
            downloaded_file = self.find_downloaded_file(before_download, video_id)
            
            if downloaded_file and downloaded_file.exists():
                logger.info(f"Downloaded: {downloaded_file}")
                return downloaded_file
            else:
                logger.error("Downloaded file not found")
                return None
                    
        except Exception as e:
            logger.error(f"Error downloading Twitter video: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get video information"""
        try:
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                return {
                    'title': info.get('title', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'uploader': info.get('uploader', 'Unknown'),
                    'thumbnail': info.get('thumbnail', ''),
                    'url': url,
                }
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return None

