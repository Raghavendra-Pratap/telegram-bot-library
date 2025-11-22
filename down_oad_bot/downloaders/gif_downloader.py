"""
GIF downloader for various platforms (Giphy, Tenor, etc.)
"""
import requests
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from .base_downloader import BaseDownloader

logger = logging.getLogger(__name__)


class GIFDownloader(BaseDownloader):
    """Downloader for GIFs from various platforms"""
    
    def download(
        self, 
        url: str, 
        quality: str = "best",
        audio_only: bool = False
    ) -> Optional[Path]:
        """Download GIF"""
        if audio_only:
            logger.warning("GIFs don't have audio")
            return None
        
        try:
            # For Giphy, try to get the direct GIF URL
            if 'giphy.com' in url or 'gph.is' in url:
                # Try to extract GIF ID and get direct URL
                gif_id = None
                if '/gifs/' in url:
                    parts = url.split('/gifs/')
                    if len(parts) > 1:
                        gif_id = parts[1].split('-')[-1].split('?')[0]
                
                if gif_id:
                    # Try direct GIF URL
                    direct_url = f"https://i.giphy.com/{gif_id}.gif"
                    response = requests.head(direct_url, allow_redirects=True)
                    if response.status_code == 200:
                        url = direct_url
            
            # Download the file
            logger.info(f"Downloading GIF from: {url}")
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Determine file extension
            content_type = response.headers.get('content-type', '')
            if 'gif' in content_type:
                ext = 'gif'
            elif 'mp4' in content_type:
                ext = 'mp4'  # Some platforms serve GIFs as MP4
            else:
                ext = 'gif'
            
            # Generate filename
            filename = f"gif_{hash(url) % 10000}.{ext}"
            output_path = self.download_dir / filename
            
            # Save file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"Downloaded: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Error downloading GIF: {str(e)}")
            return None
    
    def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """Get GIF information"""
        try:
            response = requests.head(url, allow_redirects=True, timeout=10)
            content_length = response.headers.get('content-length', 0)
            content_type = response.headers.get('content-type', '')
            
            return {
                'title': 'GIF',
                'duration': 0,
                'uploader': 'Unknown',
                'size': int(content_length) if content_length else 0,
                'url': url,
            }
        except Exception as e:
            logger.error(f"Error getting GIF info: {str(e)}")
            return None

