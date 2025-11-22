"""
Main Telegram Bot for Video Downloader
"""
import logging
import asyncio
import hashlib
import re
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode
from telegram.error import Conflict, TimedOut, NetworkError

from config import (
    TELEGRAM_BOT_TOKEN,
    DOWNLOAD_DIR,
    MAX_VIDEO_QUALITY,
    ENABLE_FILE_SERVER,
    FILE_SERVER_PORT,
    FILE_SERVER_HOST,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS
)
from utils.url_detector import URLDetector, Platform
from downloaders import (
    YouTubeDownloader,
    RedditDownloader,
    TwitterDownloader,
    InstagramDownloader,
    ThreadsDownloader,
    GIFDownloader
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize downloaders
downloaders = {
    Platform.YOUTUBE: YouTubeDownloader(DOWNLOAD_DIR),
    Platform.REDDIT: RedditDownloader(DOWNLOAD_DIR),
    Platform.TWITTER: TwitterDownloader(DOWNLOAD_DIR),
    Platform.INSTAGRAM: InstagramDownloader(DOWNLOAD_DIR),
    # Platform.THREADS: ThreadsDownloader(DOWNLOAD_DIR),  # Disabled for now
    Platform.GIF: GIFDownloader(DOWNLOAD_DIR),
}


def is_user_authorized(user_id: int) -> bool:
    """
    Check if user is authorized to use the bot
    
    Args:
        user_id: Telegram user ID
        
    Returns:
        True if user is authorized, False otherwise
    """
    # If verification is disabled, allow all users
    if not ENABLE_USER_VERIFICATION:
        return True
    
    # If no allowed users specified, deny all (safety measure)
    if not ALLOWED_USER_IDS:
        logger.warning("User verification enabled but no allowed users specified!")
        return False
    
    # Check if user ID is in allowed list
    return user_id in ALLOWED_USER_IDS


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if user is authorized and send error message if not
    
    Returns:
        True if authorized, False otherwise
    """
    user_id = update.effective_user.id
    
    if not is_user_authorized(user_id):
        user_name = update.effective_user.username or update.effective_user.first_name or "User"
        logger.warning(f"Unauthorized access attempt by user {user_id} ({user_name})")
        
        error_message = (
            "🚫 *Access Denied*\n\n"
            "This bot is restricted to authorized users only.\n\n"
            "If you believe you should have access, please contact the bot administrator."
        )
        
        # Try to send error message
        try:
            if update.message:
                await update.message.reply_text(error_message, parse_mode=ParseMode.MARKDOWN)
            elif update.callback_query:
                await update.callback_query.answer("Access denied", show_alert=True)
                await update.callback_query.edit_message_text(error_message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Error sending authorization message: {str(e)}")
        
        return False
    
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    welcome_message = """
🎬 *Video Downloader Bot*

Send me a link to download videos from:
• YouTube & YouTube Shorts
• Reddit
• Twitter/X
• Instagram Reels
• Threads
• GIFs (Giphy, Tenor, etc.)

*Features:*
• Highest quality available (up to 2160p)
• Audio extraction (MP3)
• Multiple format support

*Usage:*
1. Copy a video link from any supported platform
2. Paste it here or forward/share the post
3. I'll show you download options
4. Choose Video or Audio format
5. Download when ready!

*Commands:*
/start - Show this message
/help - Get help
"""
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    help_text = """
*How to use:*

1. Copy a video link from any supported platform
2. Paste it here or forward/share the post with the link
3. I'll analyze the link and show you options
4. Choose Video or Audio format
5. Click to download when ready!

*You can:*
• Copy and paste links directly
• Forward posts with video links
• Share video links from other apps

*Supported Platforms:*
• YouTube (including Shorts)
• Reddit
• Twitter/X
• Instagram Reels
• Threads
• GIF platforms

*Quality:*
Videos are downloaded in the highest available quality (up to 2160p).

*Note:*
This bot is for personal use only. Respect content creators' rights.
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def extract_url_from_message(message) -> str:
    """Extract URL from message text or entities"""
    # Check if message has text
    if message.text:
        text = message.text.strip()
        # Check if entire message is a URL
        if URLDetector.is_valid_url(text):
            return text
        # Extract URLs from text
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        if urls:
            return urls[0]
    
    # Check message entities for URLs
    if message.entities:
        for entity in message.entities:
            if entity.type == "url":
                url = message.text[entity.offset:entity.offset + entity.length]
                if URLDetector.is_valid_url(url):
                    return url
            elif entity.type == "text_link":
                if URLDetector.is_valid_url(entity.url):
                    return entity.url
    
    # Check caption if it's a forwarded message
    if message.caption:
        text = message.caption.strip()
        if URLDetector.is_valid_url(text):
            return text
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        if urls:
            return urls[0]
    
    return None


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle URL messages (including forwarded/shared posts)"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Extract URL from message
    url = extract_url_from_message(message)
    
    if not url:
        await message.reply_text(
            "❌ No valid URL found in your message.\n\n"
            "Please send or forward a video link from:\n"
            "• YouTube & YouTube Shorts\n"
            "• Reddit\n"
            "• Twitter/X\n"
            "• Instagram Reels\n"
            "• GIF platforms\n\n"
            "You can:\n"
            "• Copy and paste a link\n"
            "• Forward a post with a video link\n"
            "• Share a video link directly"
        )
        return
    
    # Validate URL
    if not URLDetector.is_valid_url(url):
        await message.reply_text("❌ Invalid URL. Please send a valid video URL.")
        return
    
    # Detect platform
    platform, _ = URLDetector.detect_platform(url)
    
    if platform == Platform.UNKNOWN:
        await message.reply_text(
            "❌ Unsupported platform.\n\n"
            "Please send a URL from:\n"
            "• YouTube & YouTube Shorts\n"
            "• Reddit\n"
            "• Twitter/X\n"
            "• Instagram Reels\n"
            "• GIF platforms (Giphy, Tenor, etc.)"
        )
        return
    
    # Show processing message
    processing_msg = await message.reply_text(
        f"🔍 *Analyzing {platform.value.upper()} link...*\n\n"
        "Fetching video information...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Get downloader
    downloader = downloaders.get(platform)
    if not downloader:
        await processing_msg.edit_text("❌ Downloader not available for this platform.")
        return
    
    # Get video info
    try:
        video_info = downloader.get_video_info(url)
        if not video_info:
            await processing_msg.edit_text(
                "❌ Could not fetch video information.\n\n"
                "Possible reasons:\n"
                "• Video is private or unavailable\n"
                "• Link is invalid or expired\n"
                "• Platform restrictions"
            )
            return
        
        # Show format selection with clear messaging
        # Use a short hash ID instead of full URL to avoid Telegram's 64-byte callback data limit
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]  # 12 char hash
        
        title = video_info.get('title', 'Video')[:60]
        
        # Store URL in context for later retrieval
        if 'urls' not in context.user_data:
            context.user_data['urls'] = {}
        
        # Clean up old entries if we have too many (keep last 10)
        if len(context.user_data['urls']) > 10:
            # Remove oldest entries (simple cleanup)
            keys_to_remove = list(context.user_data['urls'].keys())[:-10]
            for key in keys_to_remove:
                del context.user_data['urls'][key]
        
        # Store URL in context
        context.user_data['urls'][url_hash] = {
            'url': url,
            'platform': platform.value,
            'title': title
        }
        
        # Check if it's a playlist
        is_playlist = video_info.get('is_playlist', False)
        
        if is_playlist and platform == Platform.YOUTUBE:
            # Handle playlist
            video_count = video_info.get('video_count', 0)
            playlist_title = video_info.get('title', 'Playlist')
            entries = video_info.get('entries', [])
            
            # Store playlist info
            context.user_data['urls'][url_hash]['is_playlist'] = True
            
            # Try to get quality options from first video
            keyboard = []
            first_video_url = None
            
            if entries and len(entries) > 0:
                first_video = entries[0]
                first_video_url = (
                    first_video.get('url') or 
                    first_video.get('webpage_url') or 
                    f"https://www.youtube.com/watch?v={first_video.get('id', '')}"
                )
            
            # Get available formats for quality selection
            if first_video_url:
                try:
                    first_video_info = downloader.get_video_info(first_video_url)
                    available_formats = first_video_info.get('available_formats', []) if first_video_info else []
                    
                    if available_formats:
                        # Add quality options for playlist download
                        for fmt in available_formats[:4]:  # Limit to 4 options
                            resolution = fmt.get('resolution', 'Best')
                            filesize = fmt.get('filesize', 0)
                            
                            # Estimate total size (per video * count)
                            if filesize > 0:
                                estimated_total = filesize * video_count
                                if estimated_total < 1024 * 1024:
                                    size_text = f"{estimated_total / 1024:.1f} KB"
                                elif estimated_total < 1024 * 1024 * 1024:
                                    size_text = f"{estimated_total / (1024 * 1024):.1f} MB"
                                else:
                                    size_text = f"{estimated_total / (1024 * 1024 * 1024):.2f} GB"
                            else:
                                size_text = "~"
                            
                            format_id = fmt.get('format_id', 'best')
                            format_id_encoded = format_id.replace('+', 'PLUS').replace('/', 'SLASH')
                            button_text = f"📚 {resolution} ({size_text} total)"
                            callback_data = f"dl_{platform.value}_playlist_{format_id_encoded}_{url_hash}"
                            
                            keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                except Exception as e:
                    logger.warning(f"Could not get formats for playlist quality selection: {str(e)}")
            
            # Fallback: single download button if no formats available
            if not keyboard:
                keyboard.append([
                    InlineKeyboardButton(
                        f"📚 Download Entire Playlist ({video_count} videos)",
                        callback_data=f"dl_{platform.value}_playlist_best_{url_hash}"
                    )
                ])
            
            # Add option to download first video only
            keyboard.append([
                InlineKeyboardButton("📹 Download First Video Only", callback_data=f"dl_{platform.value}_video_best_{url_hash}")
            ])
            
            # Cancel button
            keyboard.append([
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            info_text = f"📚 *{playlist_title}*\n\n"
            info_text += f"📊 Videos: {video_count}\n\n"
            if keyboard and len(keyboard) > 2:  # Has quality options
                info_text += "*Choose download quality:*"
            else:
                info_text += "*Choose an option:*"
            
            await processing_msg.edit_text(
                info_text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Build keyboard with resolution options
        keyboard = []
        
        # Get available formats if available (for YouTube)
        available_formats = video_info.get('available_formats', [])
        
        if available_formats and platform == Platform.YOUTUBE:
            # Show video resolution options
            for fmt in available_formats[:5]:  # Limit to 5 options to avoid too many buttons
                resolution = fmt.get('resolution', 'Best')
                filesize = fmt.get('filesize', 0)
                
                # Format file size
                if filesize > 0:
                    if filesize < 1024 * 1024:  # Less than 1MB
                        size_text = f"{filesize / 1024:.1f} KB"
                    elif filesize < 1024 * 1024 * 1024:  # Less than 1GB
                        size_text = f"{filesize / (1024 * 1024):.1f} MB"
                    else:
                        size_text = f"{filesize / (1024 * 1024 * 1024):.2f} GB"
                else:
                    size_text = "~"
                
                format_id = fmt.get('format_id', 'best')
                # Encode format_id to avoid issues with special characters in callback data
                format_id_encoded = format_id.replace('+', 'PLUS').replace('/', 'SLASH')
                button_text = f"📹 {resolution} ({size_text})"
                callback_data = f"dl_{platform.value}_video_{format_id_encoded}_{url_hash}"
                
                keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
        else:
            # Fallback: single video button for non-YouTube or if formats not available
            keyboard.append([
                InlineKeyboardButton("📹 Download Video (Best Quality)", callback_data=f"dl_{platform.value}_video_best_{url_hash}")
            ])
        
        # Audio option
        keyboard.append([
            InlineKeyboardButton("🎵 Download Audio (MP3)", callback_data=f"dl_{platform.value}_audio_best_{url_hash}")
        ])
        
        # Cancel button
        keyboard.append([
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Build info text
        info_text = f"📹 *{title}*\n\n"
        
        if video_info.get('duration'):
            duration = video_info['duration']
            hours, remainder = divmod(duration, 3600)
            mins, secs = divmod(remainder, 60)
            if hours > 0:
                info_text += f"⏱ Duration: {hours}:{mins:02d}:{secs:02d}\n"
            else:
                info_text += f"⏱ Duration: {mins}:{secs:02d}\n"
        
        if video_info.get('uploader'):
            info_text += f"👤 Uploader: {video_info['uploader']}\n"
        
        if video_info.get('view_count'):
            views = video_info['view_count']
            if views > 1000000:
                info_text += f"👁 Views: {views/1000000:.1f}M\n"
            elif views > 1000:
                info_text += f"👁 Views: {views/1000:.1f}K\n"
            else:
                info_text += f"👁 Views: {views:,}\n"
        
        info_text += f"\n🌐 Platform: {platform.value.upper()}\n"
        info_text += f"🔗 [View Original]({url})\n"
        info_text += "\n" + "─" * 30 + "\n"
        info_text += "\n*Choose download option:*\n"
        info_text += "⬇️ Click a button below to download"
        
        await processing_msg.edit_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error processing URL: {str(e)}")
        await processing_msg.edit_text(
            f"❌ Error processing link:\n\n`{str(e)}`\n\n"
            "Please try again or check if the link is valid.",
            parse_mode=ParseMode.MARKDOWN
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Handle cancel
    if data == "cancel":
        await query.edit_message_text(
            "❌ Download cancelled.\n\n"
            "Send another link if you want to download a video."
        )
        return
    
    # Handle upload/local choice (will be handled in separate function)
    if data.startswith("upload_") or data.startswith("local_"):
        await handle_upload_choice(update, context)
        return
    
    if not data.startswith("dl_"):
        return
    
    # Parse callback data: dl_{platform}_{format}_{format_id}_{url_hash}
    # or: dl_{platform}_{format}_{url_hash} (legacy format)
    parts = data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("❌ Invalid request.")
        return
    
    format_type = parts[2]  # 'video', 'audio', or 'playlist'
    
    # Check if we have format_id (new format) or just url_hash (legacy)
    if len(parts) >= 5:
        # New format: dl_{platform}_{format}_{format_id}_{url_hash}
        format_id_encoded = parts[3]
        # Decode format_id
        format_id = format_id_encoded.replace('PLUS', '+').replace('SLASH', '/')
        url_hash = parts[4]  # url_hash is always 12 chars, no underscores
    else:
        # Legacy format: dl_{platform}_{format}_{url_hash}
        format_id = "best"
        url_hash = parts[3]
    
    # Retrieve URL from context
    if 'urls' not in context.user_data or url_hash not in context.user_data['urls']:
        await query.edit_message_text(
            "❌ Request expired or invalid.\n\n"
            "Please send the link again."
        )
        return
    
    url_data = context.user_data['urls'][url_hash]
    url = url_data['url']
    platform_str = url_data['platform']
    
    # Map platform string to enum
    platform_map = {
        'youtube': Platform.YOUTUBE,
        'reddit': Platform.REDDIT,
        'twitter': Platform.TWITTER,
        'instagram': Platform.INSTAGRAM,
        'gif': Platform.GIF,
    }
    
    platform = platform_map.get(platform_str)
    if not platform:
        await query.edit_message_text("❌ Unsupported platform.")
        return
    
    downloader = downloaders.get(platform)
    if not downloader:
        await query.edit_message_text("❌ Downloader not available.")
        return
    
    # Handle playlist download
    is_playlist = url_data.get('is_playlist', False)
    if format_type == "playlist" and platform == Platform.YOUTUBE and is_playlist:
        await query.edit_message_text("⏳ Downloading entire playlist...\nThis may take a while.")
        
        try:
            downloaded_files = downloader.download_playlist(url, quality=format_id, audio_only=False)
            
            if not downloaded_files:
                await query.edit_message_text("❌ Playlist download failed.")
                return
            
            file_count = len(downloaded_files)
            total_size = sum(f.stat().st_size for f in downloaded_files if f.exists())
            size_mb = total_size / (1024 * 1024)
            size_text = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
            
            # Get playlist folder path (parent directory of first file)
            playlist_folder = downloaded_files[0].parent if downloaded_files else downloader.download_dir
            
            # Store first file for upload choice
            file_path = downloaded_files[0] if downloaded_files else None
            
            url_hash_upload = hashlib.md5(f"{url_hash}_upload_playlist".encode()).hexdigest()[:12]
            url_hash_local = hashlib.md5(f"{url_hash}_local_playlist".encode()).hexdigest()[:12]
            
            context.user_data['urls'][url_hash_upload] = {
                'url': url,
                'platform': platform_str,
                'title': url_data['title'],
                'file_path': str(file_path) if file_path else '',
                'format_type': 'playlist',
                'is_playlist': True,
                'all_files': [str(f) for f in downloaded_files],
                'playlist_folder': str(playlist_folder)
            }
            context.user_data['urls'][url_hash_local] = {
                'url': url,
                'platform': platform_str,
                'title': url_data['title'],
                'file_path': str(file_path) if file_path else '',
                'format_type': 'playlist',
                'is_playlist': True,
                'all_files': [str(f) for f in downloaded_files],
                'playlist_folder': str(playlist_folder)
            }
            
            keyboard = [
                [InlineKeyboardButton("📤 Upload to Telegram", callback_data=f"upload_{url_hash_upload}")],
                [InlineKeyboardButton("💾 Keep Local Only", callback_data=f"local_{url_hash_local}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"✅ Playlist download complete!\n\n"
                f"📁 Files: {file_count} videos\n"
                f"📦 Total Size: {size_text}\n"
                f"📂 Folder: `{playlist_folder.absolute()}`\n\n"
                f"*Choose an option:*",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
            return
            
        except Exception as e:
            logger.error(f"Error downloading playlist: {str(e)}")
            await query.edit_message_text(f"❌ Playlist download error: {str(e)}")
            return
    
    # Update message
    format_text = "📹 Video" if format_type == "video" else "🎵 Audio"
    await query.edit_message_text(f"⏳ Downloading {format_text}...\nThis may take a while.")
    
    # Download
    try:
        audio_only = (format_type == "audio")
        
        # Use selected format for video, or quality setting
        if format_type == "video" and format_id and format_id != "best":
            quality = format_id  # Use specific format ID
        else:
            quality = MAX_VIDEO_QUALITY if format_type == "video" else "best"
        
        file_path = downloader.download(url, quality=quality, audio_only=audio_only)
        
        if not file_path or not file_path.exists():
            await query.edit_message_text("❌ Download failed. The video might be unavailable or private.")
            return
        
        # Format file size for display
        file_size = file_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
        
        # Ask user if they want to upload to Telegram
        url_hash_upload = hashlib.md5(f"{url_hash}_upload".encode()).hexdigest()[:12]
        url_hash_local = hashlib.md5(f"{url_hash}_local".encode()).hexdigest()[:12]
        
        # Store file info in context
        context.user_data['urls'][url_hash_upload] = {
            'url': url,
            'platform': platform_str,
            'title': url_data['title'],
            'file_path': str(file_path),
            'format_type': format_type
        }
        context.user_data['urls'][url_hash_local] = {
            'url': url,
            'platform': platform_str,
            'title': url_data['title'],
            'file_path': str(file_path),
            'format_type': format_type
        }
        
        keyboard = [
            [
                InlineKeyboardButton("📤 Upload to Telegram", callback_data=f"upload_{url_hash_upload}"),
            ],
            [
                InlineKeyboardButton("💾 Keep Local Only", callback_data=f"local_{url_hash_local}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"✅ Download complete!\n\n"
            f"📁 File: {file_path.name}\n"
            f"📦 Size: {size_text}\n"
            f"📂 Path: `{file_path.absolute()}`\n\n"
            f"*Choose an option:*",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error downloading: {str(e)}")
        await query.edit_message_text(f"❌ Download error: {str(e)}")


async def handle_upload_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle upload or local-only choice"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("upload_"):
        url_hash = data.replace("upload_", "")
        
        if url_hash not in context.user_data.get('urls', {}):
            await query.edit_message_text("❌ Request expired. Please download again.")
            return
        
        file_info = context.user_data['urls'][url_hash]
        format_type = file_info['format_type']
        is_playlist = file_info.get('is_playlist', False)
        
        # Handle playlist uploads differently - upload each video individually
        if is_playlist and format_type == "playlist":
            playlist_folder = Path(file_info.get('playlist_folder', ''))
            all_files = file_info.get('all_files', [])
            
            if not playlist_folder.exists():
                await query.edit_message_text("❌ Playlist folder not found.")
                return
            
            # Get all video files from playlist folder - sort for consistent order
            if all_files:
                video_files = sorted([Path(f) for f in all_files if Path(f).exists()], key=lambda x: x.name)
            else:
                video_files = sorted(playlist_folder.glob("*.mp4"), key=lambda x: x.name)
                # Also check for other formats
                if not video_files:
                    video_files = sorted(playlist_folder.glob("*.webm"), key=lambda x: x.name)
                if not video_files:
                    video_files = sorted(playlist_folder.glob("*.mkv"), key=lambda x: x.name)
            
            if not video_files:
                await query.edit_message_text("❌ No video files found in playlist folder.")
                return
            
            file_count = len(video_files)
            total_size = sum(f.stat().st_size for f in video_files)
            size_mb = total_size / (1024 * 1024)
            size_text = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
            
            # Start uploading files using queue system
            await query.edit_message_text(
                f"⏳ Starting playlist upload...\n\n"
                f"📁 Total: {file_count} videos\n"
                f"📦 Total Size: {size_text}\n\n"
                f"Processing upload queue...",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Process uploads in background task to avoid blocking
            import asyncio
            asyncio.create_task(
                upload_playlist_queue(
                    context,
                    query.message.chat_id,
                    query.message.message_id,
                    video_files,
                    playlist_folder
                )
            )
            return
        
        # Handle single file upload
        file_path = Path(file_info['file_path'])
        
        if not file_path.exists():
            await query.edit_message_text("❌ File not found.")
            return
        
        # Check file size (Telegram limit: 4GB for premium)
        file_size = file_path.stat().st_size
        max_size = 4 * 1024 * 1024 * 1024  # 4GB
        
        if file_size > max_size:
            file_size_mb = file_size / (1024 * 1024)
            size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
            await query.edit_message_text(
                f"❌ File too large ({size_text}). "
                f"Telegram limit is 4GB.\n\n"
                f"File saved at: `{file_path.absolute()}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Upload file
        await query.edit_message_text("⏳ Uploading to Telegram...\nThis may take a while.")
        
        try:
            # Format file size for display
            file_size_mb = file_size / (1024 * 1024)
            size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
            
            # Use asyncio timeout for file upload
            import asyncio
            
            try:
                # Pass file path directly to avoid file handle issues
                # python-telegram-bot can handle file paths directly
                if format_type == "audio":
                    # For audio, use longer timeout
                    await asyncio.wait_for(
                        query.message.reply_audio(
                            audio=str(file_path),
                            caption=f"✅ Downloaded: {file_path.name}\n📦 Size: {size_text}",
                            read_timeout=300,  # 5 minutes
                            write_timeout=300
                        ),
                        timeout=600  # 10 minutes total
                    )
                else:
                    # For video, use longer timeout and chunked upload
                    await asyncio.wait_for(
                        query.message.reply_video(
                            video=str(file_path),
                            caption=f"✅ Downloaded: {file_path.name}\n📦 Size: {size_text}",
                            supports_streaming=True,
                            read_timeout=300,  # 5 minutes
                            write_timeout=300
                        ),
                        timeout=600  # 10 minutes total
                    )
                
                await query.edit_message_text(
                    f"✅ Uploaded to Telegram!\n\n"
                    f"📁 File: {file_path.name}\n"
                    f"📦 Size: {size_text}\n\n"
                    f"📂 Local path: `{file_path.absolute()}`",
                    parse_mode=ParseMode.MARKDOWN
                )
                
            except asyncio.TimeoutError:
                logger.error("Upload timeout - file too large or slow connection")
                await query.edit_message_text(
                    f"⚠️ Upload timeout!\n\n"
                    f"📁 File saved at:\n`{file_path.absolute()}`\n"
                    f"📦 Size: {size_text}\n\n"
                    f"File is too large to upload via Telegram.\n"
                    f"You can access it from the local path above.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as e:
            logger.error(f"Error sending file: {str(e)}")
            file_size_mb = file_size / (1024 * 1024)
            size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
            
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
                error_display = "Upload timeout - File is too large or connection is slow"
            else:
                error_display = f"Error: {error_msg}"
            
            await query.edit_message_text(
                f"⚠️ Upload failed!\n\n"
                f"📁 File saved at:\n`{file_path.absolute()}`\n"
                f"📦 Size: {size_text}\n\n"
                f"{error_display}\n"
                f"You can access the file from the local path above.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data.startswith("local_"):
        url_hash = data.replace("local_", "")
        
        if url_hash not in context.user_data.get('urls', {}):
            await query.edit_message_text("❌ Request expired. Please download again.")
            return
        
        file_info = context.user_data['urls'][url_hash]
        file_path = Path(file_info['file_path'])
        
        if not file_path.exists():
            await query.edit_message_text("❌ File not found.")
            return
        
        file_size = file_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
        
        await query.edit_message_text(
            f"✅ File saved locally!\n\n"
            f"📁 File: {file_path.name}\n"
            f"📦 Size: {size_text}\n"
            f"📂 Path: `{file_path.absolute()}`\n\n"
            f"File is available on your system.",
            parse_mode=ParseMode.MARKDOWN
        )


async def upload_playlist_queue(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    status_message_id: int,
    video_files: list,
    playlist_folder: Path
):
    """Upload playlist files sequentially with proper queue handling"""
    import asyncio
    
    uploaded_count = 0
    failed_count = 0
    failed_files = []
    max_size = 4 * 1024 * 1024 * 1024  # 4GB Telegram limit
    max_retries = 3
    file_count = len(video_files)
    
    try:
        for idx, video_file in enumerate(video_files, 1):
            try:
                # Verify file exists
                if not video_file.exists():
                    logger.error(f"File does not exist: {video_file}")
                    failed_count += 1
                    failed_files.append(f"{video_file.name} (not found)")
                    continue
                
                file_size = video_file.stat().st_size
                
                # Skip empty files
                if file_size == 0:
                    logger.warning(f"File {video_file.name} is empty, skipping")
                    failed_count += 1
                    failed_files.append(f"{video_file.name} (empty)")
                    continue
                
                # Skip files that are too large
                if file_size > max_size:
                    logger.warning(f"File {video_file.name} is too large ({file_size / (1024*1024):.2f} MB), skipping")
                    failed_count += 1
                    failed_files.append(f"{video_file.name} (too large)")
                    continue
                
                # Update progress message
                file_size_mb = file_size / (1024 * 1024)
                file_size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"
                
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=status_message_id,
                        text=(
                            f"⏳ Uploading playlist...\n\n"
                            f"📹 File {idx}/{file_count}: {video_file.name[:50]}\n"
                            f"📦 Size: {file_size_text}\n\n"
                            f"✅ Uploaded: {uploaded_count}\n"
                            f"❌ Failed: {failed_count}"
                        ),
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as e:
                    logger.debug(f"Could not update status message: {str(e)}")
                
                # Upload with retry logic
                upload_success = False
                for retry in range(max_retries):
                    try:
                        logger.info(f"Uploading {idx}/{file_count}: {video_file.name} (attempt {retry + 1}/{max_retries})")
                        
                        # Upload video with timeout
                        await asyncio.wait_for(
                            context.bot.send_video(
                                chat_id=chat_id,
                                video=str(video_file.absolute()),
                                caption=f"📹 {video_file.name[:200]}\n📦 {file_size_text}",
                                supports_streaming=True,
                                read_timeout=300,  # 5 minutes
                                write_timeout=300
                            ),
                            timeout=600  # 10 minutes total per file
                        )
                        
                        uploaded_count += 1
                        upload_success = True
                        logger.info(f"✅ Successfully uploaded {idx}/{file_count}: {video_file.name}")
                        break  # Success, exit retry loop
                        
                    except asyncio.TimeoutError:
                        logger.error(f"Upload timeout (attempt {retry + 1}/{max_retries}) for {video_file.name}")
                        if retry < max_retries - 1:
                            await asyncio.sleep(5)  # Wait before retry
                        else:
                            failed_count += 1
                            failed_files.append(f"{video_file.name} (timeout)")
                    except Exception as upload_error:
                        error_msg = str(upload_error)
                        logger.error(f"Error uploading {video_file.name} (attempt {retry + 1}/{max_retries}): {error_msg}")
                        
                        # Check if it's a rate limit error
                        if "rate limit" in error_msg.lower() or "429" in error_msg or "flood" in error_msg.lower():
                            wait_time = (retry + 1) * 10  # Exponential backoff: 10s, 20s, 30s
                            logger.warning(f"Rate limited, waiting {wait_time} seconds before retry...")
                            await asyncio.sleep(wait_time)
                            continue
                        
                        if retry < max_retries - 1:
                            await asyncio.sleep(5)  # Wait before retry
                        else:
                            failed_count += 1
                            failed_files.append(f"{video_file.name} ({error_msg[:50]})")
                
                # Delay between uploads to avoid rate limiting
                if idx < file_count:  # Don't wait after last file
                    delay = 2 if upload_success else 5  # Longer delay if failed
                    await asyncio.sleep(delay)
                    
            except Exception as e:
                logger.error(f"Error processing {video_file.name}: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                failed_count += 1
                failed_files.append(f"{video_file.name} (error)")
                continue
        
        # Final summary
        total_size = sum(f.stat().st_size for f in video_files if f.exists())
        size_mb = total_size / (1024 * 1024)
        size_text = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"
        
        success_text = f"✅ Uploaded: {uploaded_count} videos"
        if failed_count > 0:
            success_text += f"\n❌ Failed: {failed_count} videos"
            if failed_files:
                failed_list = "\n".join([f"  • {f}" for f in failed_files[:5]])
                if len(failed_files) > 5:
                    failed_list += f"\n  ... and {len(failed_files) - 5} more"
                success_text += f"\n\nFailed files:\n{failed_list}"
        
        summary_text = (
            f"✅ Playlist upload complete!\n\n"
            f"{success_text}\n\n"
            f"📁 Total: {file_count} videos\n"
            f"📦 Total Size: {size_text}\n"
            f"📂 Folder: `{playlist_folder.absolute()}`\n\n"
            f"All videos are saved locally."
        )
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=summary_text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error updating final message: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in upload queue: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"❌ Upload queue error: {str(e)}",
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot"""
    error = context.error
    
    # Handle Conflict error (multiple bot instances)
    if isinstance(error, Conflict):
        logger.error("❌ Bot conflict detected!")
        logger.error("Another bot instance is already running.")
        logger.error("The bot will continue but may have issues.")
        logger.error("To fix: Stop all other bot instances and restart.")
        # Try to clear webhook and get updates
        try:
            await context.bot.delete_webhook(drop_pending_updates=True)
            logger.info("Cleared webhook and pending updates")
            # Wait a bit before continuing
            await asyncio.sleep(2)
        except Exception as e:
            logger.debug(f"Could not clear webhook: {str(e)}")
        return  # Don't log as error, just warn
    
    # Handle network errors
    elif isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}. Will retry...")
        return  # These are expected and will retry
    
    # Handle other errors
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    # Handle text messages and messages with captions (including forwarded messages with URLs)
    application.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.CAPTION, 
        handle_url
    ))
    
    # Start bot with conflict handling
    logger.info("Bot starting...")
    
    try:
        # Start polling with conflict handling
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Drop pending updates on start
            close_loop=False
        )
    except Conflict as e:
        logger.error("❌ Bot conflict detected!")
        logger.error("Another bot instance is already running.")
        logger.error("Please stop all other bot instances and try again.")
        logger.error(f"Error: {str(e)}")
        logger.error("\nTo fix:")
        logger.error("1. Find and stop other bot processes:")
        logger.error("   ps aux | grep bot.py")
        logger.error("2. Or kill all Python processes (be careful!):")
        logger.error("   pkill -f bot.py")
        logger.error("3. Wait a few seconds, then restart the bot")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()

