"""
URL detection and platform identification
"""
import re
from typing import Optional, Tuple
from enum import Enum


class Platform(Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    REDDIT = "reddit"
    TIKTOK = "tiktok"
    THREADS = "threads"
    GIF = "gif"
    UNKNOWN = "unknown"


class URLDetector:
    """Detects the platform from a URL"""
    
    # URL patterns for different platforms
    PATTERNS = {
        Platform.YOUTUBE: [
            # Playlist URLs (check first to avoid matching single video in playlist)
            r'(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([a-zA-Z0-9_-]+)',
            r'(?:https?://)?(?:www\.)?youtube\.com/watch\?.*list=([a-zA-Z0-9_-]+)',
            # Single video URLs
            r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})',
            r'(?:https?://)?(?:www\.)?youtube\.com/.*[?&]v=([a-zA-Z0-9_-]{11})',
        ],
        Platform.INSTAGRAM: [
            r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|stories)/([a-zA-Z0-9_-]+)',
            r'(?:https?://)?(?:www\.)?instagram\.com/([a-zA-Z0-9_.]+)/?$',
        ],
        Platform.TWITTER: [
            r'(?:https?://)?(?:www\.|mobile\.)?(?:twitter\.com|x\.com)/(?:#!)?(\w+)/status/(\d+)',
        ],
        Platform.REDDIT: [
            r'(?:https?://)?(?:www\.)?reddit\.com/r/\w+/comments/[a-zA-Z0-9_]+',
            r'(?:https?://)?(?:www\.)?redd\.it/([a-zA-Z0-9_]+)',
        ],
        # TIKTOK: disabled (not supported in our region; plan support later)
        Platform.THREADS: [
            r'(?:https?://)?(?:www\.)?threads\.(?:net|com)/@[\w.]+/post/([a-zA-Z0-9_-]+)',
            r'(?:https?://)?(?:www\.)?threads\.(?:net|com)/t/([a-zA-Z0-9_-]+)',
            r'(?:https?://)?threads\.(?:net|com)/@[\w.]+/post/([a-zA-Z0-9_-]+)',
        ],
        Platform.GIF: [
            r'(?:https?://)?(?:www\.)?(?:giphy\.com|gph\.is|tenor\.com|media\.giphy\.com)',
        ],
    }
    
    @staticmethod
    def is_playlist_url(url: str) -> bool:
        """Check if URL is a YouTube playlist"""
        playlist_patterns = [
            r'youtube\.com/playlist\?list=',
            r'youtube\.com/watch\?.*list=',
        ]
        for pattern in playlist_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def detect_platform(url: str) -> Tuple[Platform, Optional[str]]:
        """
        Detect platform from URL
        
        Returns:
            Tuple of (Platform, extracted_id or None)
        """
        url = url.strip()
        
        # Check each platform
        for platform, patterns in URLDetector.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    # Extract ID if available
                    extracted_id = match.group(1) if match.groups() else None
                    return platform, extracted_id
        
        return Platform.UNKNOWN, None
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if URL is valid"""
        url_pattern = re.compile(
            r'^https?://'  # http:// or https://
            r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
            r'localhost|'  # localhost...
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
            r'(?::\d+)?'  # optional port
            r'(?:/?|[/?]\S+)$', re.IGNORECASE)
        return url_pattern.match(url) is not None

