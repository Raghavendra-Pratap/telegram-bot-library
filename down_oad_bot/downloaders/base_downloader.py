"""
Base downloader class for all platforms
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Dict, Any
import logging
import time

logger = logging.getLogger(__name__)


class BaseDownloader(ABC):
    """Base class for all video downloaders"""
    
    def __init__(self, download_dir: Path):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
    
    def find_downloaded_file(self, before_time: float, video_id: str = None) -> Optional[Path]:
        """
        Find the most recently downloaded video file
        
        Args:
            before_time: Timestamp before download started
            video_id: Optional video ID to search for
            
        Returns:
            Path to downloaded file or None
        """
        # Prioritize .mp4 files, then check other formats
        video_extensions = ['.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.opus', '.ogg']
        recent_files = []
        after_download = time.time()
        
        # First, try to find by video ID if provided (most accurate)
        if video_id:
            for file in self.download_dir.glob(f"*{video_id}*"):
                if file.is_file() and file.suffix in video_extensions and file.exists():
                    # Check if file was created/modified after download started
                    try:
                        stat = file.stat()
                        # Use creation time if available (macOS), else modification time
                        file_time = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime
                        if file_time >= before_time - 2:  # 2 second buffer
                            logger.info(f"Found file by video ID: {file}")
                            return file
                    except Exception:
                        # If we can't check time, still return it if ID matches
                        return file
        
        # Find files created/modified during/after download (strict time window)
        # Only consider files created AFTER download started (not just modified)
        # Use a very tight window to avoid picking up files from previous downloads
        time_window_start = before_time - 1  # 1 second buffer before download
        time_window_end = after_download + 10  # 10 seconds after download completes
        
        for ext in video_extensions:
            for file in self.download_dir.glob(f"*{ext}"):
                if file.is_file():
                    try:
                        stat = file.stat()
                        # Use creation time if available (macOS), else modification time
                        file_time = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime
                        
                        # Only consider files created/modified within the download window
                        # This ensures we only get files from THIS download, not previous ones
                        if time_window_start <= file_time <= time_window_end:
                            # Calculate how recent the file is (prefer files created closer to download start)
                            # But prioritize files created AFTER download started
                            if file_time >= before_time:
                                time_diff = file_time - before_time  # Positive = created after start
                            else:
                                time_diff = before_time - file_time + 1000  # Penalize files before start
                            recent_files.append((time_diff, file_time, file))
                    except Exception as e:
                        logger.warning(f"Error checking file {file}: {str(e)}")
                        continue
        
        if recent_files:
            # Sort by time difference from download start (closest first)
            # This ensures we get the file created during THIS download, not a previous one
            recent_files.sort(key=lambda x: x[0])  # Sort by time difference (closest to download start)
            return recent_files[0][2]  # Return the file path
        
        # Last resort: Get newest file created after download started
        all_files = []
        for file in self.download_dir.iterdir():
            if file.is_file() and file.suffix in video_extensions:
                try:
                    stat = file.stat()
                    file_time = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_mtime
                    # Only consider files created after download started
                    if file_time >= before_time - 2:
                        all_files.append((file_time, file))
                except Exception:
                    continue
        
        if all_files:
            all_files.sort(key=lambda x: x[0], reverse=True)
            return all_files[0][1]
        
        return None
    
    @abstractmethod
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """
        Download video from URL
        
        Args:
            url: Video URL
            quality: Video quality (1080p, 2160p, best, etc.)
            audio_only: If True, extract audio only (MP3)
            
        Returns:
            Path to downloaded file or None if failed
        """
        pass
    
    @abstractmethod
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get video information without downloading
        
        Args:
            url: Video URL
            
        Returns:
            Dict with video info (title, duration, quality options, etc.)
        """
        pass
    
    def get_output_path(self, filename: str) -> Path:
        """Generate output file path"""
        return self.download_dir / filename

