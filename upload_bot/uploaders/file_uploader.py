"""
File uploader with Telegram quality options and grouping support
"""
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Union, Callable
from telegram import Bot, InputMediaDocument, InputMediaPhoto, InputMediaVideo, InputMediaAudio
from telegram.constants import ParseMode

from utils.file_scanner import FileInfo
from utils.tree_builder import TreeBuilder
from config import UPLOAD_DELAY, MAX_FILE_SIZE_FREE, MAX_FILE_SIZE_PREMIUM

logger = logging.getLogger(__name__)


class FileUploader:
    """Handles file uploads to Telegram with various options"""
    
    # File type detection
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv'}
    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'}
    
    def __init__(self, bot: Bot, delay: float = UPLOAD_DELAY):
        """
        Initialize file uploader
        
        Args:
            bot: Telegram Bot instance
            delay: Delay between uploads (seconds)
        """
        self.bot = bot
        self.delay = delay
    
    def detect_file_type(self, file_info: FileInfo) -> str:
        """
        Detect file type from extension
        
        Args:
            file_info: FileInfo object
        
        Returns:
            File type: 'photo', 'video', 'audio', or 'document'
        """
        ext = file_info.extension.lower()
        
        if ext in self.IMAGE_EXTENSIONS:
            return 'photo'
        elif ext in self.VIDEO_EXTENSIONS:
            return 'video'
        elif ext in self.AUDIO_EXTENSIONS:
            return 'audio'
        else:
            return 'document'
    
    def determine_upload_type(self, file_info: FileInfo, metadata: Optional[Dict] = None) -> str:
        """
        Determine how to upload file (auto, document, photo, video, audio)
        
        Args:
            file_info: FileInfo object
            metadata: Optional metadata dict with 'upload_as' key
        
        Returns:
            Upload type string
        """
        if metadata and 'upload_as' in metadata:
            upload_as = metadata['upload_as'].strip().lower()
            if upload_as in ['document', 'photo', 'video', 'audio']:
                return upload_as
        
        # Auto-detect based on file type
        return self.detect_file_type(file_info)
    
    def build_caption(self, file_info: FileInfo, metadata: Optional[Dict] = None, 
                     include_tree: bool = True) -> str:
        """
        Build caption for file upload
        
        Args:
            file_info: FileInfo object
            metadata: Optional metadata dict
            include_tree: Include tree path in caption
        
        Returns:
            Caption string
        """
        parts = []
        
        # Add tree path if requested
        if include_tree:
            tree_caption = TreeBuilder.format_tree_caption(file_info, include_filename=False)
            if tree_caption:
                parts.append(tree_caption)
        
        # Add filename
        parts.append(f"📄 {file_info.filename}")
        
        # Add file size
        size_mb = file_info.size / (1024 * 1024)
        if size_mb < 1024:
            size_text = f"{size_mb:.2f} MB"
        else:
            size_text = f"{size_mb / 1024:.2f} GB"
        parts.append(f"📦 Size: {size_text}")
        
        # Add metadata fields if available
        if metadata:
            if metadata.get('description'):
                parts.append(f"📝 {metadata['description']}")
            
            if metadata.get('tags'):
                tags = metadata['tags'].strip()
                if tags:
                    parts.append(f"🏷 Tags: {tags}")
        
        return "\n".join(parts)
    
    async def upload_single(self, file_info: FileInfo, chat_id: Union[int, str],
                           metadata: Optional[Dict] = None, 
                           upload_type: Optional[str] = None,
                           quality: Optional[str] = None,
                           include_tree: bool = True) -> bool:
        """
        Upload a single file
        
        Args:
            file_info: FileInfo object
            chat_id: Target chat/channel ID or username
            metadata: Optional metadata dict
            upload_type: Override upload type (document, photo, video, audio, auto)
            quality: Video quality (HD, high, standard, low)
            include_tree: Include tree path in caption
        
        Returns:
            True if successful, False otherwise
        """
        if not file_info.file_path.exists():
            logger.error(f"File does not exist: {file_info.file_path}")
            return False
        
        # Check file size
        file_size = file_info.size
        if file_size > MAX_FILE_SIZE_PREMIUM:
            logger.error(f"File too large: {file_size} bytes (max: {MAX_FILE_SIZE_PREMIUM})")
            return False
        
        # Determine upload type
        if upload_type is None:
            upload_type = self.determine_upload_type(file_info, metadata)
        
        # Build caption
        caption = self.build_caption(file_info, metadata, include_tree)
        
        # Override caption if provided in metadata
        if metadata and metadata.get('caption'):
            caption = metadata['caption']
        
        try:
            with open(file_info.file_path, 'rb') as file:
                # Upload based on type
                if upload_type == 'document' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'document'):
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=300,
                        write_timeout=300
                    )
                
                elif upload_type == 'photo' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'photo'):
                    await self.bot.send_photo(
                        chat_id=chat_id,
                        photo=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=300,
                        write_timeout=300
                    )
                
                elif upload_type == 'video' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'video'):
                    # Video quality settings
                    supports_streaming = True
                    if quality and quality.lower() in ['standard', 'low']:
                        supports_streaming = False
                    
                    await self.bot.send_video(
                        chat_id=chat_id,
                        video=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        supports_streaming=supports_streaming,
                        read_timeout=300,
                        write_timeout=300
                    )
                
                elif upload_type == 'audio' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'audio'):
                    await self.bot.send_audio(
                        chat_id=chat_id,
                        audio=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=300,
                        write_timeout=300
                    )
                
                else:
                    # Fallback to document
                    await self.bot.send_document(
                        chat_id=chat_id,
                        document=file,
                        caption=caption,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=300,
                        write_timeout=300
                    )
                
                logger.info(f"Uploaded {file_info.filename} to {chat_id}")
                return True
        
        except Exception as e:
            logger.error(f"Error uploading {file_info.filename}: {e}")
            return False
    
    async def upload_media_group(self, files: List[FileInfo], chat_id: Union[int, str],
                                metadata_list: Optional[List[Dict]] = None,
                                group_caption: Optional[str] = None,
                                include_tree: bool = True) -> bool:
        """
        Upload files as a media group (appears together)
        
        Args:
            files: List of FileInfo objects (max 10 for media groups)
            chat_id: Target chat/channel ID or username
            metadata_list: Optional list of metadata dicts (one per file)
            group_caption: Optional caption for the group
            include_tree: Include tree path in captions
        
        Returns:
            True if successful, False otherwise
        """
        if not files:
            return False
        
        # Telegram media groups are limited to 10 items
        if len(files) > 10:
            logger.warning(f"Media group limited to 10 files, uploading first 10")
            files = files[:10]
            if metadata_list:
                metadata_list = metadata_list[:10]
        
        # Build media list
        media = []
        for idx, file_info in enumerate(files):
            if not file_info.file_path.exists():
                logger.warning(f"Skipping non-existent file: {file_info.file_path}")
                continue
            
            metadata = metadata_list[idx] if metadata_list and idx < len(metadata_list) else None
            upload_type = self.determine_upload_type(file_info, metadata)
            
            # Build individual caption
            caption = self.build_caption(file_info, metadata, include_tree)
            if metadata and metadata.get('caption'):
                caption = metadata['caption']
            
            try:
                with open(file_info.file_path, 'rb') as file:
                    if upload_type == 'photo' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'photo'):
                        media.append(InputMediaPhoto(media=file, caption=caption, parse_mode=ParseMode.MARKDOWN))
                    elif upload_type == 'video' or (upload_type == 'auto' and self.detect_file_type(file_info) == 'video'):
                        media.append(InputMediaVideo(media=file, caption=caption, parse_mode=ParseMode.MARKDOWN))
                    else:
                        # Documents and other types can't be in media groups, will upload separately
                        logger.warning(f"File {file_info.filename} cannot be in media group, will upload separately")
                        continue
            except Exception as e:
                logger.error(f"Error preparing {file_info.filename} for media group: {e}")
                continue
        
        if not media:
            logger.error("No valid media files for media group")
            return False
        
        try:
            # Send media group
            await self.bot.send_media_group(
                chat_id=chat_id,
                media=media,
                read_timeout=300,
                write_timeout=300
            )
            
            # If group caption provided, send it as separate message
            if group_caption:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=group_caption,
                    parse_mode=ParseMode.MARKDOWN
                )
            
            logger.info(f"Uploaded media group with {len(media)} files to {chat_id}")
            return True
        
        except Exception as e:
            logger.error(f"Error uploading media group: {e}")
            return False
    
    async def upload_sequential(self, files: List[FileInfo], chat_id: Union[int, str],
                               metadata_list: Optional[List[Dict]] = None,
                               shared_caption_prefix: Optional[str] = None,
                               include_tree: bool = True,
                               progress_callback: Optional[Callable] = None) -> Dict[FileInfo, bool]:
        """
        Upload files sequentially with optional shared caption prefix
        
        Args:
            files: List of FileInfo objects
            chat_id: Target chat/channel ID or username
            metadata_list: Optional list of metadata dicts
            shared_caption_prefix: Optional prefix to add to all captions
            include_tree: Include tree path in captions
            progress_callback: Optional callback function(current, total, file_info)
        
        Returns:
            Dictionary mapping FileInfo to success status
        """
        results = {}
        total = len(files)
        
        for idx, file_info in enumerate(files, 1):
            metadata = metadata_list[idx - 1] if metadata_list and idx - 1 < len(metadata_list) else None
            
            # Build caption with optional prefix
            caption = self.build_caption(file_info, metadata, include_tree)
            if shared_caption_prefix:
                caption = f"{shared_caption_prefix}\n\n{caption}"
            if metadata and metadata.get('caption'):
                caption = metadata['caption']
            
            # Get upload options from metadata
            upload_type = None
            quality = None
            if metadata:
                upload_type = metadata.get('upload_as')
                quality = metadata.get('quality')
            
            # Upload file
            success = await self.upload_single(
                file_info=file_info,
                chat_id=chat_id,
                metadata=metadata,
                upload_type=upload_type,
                quality=quality,
                include_tree=include_tree
            )
            
            results[file_info] = success
            
            # Progress callback
            if progress_callback:
                progress_callback(idx, total, file_info)
            
            # Delay between uploads
            if idx < total:
                await asyncio.sleep(self.delay)
        
        return results
    
    def get_chat_id(self, channel_spec: str, default_chat_id: Optional[Union[int, str]] = None) -> Union[int, str]:
        """
        Parse channel specification to chat ID
        
        Args:
            channel_spec: Channel username (@channel) or ID (-1001234567890)
            default_chat_id: Default chat ID if channel_spec is empty
        
        Returns:
            Chat ID (int or str)
        """
        if not channel_spec or not channel_spec.strip():
            return default_chat_id
        
        channel_spec = channel_spec.strip()
        
        # If it's a username, return as-is
        if channel_spec.startswith('@'):
            return channel_spec
        
        # Try to parse as integer
        try:
            return int(channel_spec)
        except ValueError:
            # Return as string (might be channel ID with minus sign)
            return channel_spec

