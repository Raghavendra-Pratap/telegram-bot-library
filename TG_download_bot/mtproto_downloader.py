"""
MTProto Downloader using Pyrogram with Premium Account
Downloads files at premium speeds using MTProto protocol
"""
import logging
import asyncio
from pathlib import Path
from typing import Optional, Callable
from pyrogram import Client
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

from config import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    TELEGRAM_SESSION_NAME,
    DOWNLOAD_DIR
)

logger = logging.getLogger(__name__)


class PremiumDownloader:
    """Download files from Telegram using MTProto with premium account"""
    
    def __init__(self):
        """Initialize Pyrogram client with premium account"""
        if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
            raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in environment")
        
        self.client = Client(
            TELEGRAM_SESSION_NAME,
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
            workdir=str(Path.cwd())
        )
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._is_running = False
    
    async def start(self):
        """Start the MTProto client"""
        if not self._is_running:
            await self.client.start()
            self._is_running = True
            logger.info("✅ Premium MTProto client started successfully!")
            
            # Check if account is premium
            me = await self.client.get_me()
            if hasattr(me, 'is_premium') and me.is_premium:
                logger.info("✅ Premium account detected - fast downloads enabled!")
            else:
                logger.warning("⚠️ Account is not premium - downloads may be slower")
    
    async def stop(self):
        """Stop the MTProto client"""
        if self._is_running:
            await self.client.stop()
            self._is_running = False
            logger.info("MTProto client stopped")
    
    def _get_file_from_message(self, message: Message):
        """Extract file information from message"""
        file = None
        file_name = None
        file_size = 0
        file_type = None
        
        if message.document:
            file = message.document
            file_name = file.file_name or f"document_{message.id}"
            file_size = file.file_size or 0
            file_type = "document"
        elif message.video:
            file = message.video
            file_name = file.file_name or f"video_{message.id}.mp4"
            file_size = file.file_size or 0
            file_type = "video"
        elif message.audio:
            file = message.audio
            file_name = file.file_name or f"audio_{message.id}.mp3"
            file_size = file.file_size or 0
            file_type = "audio"
        elif message.photo:
            file = message.photo[-1]  # Get largest photo
            file_name = f"photo_{message.id}.jpg"
            file_size = file.file_size or 0
            file_type = "photo"
        elif message.video_note:
            file = message.video_note
            file_name = f"video_note_{message.id}.mp4"
            file_size = file.file_size or 0
            file_type = "video_note"
        elif message.voice:
            file = message.voice
            file_name = f"voice_{message.id}.ogg"
            file_size = file.file_size or 0
            file_type = "voice"
        elif message.sticker:
            file = message.sticker
            # Stickers can be .webp (static), .tgs (animated), or .webm (video)
            if hasattr(file, 'is_video') and file.is_video:
                ext = ".webm"
            elif hasattr(file, 'is_animated') and file.is_animated:
                ext = ".tgs"
            else:
                ext = ".webp"
            file_name = f"sticker_{message.id}{ext}"
            file_size = file.file_size or 0
            file_type = "sticker"
        
        return file, file_name, file_size, file_type
    
    async def download_file_from_message(
        self,
        chat_id: int,
        message_id: int,
        filename: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> Optional[Path]:
        """
        Download file from Telegram message using premium account
        
        Args:
            chat_id: Chat ID where message is located
            message_id: Message ID containing the file
            filename: Optional custom filename
            progress_callback: Optional callback(current, total) for progress
            
        Returns:
            Path to downloaded file, or None if failed
        """
        if not self._is_running:
            raise RuntimeError("MTProto client not started. Call start() first.")
        
        try:
            # Get message
            message = await self.client.get_messages(chat_id, message_id)
            
            if not message:
                logger.error(f"Message {message_id} not found in chat {chat_id}")
                return None
            
            # Extract file information
            file, file_name, file_size, file_type = self._get_file_from_message(message)
            
            if not file:
                logger.error(f"No file found in message {message_id}")
                return None
            
            # Use provided filename or default
            if not filename:
                filename = file_name
            
            # Ensure filename is safe
            filename = self._sanitize_filename(filename)
            
            file_path = self.download_dir / filename
            
            # If file already exists, add suffix
            if file_path.exists():
                stem = file_path.stem
                suffix = file_path.suffix
                counter = 1
                while file_path.exists():
                    file_path = self.download_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
            
            logger.info(f"Downloading {file_type} file: {filename} ({file_size / 1024 / 1024:.2f} MB)")
            
            # Progress callback wrapper
            def progress_wrapper(current: int, total: int):
                if progress_callback:
                    progress_callback(current, total)
                else:
                    # Default progress logging
                    percent = (current / total) * 100 if total > 0 else 0
                    if percent % 10 == 0 or current == total:  # Log every 10%
                        logger.info(f"Download progress: {percent:.1f}% ({current}/{total} bytes)")
            
            # Download using MTProto (premium speeds!)
            await self.client.download_media(
                message,
                file_name=str(file_path),
                progress=progress_wrapper
            )
            
            # Verify file was downloaded
            if file_path.exists() and file_path.stat().st_size > 0:
                actual_size = file_path.stat().st_size
                logger.info(f"✅ Download complete: {filename} ({actual_size / 1024 / 1024:.2f} MB)")
                return file_path
            else:
                logger.error(f"Download failed: File not found or empty")
                return None
                
        except FloodWait as e:
            logger.warning(f"Flood wait: {e.value} seconds")
            await asyncio.sleep(e.value)
            # Retry once
            return await self.download_file_from_message(chat_id, message_id, filename, progress_callback)
        except RPCError as e:
            logger.error(f"RPC Error downloading file: {e}")
            return None
        except Exception as e:
            logger.error(f"Error downloading file: {e}", exc_info=True)
            return None
    
    def _sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to remove invalid characters"""
        import re
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove leading/trailing spaces and dots
        filename = filename.strip(' .')
        # Ensure filename is not empty
        if not filename:
            filename = "file"
        return filename
    
    async def get_file_info(self, chat_id: int, message_id: int) -> Optional[dict]:
        """Get file information without downloading"""
        try:
            message = await self.client.get_messages(chat_id, message_id)
            if not message:
                return None
            
            file, file_name, file_size, file_type = self._get_file_from_message(message)
            
            if not file:
                return None
            
            return {
                'file_name': file_name,
                'file_size': file_size,
                'file_type': file_type,
                'chat_id': chat_id,
                'message_id': message_id
            }
        except Exception as e:
            logger.error(f"Error getting file info: {e}")
            return None
