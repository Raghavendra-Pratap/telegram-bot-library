"""
Threads (Meta) video downloader using third-party API services
Note: yt-dlp doesn't support Threads, so we use API services
"""
import requests
import re
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from urllib.parse import urlparse, parse_qs, quote
from .base_downloader import BaseDownloader

logger = logging.getLogger(__name__)


class ThreadsDownloader(BaseDownloader):
    """Downloader for Threads videos"""
    
    def __init__(self, download_dir: Path):
        super().__init__(download_dir)
        self.session = requests.Session()
        # Use more realistic browser headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        # API endpoints that might work (we'll try multiple)
        self.api_endpoints = [
            'https://api.savethreads.io/api/convert',
            'https://threadsdownloader.com/api/convert',
        ]
    
    def _extract_post_id(self, url: str) -> Optional[str]:
        """Extract post ID from Threads URL"""
        # Pattern: threads.com/@username/post/POST_ID
        match = re.search(r'/post/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        
        # Pattern: threads.net/t/POST_ID
        match = re.search(r'/t/([a-zA-Z0-9_-]+)', url)
        if match:
            return match.group(1)
        
        return None
    
    def _try_api_service(self, url: str) -> Optional[str]:
        """Try to get video URL using third-party API services"""
        # Try different API endpoints that might work
        api_services = [
            {
                'url': 'https://api.savethreads.io/api/convert',
                'method': 'POST',
                'data': {'url': url}
            },
            {
                'url': f'https://threadsdownloader.com/api/convert?url={quote(url)}',
                'method': 'GET',
                'data': None
            },
        ]
        
        for service in api_services:
            try:
                logger.info(f"Trying API service: {service['url']}")
                if service['method'] == 'POST':
                    response = self.session.post(
                        service['url'],
                        json=service['data'],
                        headers={'Content-Type': 'application/json'},
                        timeout=30
                    )
                else:
                    response = self.session.get(service['url'], timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    # Look for video URL in response
                    video_url = self._find_video_in_json(data)
                    if video_url:
                        logger.info("Found video URL via API service")
                        return video_url
            except Exception as e:
                logger.debug(f"API service failed: {str(e)}")
                continue
        return None
    
    def _get_video_url_from_page(self, url: str) -> Optional[str]:
        """Extract video URL from Threads page using multiple methods"""
        # Method 1: Try API services first
        video_url = self._try_api_service(url)
        if video_url:
            return video_url
        
        # Method 2: Direct page scraping
        try:
            response = self.session.get(url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            content = response.text
            
            # Look for video URLs in the page content
            video_patterns = [
                r'"video_url":"([^"]+)"',
                r'"videoUrl":"([^"]+)"',
                r'"video_url_quality_0":"([^"]+)"',
                r'"playback_url":"([^"]+)"',
                r'"src":"(https://[^"]*\.mp4[^"]*)"',
                r'<video[^>]+src="([^"]+)"',
                r'src="(https://[^"]+\.mp4[^"]*)"',
                r'https://[^"]*\.scontent[^"]*\.mp4[^"]*',
                r'https://[^"]*cdninstagram[^"]*\.mp4[^"]*',
                r'https://[^"]*fbcdn[^"]*\.mp4[^"]*',
            ]
            
            for pattern in video_patterns:
                matches = re.findall(pattern, content)
                for match in matches:
                    video_url = match
                    # Clean up URL
                    video_url = video_url.replace('\\/', '/').replace('\\u002F', '/')
                    if video_url.startswith('http') and ('.mp4' in video_url or 'video' in video_url.lower()):
                        logger.info(f"Found video URL from page scraping")
                        return video_url
            
            # Try to find in JSON data
            json_pattern = r'<script[^>]*type="application/json"[^>]*>(.*?)</script>'
            json_matches = re.findall(json_pattern, content, re.DOTALL)
            for json_str in json_matches:
                try:
                    data = json.loads(json_str)
                    video_url = self._find_video_in_json(data)
                    if video_url:
                        return video_url
                except Exception as e:
                    logger.debug(f"Error parsing JSON: {str(e)}")
                    continue
            
            # Try to find in __NEXT_DATA__ script tag
            next_data_pattern = r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>'
            next_data_match = re.search(next_data_pattern, content, re.DOTALL)
            if next_data_match:
                try:
                    next_data = json.loads(next_data_match.group(1))
                    video_url = self._find_video_in_json(next_data)
                    if video_url:
                        return video_url
                except Exception as e:
                    logger.debug(f"Error parsing __NEXT_DATA__: {str(e)}")
            
            logger.warning("Could not find video URL in Threads page")
            return None
        except Exception as e:
            logger.error(f"Error fetching Threads page: {str(e)}")
            return None
    
    def _find_video_in_json(self, data: Any) -> Optional[str]:
        """Recursively find video URL in JSON data"""
        if isinstance(data, dict):
            for key, value in data.items():
                if 'video' in key.lower() and 'url' in key.lower() and isinstance(value, str) and value.startswith('http'):
                    return value
                result = self._find_video_in_json(value)
                if result:
                    return result
        elif isinstance(data, list):
            for item in data:
                result = self._find_video_in_json(item)
                if result:
                    return result
        return None
    
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download Threads video"""
        try:
            if audio_only:
                logger.warning("Audio extraction from Threads not yet implemented")
                return None
            
            before_download = time.time()
            post_id = self._extract_post_id(url)
            
            if not post_id:
                logger.error("Could not extract post ID from URL")
                return None
            
            logger.info(f"Downloading Threads video: {post_id}")
            
            # Get video URL from page
            video_url = self._get_video_url_from_page(url)
            
            if not video_url:
                logger.error("Could not extract video URL from Threads page")
                return None
            
            logger.info(f"Found video URL: {video_url[:100]}...")
            
            # Download video
            response = self.session.get(video_url, stream=True, timeout=60)
            response.raise_for_status()
            
            # Generate filename
            filename = f"threads_{post_id}.mp4"
            output_path = self.download_dir / filename
            
            # Download file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            if output_path.exists() and output_path.stat().st_size > 0:
                logger.info(f"Downloaded: {output_path}")
                return output_path
            else:
                logger.error("Downloaded file is empty or doesn't exist")
                return None
                    
        except Exception as e:
            logger.error(f"Error downloading Threads video: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get video information"""
        try:
            post_id = self._extract_post_id(url)
            if not post_id:
                return None
            
            # Try to get basic info from page
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Extract title/username from page
            title = "Threads Video"
            uploader = "Unknown"
            
            # Try to extract username from URL
            username_match = re.search(r'@([\w.]+)', url)
            if username_match:
                uploader = username_match.group(1)
            
            # Try to extract title from page meta tags
            title_match = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', response.text)
            if title_match:
                title = title_match.group(1)
            
            # Check if video exists - try to get video URL
            # Note: Threads has strong anti-scraping, so this may fail
            video_url = self._get_video_url_from_page(url)
            if not video_url:
                logger.warning("No video found in Threads post - Threads may require authentication or have anti-scraping protection")
                # Return basic info anyway so user can try downloading
                return {
                    'title': title[:100],
                    'duration': 0,
                    'uploader': uploader,
                    'view_count': 0,
                    'thumbnail': '',
                    'url': url,
                }
            
            return {
                'title': title[:100],
                'duration': 0,  # Threads doesn't provide duration easily
                'uploader': uploader,
                'view_count': 0,  # Threads doesn't provide view count easily
                'thumbnail': '',  # Could extract from page if needed
                'url': url,
            }
        except Exception as e:
            logger.error(f"Error getting video info: {str(e)}")
            return None

