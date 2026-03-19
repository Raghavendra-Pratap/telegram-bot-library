"""
MTProto Downloader using Pyrogram with Premium Account
Downloads files at premium speeds using MTProto protocol
"""
import logging
import asyncio
import time
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
            workdir=str(Path.cwd()),
            no_updates=True,  # Don't handle updates (we use Bot API for that)
            # Optimize for speed
            max_concurrent_transmissions=3,  # Allow parallel downloads
            workers=4  # More workers for faster processing
        )
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """Check if client is actually running and connected"""
        if not self._is_running:
            return False
        try:
            # Check if client is actually connected
            # Pyrogram client has is_connected property
            if hasattr(self.client, 'is_connected'):
                return self.client.is_connected
            # Fallback: check if client has started
            if hasattr(self.client, 'is_initialized'):
                return self.client.is_initialized
            # Last resort: return the flag
            return self._is_running
        except Exception as e:
            logger.warning(f"Error checking MTProto client status: {e}")
            return self._is_running
    
    async def start(self, max_retries: int = 3, retry_delay: int = 5):
        """Start the MTProto client with retry logic for database locks"""
        if self._is_running:
            logger.info("MTProto client is already running")
            return
        
        session_file = Path(f"{self.client.name}.session")
        last_error = None
        
        for attempt in range(1, max_retries + 1):
            try:
                # Check if session file exists and is valid
                if session_file.exists():
                    logger.info(f"Found session file: {session_file}")
                else:
                    logger.warning(f"Session file not found: {session_file}")
                    logger.warning("MTProto client will need interactive authentication on first run")
                
                # Try to start the client
                await self.client.start()
                self._is_running = True
                logger.info("✅ Premium MTProto client started successfully!")
                
                # Check if account is premium
                me = await self.client.get_me()
                
                # Log account details for debugging
                account_type = "Bot" if (hasattr(me, 'is_bot') and me.is_bot) else "User"
                logger.info(f"Account type: {account_type} (ID: {me.id}, Name: {me.first_name})")
                
                # Check if this is a bot account (bots cannot have premium)
                if hasattr(me, 'is_bot') and me.is_bot:
                    logger.error("❌ CRITICAL: MTProto is authenticated as a BOT account!")
                    logger.error("   Bot accounts cannot have premium subscriptions.")
                    logger.error("   You must authenticate with your PERSONAL user account.")
                    logger.error("   To fix:")
                    logger.error("   1. Stop the bot")
                    logger.error("   2. Run: ./reauthenticate_premium.sh")
                    logger.error("   3. Enter your PHONE NUMBER (not bot token) when prompted")
                    logger.warning("⚠️ Using bot account - downloads will be slower (no premium)")
                elif hasattr(me, 'is_premium'):
                    if me.is_premium:
                        logger.info("✅ Premium account detected - fast downloads enabled!")
                        logger.info(f"   Account: {me.first_name} (User ID: {me.id})")
                    else:
                        logger.warning("⚠️ Account is not premium - downloads may be slower")
                        logger.info(f"   Account: {me.first_name} (User ID: {me.id})")
                        logger.info("   To enable premium speeds:")
                        logger.info("   1. Subscribe to Telegram Premium in the app")
                        logger.info("   2. Re-authenticate: ./reauthenticate_premium.sh")
                else:
                    logger.warning("⚠️ Cannot determine premium status (is_premium attribute not available)")
                    logger.info(f"   Account: {me.first_name} (User ID: {me.id})")
                    logger.info("   This might mean the account is not premium or Pyrogram version issue")
                
                # Success - return
                return
                
            except EOFError:
                # Session needs authentication but can't read from stdin
                logger.error("❌ MTProto client needs interactive authentication")
                logger.error("Session file exists but is not authenticated")
                logger.error("To fix: Run the bot interactively once to authenticate:")
                logger.error("  python bot.py")
                logger.error("Then enter your phone number and code when prompted")
                self._is_running = False
                raise
            except Exception as e:
                error_str = str(e).lower()
                last_error = e
                
                # Check if it's a database lock error
                if "database is locked" in error_str or "sqlite3.operationalerror" in error_str:
                    if attempt < max_retries:
                        logger.warning(f"⚠️ Database is locked (attempt {attempt}/{max_retries})")
                        logger.warning(f"   Another instance may be using the session file.")
                        logger.warning(f"   Waiting {retry_delay} seconds before retry...")
                        await asyncio.sleep(retry_delay)
                        # Try to kill any other processes using the session
                        await self._cleanup_locked_session(session_file)
                        continue
                    else:
                        logger.error(f"❌ Database lock persists after {max_retries} attempts")
                        logger.error("   Another bot instance is likely running.")
                        logger.error("   To fix:")
                        logger.error("   1. Stop all bot instances: pkill -9 -f 'python.*bot.py'")
                        logger.error("   2. Wait 5 seconds")
                        logger.error("   3. Restart the bot")
                        self._is_running = False
                        raise RuntimeError(f"Database is locked - another instance may be running. Error: {e}")
                else:
                    # Other errors - don't retry
                    logger.error(f"Failed to start MTProto client: {e}")
                    self._is_running = False
                    raise
        
        # If we get here, all retries failed
        if last_error:
            raise last_error
    
    async def _cleanup_locked_session(self, session_file: Path):
        """Try to clean up locked session files"""
        try:
            # Check for journal file (SQLite write-ahead log)
            journal_file = Path(f"{session_file}.journal")
            if journal_file.exists():
                logger.info(f"Removing stale journal file: {journal_file}")
                journal_file.unlink()
            
            # Check for WAL file (SQLite write-ahead log)
            wal_file = Path(f"{session_file}-wal")
            if wal_file.exists():
                logger.info(f"Removing stale WAL file: {wal_file}")
                wal_file.unlink()
            
            # Check for SHM file (SQLite shared memory)
            shm_file = Path(f"{session_file}-shm")
            if shm_file.exists():
                logger.info(f"Removing stale SHM file: {shm_file}")
                shm_file.unlink()
        except Exception as e:
            logger.debug(f"Could not clean up session files: {e}")
    
    async def stop(self):
        """Stop the MTProto client"""
        if self._is_running:
            try:
                await self.client.stop()
                self._is_running = False
                logger.info("MTProto client stopped")
            except Exception as e:
                logger.warning(f"Error stopping MTProto client: {e}")
                self._is_running = False
    
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
            file_type = "Document"
        elif message.video:
            file = message.video
            file_name = file.file_name or f"video_{message.id}.mp4"
            file_size = file.file_size or 0
            file_type = "Video"
        elif message.audio:
            file = message.audio
            file_name = file.file_name or f"audio_{message.id}.mp3"
            file_size = file.file_size or 0
            file_type = "Audio"
        elif message.photo:
            file = message.photo[-1]  # Get largest photo
            file_name = f"photo_{message.id}.jpg"
            file_size = file.file_size or 0
            file_type = "Photo"
        elif message.video_note:
            file = message.video_note
            file_name = f"video_note_{message.id}.mp4"
            file_size = file.file_size or 0
            file_type = "Video Note"
        elif message.voice:
            file = message.voice
            file_name = f"voice_{message.id}.ogg"
            file_size = file.file_size or 0
            file_type = "Voice"
        elif message.sticker:
            file = message.sticker
            # Determine sticker extension
            if hasattr(file, 'is_video') and file.is_video:
                file_name = f"sticker_{message.id}.webm"
            elif hasattr(file, 'is_animated') and file.is_animated:
                file_name = f"sticker_{message.id}.tgs"
            else:
                file_name = f"sticker_{message.id}.webp"
            file_size = file.file_size or 0
            file_type = "Sticker"
        
        return file, file_name, file_size, file_type

    async def download_file_from_file_id(
        self,
        file_id: str,
        filename: Optional[str] = None,
        file_size: int = 0,
        progress_callback: Optional[Callable] = None
    ) -> Optional[Path]:
        """
        Download file using Bot API file_id directly (works for forwarded files)
        
        Args:
            file_id: Bot API file_id from the message
            filename: Optional custom filename
            file_size: File size in bytes (for progress tracking)
            progress_callback: Optional callback(current, total) for progress
            
        Returns:
            Path to downloaded file, or None if failed
        """
        if not self._is_running:
            raise RuntimeError("MTProto client not started. Call start() first.")
        
        try:
            # Use provided filename or default
            if not filename:
                filename = "file"
            
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
            
            logger.info(f"Downloading file via file_id: {filename} ({file_size / 1024 / 1024:.2f} MB if known)")
            
            # Progress callback wrapper
            last_logged_percent = [0]
            def progress_wrapper(current: int, total: int):
                if progress_callback:
                    progress_callback(current, total)
                else:
                    # Default progress logging
                    percent = (current / total) * 100 if total > 0 else 0
                    # Log every 10% or when complete
                    if percent - last_logged_percent[0] >= 10 or current == total:
                        last_logged_percent[0] = percent
                        logger.info(f"Download progress: {percent:.1f}% ({current}/{total} bytes, {current / 1024 / 1024:.2f}/{total / 1024 / 1024:.2f} MB)")
            
            # Download using file_id directly (Pyrogram supports this)
            # Retry logic for large files
            max_retries = 2
            retry_count = 0
            download_success = False
            
            while retry_count <= max_retries and not download_success:
                try:
                    if retry_count > 0:
                        logger.info(f"Retrying download (attempt {retry_count + 1}/{max_retries + 1})...")
                        # Clean up any partial file from previous attempt
                        if file_path.exists():
                            try:
                                file_path.unlink()
                            except:
                                pass
                        await asyncio.sleep(2)  # Wait before retry
                    
                    # Download using file_id directly
                    logger.info(f"Starting download via file_id (attempt {retry_count + 1})...")
                    if file_size > 0:
                        logger.info(f"Expected file size: {file_size / 1024 / 1024:.2f} MB")
                    
                    # For very large files (>200MB), use streaming to avoid timeout/incomplete download issues
                    if file_size > 200 * 1024 * 1024:  # > 200MB
                        logger.info("Using streaming download for large file (more reliable)...")
                        # Stream download in chunks - more reliable for large files
                        total_downloaded = 0
                        chunk_count = 0
                        try:
                            with open(file_path, 'wb') as f:
                                async for chunk in self.client.stream_media(file_id):
                                    f.write(chunk)
                                    total_downloaded += len(chunk)
                                    chunk_count += 1
                                    # Update progress every 10 chunks or at end
                                    if chunk_count % 10 == 0 or (file_size > 0 and total_downloaded >= file_size):
                                        if progress_wrapper:
                                            progress_wrapper(total_downloaded, file_size if file_size > 0 else total_downloaded)
                            logger.info(f"Streaming download complete: {total_downloaded / 1024 / 1024:.2f} MB ({chunk_count} chunks)")
                        except Exception as stream_error:
                            logger.error(f"Streaming download error: {stream_error}", exc_info=True)
                            # Clean up partial file
                            if file_path.exists():
                                try:
                                    file_path.unlink()
                                except:
                                    pass
                            raise
                    else:
                        # Use direct download for better speed
                        await self.client.download_media(
                            file_id,
                            file_name=str(file_path),
                            progress=progress_wrapper,
                            block=True  # Block until complete
                        )
                    
                    download_success = True
                    
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"Download attempt {retry_count} failed: {e}")
                    if retry_count > max_retries:
                        logger.error(f"All download attempts failed after {max_retries + 1} tries")
                        raise
            
            # Verify file was downloaded
            if not file_path.exists():
                logger.error(f"Downloaded file does not exist: {file_path}")
                return None
            
            actual_size = file_path.stat().st_size
            logger.info(f"Downloaded file size: {actual_size / 1024 / 1024:.2f} MB")
            
            # Verify file size matches expected (allow 1% tolerance for metadata differences)
            if file_size > 0:
                size_diff = abs(actual_size - file_size)
                size_diff_percent = (size_diff / file_size) * 100
                
                if size_diff_percent > 1.0:  # More than 1% difference
                    logger.warning(f"File size mismatch: Expected {file_size / 1024 / 1024:.2f} MB, got {actual_size / 1024 / 1024:.2f} MB (diff: {size_diff_percent:.1f}%)")
                    
                    # If significantly smaller, likely incomplete download
                    if actual_size < file_size * 0.9:  # Less than 90% of expected
                        logger.error(f"❌ Download appears incomplete! Expected {file_size / 1024 / 1024:.2f} MB, got {actual_size / 1024 / 1024:.2f} MB")
                        logger.error(f"Removing incomplete file...")
                        try:
                            file_path.unlink()
                        except:
                            pass
                        raise ValueError(f"Download incomplete: got {actual_size / 1024 / 1024:.2f} MB, expected {file_size / 1024 / 1024:.2f} MB")
                else:
                    logger.info(f"✅ Download complete: {filename} ({actual_size / 1024 / 1024:.2f} MB)")
            else:
                logger.info(f"✅ Download complete: {filename} ({actual_size / 1024 / 1024:.2f} MB) - size unknown, file exists")
            
            return file_path
                
        except FloodWait as e:
            logger.warning(f"Flood wait: {e.value} seconds")
            await asyncio.sleep(e.value)
            # Retry once
            return await self.download_file_from_file_id(file_id, filename, file_size, progress_callback)
        except RPCError as e:
            logger.error(f"RPC Error downloading file: {e}")
            return None
        except Exception as e:
            logger.error(f"Error downloading file: {e}", exc_info=True)
            return None

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
            last_logged_percent = [0]
            def progress_wrapper(current: int, total: int):
                if progress_callback:
                    progress_callback(current, total)
                else:
                    # Default progress logging
                    percent = (current / total) * 100 if total > 0 else 0
                    # Log every 10% or when complete
                    if percent - last_logged_percent[0] >= 10 or current == total:
                        last_logged_percent[0] = percent
                        logger.info(f"Download progress: {percent:.1f}% ({current}/{total} bytes, {current / 1024 / 1024:.2f}/{total / 1024 / 1024:.2f} MB)")
            
            # Download using MTProto (premium speeds!)
            # Retry logic for large files
            max_retries = 2
            retry_count = 0
            download_success = False
            
            while retry_count <= max_retries and not download_success:
                try:
                    if retry_count > 0:
                        logger.info(f"Retrying download (attempt {retry_count + 1}/{max_retries + 1})...")
                        # Clean up any partial file from previous attempt
                        if file_path.exists():
                            try:
                                file_path.unlink()
                            except:
                                pass
                        await asyncio.sleep(2)  # Wait before retry
                    
                    # Download using MTProto
                    logger.info(f"Starting download (attempt {retry_count + 1})...")
                    logger.info(f"Expected file size: {file_size / 1024 / 1024:.2f} MB")
                    
                    # For very large files (>200MB), use streaming to avoid timeout/incomplete download issues
                    # For medium files (50-200MB), use direct download for better speed
                    # Streaming is more reliable but slower for large files
                    if file_size > 200 * 1024 * 1024:  # > 200MB
                        logger.info("Using streaming download for large file (more reliable)...")
                        # Stream download in chunks - more reliable for large files
                        total_downloaded = 0
                        chunk_count = 0
                        try:
                            with open(file_path, 'wb') as f:
                                async for chunk in self.client.stream_media(message):
                                    f.write(chunk)
                                    total_downloaded += len(chunk)
                                    chunk_count += 1
                                    # Update progress every 10 chunks or at end
                                    if chunk_count % 10 == 0 or total_downloaded == file_size:
                                        if progress_wrapper:
                                            progress_wrapper(total_downloaded, file_size if file_size > 0 else total_downloaded)
                            logger.info(f"Streaming download complete: {total_downloaded / 1024 / 1024:.2f} MB ({chunk_count} chunks)")
                        except Exception as stream_error:
                            logger.error(f"Streaming download error: {stream_error}", exc_info=True)
                            # Clean up partial file
                            if file_path.exists():
                                try:
                                    file_path.unlink()
                                except:
                                    pass
                            raise
                    else:
                        # Use direct download for better speed (faster than streaming)
                        # This is optimized for files < 200MB
                        await self.client.download_media(
                            message,
                            file_name=str(file_path),
                            progress=progress_wrapper,
                            block=True  # Block until complete
                        )
                    
                    download_success = True
                    
                except Exception as e:
                    retry_count += 1
                    logger.warning(f"Download attempt {retry_count} failed: {e}")
                    if retry_count > max_retries:
                        logger.error(f"All download attempts failed after {max_retries + 1} tries")
                        raise
            
            # Verify file was downloaded
            if not file_path.exists():
                logger.error(f"Downloaded file does not exist: {file_path}")
                return None
            
            actual_size = file_path.stat().st_size
            logger.info(f"Downloaded file size: {actual_size / 1024 / 1024:.2f} MB")
            
            # Verify file size matches expected (allow 1% tolerance for metadata differences)
            if file_size > 0:
                size_diff = abs(actual_size - file_size)
                size_diff_percent = (size_diff / file_size) * 100
                
                if size_diff_percent > 1.0:  # More than 1% difference
                    logger.warning(f"File size mismatch: Expected {file_size / 1024 / 1024:.2f} MB, got {actual_size / 1024 / 1024:.2f} MB (diff: {size_diff_percent:.1f}%)")
                    
                    # If significantly smaller, likely incomplete download
                    if actual_size < file_size * 0.9:  # Less than 90% of expected
                        logger.error(f"❌ Download appears incomplete! Expected {file_size / 1024 / 1024:.2f} MB, got {actual_size / 1024 / 1024:.2f} MB")
                        logger.error(f"Removing incomplete file...")
                        try:
                            file_path.unlink()
                        except:
                            pass
                        raise ValueError(f"Download incomplete: got {actual_size / 1024 / 1024:.2f} MB, expected {file_size / 1024 / 1024:.2f} MB")
                else:
                    logger.info(f"✅ Download complete: {filename} ({actual_size / 1024 / 1024:.2f} MB)")
            else:
                logger.info(f"✅ Download complete: {filename} ({actual_size / 1024 / 1024:.2f} MB) - size unknown, file exists")
            
            return file_path
                
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
