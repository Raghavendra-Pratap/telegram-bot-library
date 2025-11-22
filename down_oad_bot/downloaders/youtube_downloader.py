"""
YouTube and YouTube Shorts downloader using yt-dlp
"""
import yt_dlp
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
    
    def _get_ydl_opts(
        self, 
        output_path: Path, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Dict[str, Any]:
        """Get yt-dlp options"""
        if audio_only:
            format_selector = "bestaudio/best"
            output_template = str(output_path / "%(title)s.%(ext)s")
        else:
            # If quality is a format ID (like "399+251" or "best"), use it directly
            # Otherwise use quality format mapping
            if '+' in quality or quality.isdigit() or quality.startswith('best'):
                format_selector = quality
            else:
                format_selector = QUALITY_FORMAT.get(quality, QUALITY_FORMAT["best"])
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
    
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download YouTube video"""
        try:
            # Store the actual filename from yt-dlp
            downloaded_filename = None
            
            def postprocessor_hook(d):
                """Hook to capture the final filename after processing"""
                nonlocal downloaded_filename
                if d['status'] == 'finished':
                    downloaded_filename = d.get('filename')
                    logger.info(f"Post-processed file: {downloaded_filename}")
            
            # Get current time to find recently created files
            before_download = time.time()
            
            ydl_opts = self._get_ydl_opts(self.download_dir, quality, audio_only)
            ydl_opts['progress_hooks'] = [postprocessor_hook]
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Get video info first
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'video')
                video_id = info.get('id', '')
                
                # Download
                logger.info(f"Downloading YouTube video: {title}")
                ydl.download([url])
            
            # Small delay to ensure file system has updated
            time.sleep(0.5)
            
            # Try to find the downloaded file using multiple methods
            downloaded_file = None
            video_extensions = ['.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.opus', '.ogg']
            
            # Method 1: Use the filename from postprocessor hook
            if downloaded_filename:
                downloaded_file = Path(downloaded_filename)
                if downloaded_file.exists():
                    logger.info(f"Found file from postprocessor: {downloaded_file}")
                    return downloaded_file
            
            # Method 2: Use base class helper to find downloaded file
            downloaded_file = self.find_downloaded_file(before_download, video_id)
            
            if downloaded_file:
                logger.info(f"Found downloaded file: {downloaded_file}")
                return downloaded_file
            
            logger.error("Downloaded file not found after all methods")
            logger.error(f"Download directory contents: {list(self.download_dir.glob('*'))}")
            return None
                    
        except Exception as e:
            logger.error(f"Error downloading YouTube video: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
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
            
            # Track downloaded files
            downloaded_filenames = []
            
            def postprocessor_hook(d):
                """Hook to capture downloaded filenames"""
                if d['status'] == 'finished':
                    filename = d.get('filename')
                    if filename:
                        downloaded_filenames.append(filename)
                        logger.info(f"Downloaded: {Path(filename).name}")
            
            ydl_opts['progress_hooks'] = [postprocessor_hook]
            
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
            import traceback
            logger.error(traceback.format_exc())
            return downloaded_files
    
    def _parse_formats(self, formats: list) -> list:
        """Parse yt-dlp formats to get available resolutions with file sizes"""
        video_formats = []
        seen_resolutions = set()
        
        for fmt in formats:
            # Only process video formats (not audio-only)
            if fmt.get('vcodec') != 'none' and fmt.get('acodec') != 'none':
                height = fmt.get('height')
                filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
                
                if height:
                    resolution = f"{height}p"
                    # Avoid duplicates, prefer formats with known file size
                    if resolution not in seen_resolutions or filesize > 0:
                        seen_resolutions.add(resolution)
                        
                        # Calculate total size (video + audio if separate)
                        total_size = filesize
                        
                        video_formats.append({
                            'format_id': fmt.get('format_id', ''),
                            'resolution': resolution,
                            'height': height,
                            'filesize': total_size,
                            'ext': fmt.get('ext', 'mp4'),
                            'fps': fmt.get('fps'),
                        })
        
        # Sort by resolution (height) descending
        video_formats.sort(key=lambda x: x['height'], reverse=True)
        
        # Also add "best" option
        best_size = sum(f.get('filesize', 0) for f in formats if f.get('filesize')) or 0
        video_formats.insert(0, {
            'format_id': 'best',
            'resolution': 'Best',
            'height': 9999,
            'filesize': best_size,
            'ext': 'mp4',
            'fps': None,
        })
        
        return video_formats

