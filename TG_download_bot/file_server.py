"""
Simple HTTP file server for serving downloaded files
"""
import logging
import time
import secrets
from pathlib import Path
from typing import Dict, Optional
from aiohttp import web
from aiohttp.web import Response

from config import FILE_RETENTION_HOURS

logger = logging.getLogger(__name__)


class FileServer:
    """HTTP server for serving downloaded files with expiration"""
    
    def __init__(self):
        self.file_store: Dict[str, dict] = {}
        self.app = web.Application()
        self._base_url: Optional[str] = None  # Set in start() so links use actual port
        self.app.router.add_get('/download/{token}', self.download_handler)
        self.app.router.add_get('/health', self.health_handler)
        self.runner: Optional[web.AppRunner] = None
    
    def generate_download_link(self, file_path: Path, filename: str) -> tuple[str, str]:
        """
        Generate secure download link for file
        
        Returns:
            (token, full_url)
        """
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + (FILE_RETENTION_HOURS * 3600)
        
        self.file_store[token] = {
            'path': str(file_path.absolute()),
            'filename': filename,
            'expires_at': expires_at,
            'created_at': time.time()
        }
        
        base_url = self._base_url
        if base_url is None:
            from config import FILE_SERVER_BASE_URL
            base_url = FILE_SERVER_BASE_URL
        full_url = f"{base_url}/download/{token}"
        
        logger.info(f"Generated download link for {filename} (expires in {FILE_RETENTION_HOURS}h)")
        return token, full_url
    
    async def download_handler(self, request):
        """Handle download requests"""
        token = request.match_info.get('token')
        
        if not token or token not in self.file_store:
            return Response(
                text="Link not found or expired",
                status=404,
                content_type='text/plain'
            )
        
        file_info = self.file_store[token]
        
        # Check expiration
        if time.time() > file_info['expires_at']:
            del self.file_store[token]
            return Response(
                text="Link expired",
                status=410,
                content_type='text/plain'
            )
        
        # Check if file exists
        file_path = Path(file_info['path'])
        if not file_path.exists():
            del self.file_store[token]
            return Response(
                text="File not found",
                status=404,
                content_type='text/plain'
            )
        
        # Serve file
        try:
            file_data = file_path.read_bytes()
            filename = file_info['filename']
            
            return Response(
                body=file_data,
                headers={
                    'Content-Type': 'application/octet-stream',
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Length': str(len(file_data))
                }
            )
        except Exception as e:
            logger.error(f"Error serving file: {e}")
            return Response(
                text="Error serving file",
                status=500,
                content_type='text/plain'
            )
    
    async def health_handler(self, request):
        """Health check endpoint"""
        return Response(
            text="OK",
            content_type='text/plain'
        )
    
    def cleanup_expired(self):
        """Remove expired file entries"""
        current_time = time.time()
        expired_tokens = [
            token for token, info in self.file_store.items()
            if current_time > info['expires_at']
        ]
        for token in expired_tokens:
            del self.file_store[token]
            logger.debug(f"Removed expired token: {token}")
    
    async def start(self, host: str, port: int, base_url: Optional[str] = None):
        """Start the file server. base_url: URL for download links (e.g. http://localhost:PORT); if not set, uses config FILE_SERVER_BASE_URL."""
        if base_url is not None:
            self._base_url = base_url.rstrip('/')
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()
        logger.info(f"File server started on http://{host}:{port}")
    
    async def stop(self):
        """Stop the file server"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("File server stopped")
