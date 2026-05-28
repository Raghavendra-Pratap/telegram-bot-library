"""
Main Telegram Bot for Video Downloader
"""
import logging
import asyncio
import hashlib
import re
import traceback
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

import datetime
from config import (
    TELEGRAM_BOT_TOKEN,
    DOWNLOAD_DIR,
    MAX_VIDEO_QUALITY,
    ENABLE_FILE_SERVER,
    FILE_SERVER_PORT,
    FILE_SERVER_HOST,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    ADMIN_USER_ID,
    MAX_CONCURRENT_UPLOADS,
    FILE_CLEANUP_DAYS,
    ANALYZE_WORKERS,
    DOWNLOAD_WORKERS,
    UPLOAD_WORKERS,
    MAX_BOT_UPLOAD_MB,
    MAX_BOT_UPLOAD_BYTES,
)
from queue_manager import (
    QueueManager,
    DownloadJob,
    PlaylistDownloadJob,
    UploadJob,
    AnalyzeUrlJob,
    PlaylistUploadJob,
)
from utils.url_detector import URLDetector, Platform
from downloaders import (
    YouTubeDownloader,
    RedditDownloader,
    TwitterDownloader,
    InstagramDownloader,
    ThreadsDownloader,
    GIFDownloader,
    TikTokDownloader,
)
from user_manager import UserManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Dynamic user approval manager
user_manager = UserManager()

# Background worker queue (workers started in post_init)
queue_manager = QueueManager(
    analyze_workers=ANALYZE_WORKERS,
    download_workers=DOWNLOAD_WORKERS,
    upload_workers=UPLOAD_WORKERS,
)

# Initialize downloaders
downloaders = {
    Platform.YOUTUBE: YouTubeDownloader(DOWNLOAD_DIR),
    Platform.REDDIT: RedditDownloader(DOWNLOAD_DIR),
    Platform.TWITTER: TwitterDownloader(DOWNLOAD_DIR),
    Platform.INSTAGRAM: InstagramDownloader(DOWNLOAD_DIR),
    Platform.THREADS: ThreadsDownloader(DOWNLOAD_DIR),
    Platform.GIF: GIFDownloader(DOWNLOAD_DIR),
    Platform.TIKTOK: TikTokDownloader(DOWNLOAD_DIR),
}


_bot_start_time = datetime.datetime.now()

_VIDEO_EXTS = {'.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.opus', '.ogg', '.gif'}


def cleanup_old_files(days: int = FILE_CLEANUP_DAYS) -> int:
    """Delete files in DOWNLOAD_DIR older than *days* days. Returns count deleted."""
    if days <= 0:
        return 0
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    deleted = 0
    for path in DOWNLOAD_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _VIDEO_EXTS:
            continue
        try:
            mtime = datetime.datetime.fromtimestamp(path.stat().st_mtime)
            if mtime < cutoff:
                path.unlink()
                deleted += 1
                logger.info(f"Cleanup: removed {path.name}")
        except Exception as e:
            logger.warning(f"Cleanup: could not remove {path}: {e}")
    return deleted


async def status_command(update: "Update", context: "ContextTypes.DEFAULT_TYPE") -> None:
    """Handle /status — show disk usage, file count, uptime, last cleanup."""
    if not await check_authorization(update, context):
        return

    # Disk usage of downloads folder
    total_size = 0
    file_count = 0
    for path in DOWNLOAD_DIR.rglob("*"):
        if path.is_file() and path.suffix.lower() in _VIDEO_EXTS:
            total_size += path.stat().st_size
            file_count += 1

    size_mb = total_size / (1024 * 1024)
    size_text = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{size_mb / 1024:.2f} GB"

    uptime = datetime.datetime.now() - _bot_start_time
    hours, rem = divmod(int(uptime.total_seconds()), 3600)
    mins = rem // 60
    uptime_text = f"{hours}h {mins}m" if hours else f"{mins}m"

    cleanup_note = (
        f"🧹 Auto-cleanup: files older than {FILE_CLEANUP_DAYS}d are removed"
        if FILE_CLEANUP_DAYS > 0
        else "🧹 Auto-cleanup: disabled"
    )

    an_pending = queue_manager.analyze_pending
    dl_pending = queue_manager.download_pending
    ul_pending = queue_manager.upload_pending
    queued = an_pending or dl_pending or ul_pending
    queue_note = (
        f"⚙️ Workers: {ANALYZE_WORKERS} analyze / {DOWNLOAD_WORKERS} dl / {UPLOAD_WORKERS} ul"
        + (
            f" | ⏳ Queued: {an_pending} analyze / {dl_pending} dl / {ul_pending} ul"
            if queued
            else ""
        )
    )

    await update.message.reply_text(
        f"📊 *Bot Status*\n\n"
        f"📁 Downloads: {file_count} files | {size_text}\n"
        f"📂 Folder: `{DOWNLOAD_DIR}`\n"
        f"🕒 Uptime: {uptime_text}\n"
        f"{queue_note}\n"
        f"{cleanup_note}",
        parse_mode=ParseMode.MARKDOWN,
    )


def _is_statically_allowed(user_id: int) -> bool:
    """True if user is in the static ALLOWED_USER_IDS list from .env."""
    if not ENABLE_USER_VERIFICATION:
        return True
    return user_id in ALLOWED_USER_IDS


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Gate every handler.  Returns True if the user may proceed.

    Access order:
      1. Verification disabled → allow everyone.
      2. User in static ALLOWED_USER_IDS → allow.
      3. User dynamically approved → allow.
      4. User denied → silent reject.
      5. User already pending → remind them.
      6. New user → create pending request, notify admin.
    """
    user = update.effective_user
    user_id = user.id

    # Fast paths
    if _is_statically_allowed(user_id):
        return True
    if user_manager.is_approved(user_id):
        return True

    # Denied
    if user_manager.is_denied(user_id):
        try:
            msg = "🚫 Your access request was denied."
            if update.message:
                await update.message.reply_text(msg)
            elif update.callback_query:
                await update.callback_query.answer("Access denied.", show_alert=True)
        except Exception:
            pass
        return False

    # Already waiting
    if user_manager.is_pending(user_id):
        try:
            if update.message:
                await update.message.reply_text(
                    "⏳ Your access request is pending admin approval. Please wait."
                )
            elif update.callback_query:
                await update.callback_query.answer("Request still pending.", show_alert=True)
        except Exception:
            pass
        return False

    # Brand-new user — register and ping admin
    name = user.full_name or "Unknown"
    username = user.username
    user_manager.add_pending(user_id, name, username)
    logger.warning(f"New access request: {user_id} ({name} / @{username})")

    if ADMIN_USER_ID:
        uname_display = f"@{username}" if username else "no username"
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton("❌ Deny",    callback_data=f"deny_{user_id}"),
            ]
        ])
        try:
            await context.bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=(
                    f"👤 *New access request*\n\n"
                    f"Name: {name}\n"
                    f"Username: {uname_display}\n"
                    f"ID: `{user_id}`"
                ),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Could not notify admin: {e}")
    else:
        logger.warning("ADMIN_USER_ID not set — cannot forward approval request.")

    try:
        if update.message:
            await update.message.reply_text(
                "📋 Access request sent to the admin. You'll be notified once approved."
            )
        elif update.callback_query:
            await update.callback_query.answer("Request sent to admin.", show_alert=True)
    except Exception:
        pass

    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    welcome_message = """
🎬 *Video Downloader Bot*

Send me a link to download videos from:
• YouTube & YouTube Shorts
• TikTok
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
• TikTok
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


def _pick_supported_url(candidates: list[str]) -> str | None:
    """Return the first URL that maps to a known platform, or None."""
    for url in candidates:
        if not URLDetector.is_valid_url(url):
            continue
        platform, _ = URLDetector.detect_platform(url)
        if platform != Platform.UNKNOWN:
            return url
    return None


def extract_url_from_message(message) -> str | None:
    """Extract the first *supported* URL from message text, entities, or caption."""
    _url_re = re.compile(r'https?://[^\s]+')

    # Collect candidates from text
    if message.text:
        candidates = _url_re.findall(message.text)
        result = _pick_supported_url(candidates)
        if result:
            return result

    # Entities (Telegram pre-parsed links)
    if message.entities and message.text:
        for entity in message.entities:
            if entity.type == "url":
                url = message.text[entity.offset:entity.offset + entity.length]
                platform, _ = URLDetector.detect_platform(url)
                if platform != Platform.UNKNOWN:
                    return url
            elif entity.type == "text_link":
                platform, _ = URLDetector.detect_platform(entity.url)
                if platform != Platform.UNKNOWN:
                    return entity.url

    # Caption (forwarded posts, shared links)
    if message.caption:
        candidates = _url_re.findall(message.caption)
        result = _pick_supported_url(candidates)
        if result:
            return result

    return None


async def _process_single_url(url: str, message, context: ContextTypes.DEFAULT_TYPE, status_message) -> None:
    """Fetch info for one URL and send the quality-selection keyboard (edits status_message)."""
    platform, _ = URLDetector.detect_platform(url)

    await status_message.edit_text(
        f"🔍 *Analyzing {platform.value.upper()} link...*\n\nFetching video information...",
        parse_mode=ParseMode.MARKDOWN,
    )

    downloader = downloaders.get(platform)
    if not downloader:
        await status_message.edit_text("❌ Downloader not available for this platform.")
        return

    # Get video info — run blocking I/O in a thread to keep the event loop free
    try:
        video_info = await asyncio.to_thread(downloader.get_video_info, url)
        if not video_info:
            await status_message.edit_text(
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
                        # Quality options for playlist (up to 6, skip "Best" duplicate)
                        for fmt in available_formats[:6]:
                            resolution = fmt.get('resolution', 'Best')
                            filesize = fmt.get('filesize', 0)

                            # Estimate total playlist size
                            if filesize > 0:
                                estimated_total = filesize * video_count
                                if estimated_total < 1024 * 1024:
                                    size_text = f"~{estimated_total / 1024:.0f} KB total"
                                elif estimated_total < 1024 * 1024 * 1024:
                                    size_text = f"~{estimated_total / (1024 * 1024):.0f} MB total"
                                else:
                                    size_text = f"~{estimated_total / (1024 * 1024 * 1024):.1f} GB total"
                            else:
                                size_text = "size unknown"

                            format_id = fmt.get('format_id', 'best')
                            format_id_encoded = format_id.replace('+', 'PLUS').replace('/', 'SLASH')
                            button_text = f"📚 {resolution} ({size_text})"
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
            
            await status_message.edit_text(
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
            # Show all distinct quality options (up to 8 buttons)
            for fmt in available_formats[:8]:
                resolution = fmt.get('resolution', 'Best')
                filesize = fmt.get('filesize', 0)

                if filesize > 0:
                    if filesize < 1024 * 1024:
                        size_text = f"~{filesize / 1024:.0f} KB"
                    elif filesize < 1024 * 1024 * 1024:
                        size_text = f"~{filesize / (1024 * 1024):.0f} MB"
                    else:
                        size_text = f"~{filesize / (1024 * 1024 * 1024):.1f} GB"
                else:
                    size_text = "size unknown"

                format_id = fmt.get('format_id', 'best')
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
        
        await status_message.edit_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error processing URL: {str(e)}")
        await status_message.edit_text(
            f"❌ Error processing link:\n\n`{str(e)}`\n\n"
            "Please try again or check if the link is valid.",
            parse_mode=ParseMode.MARKDOWN
        )


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for text messages. Extracts all supported URLs and processes each."""
    if not await check_authorization(update, context):
        return

    message = update.message

    # Collect all text from the message (text + caption)
    text_sources = []
    if message.text:
        text_sources.append(message.text)
    if message.caption:
        text_sources.append(message.caption)
    full_text = " ".join(text_sources)

    urls = URLDetector.extract_all_supported_urls(full_text)

    # Also surface text_link entities that may not appear as raw text
    for entity in list(message.entities or ()) + list(message.caption_entities or ()):
        if entity.type == "text_link":
            platform, _ = URLDetector.detect_platform(entity.url)
            if platform != Platform.UNKNOWN and entity.url not in urls:
                urls.append(entity.url)

    if not urls:
        await message.reply_text(
            "❌ No supported video link found.\n\n"
            "Supported: YouTube, TikTok, Instagram, Reddit, Twitter/X, Threads, GIFs"
        )
        return

    # Immediate ack per URL, then analyzer pool (limits concurrent get_video_info / yt-dlp)
    for url in urls:
        status_msg = await message.reply_text(
            "📥 *Link received — joining queue…*",
            parse_mode=ParseMode.MARKDOWN,
        )

        async def _run_analyze(
            u: str = url,
            m=message,
            ctx=context,
            sm=status_msg,
        ):
            await _process_single_url(u, m, ctx, sm)

        depth = await queue_manager.enqueue_analyze(AnalyzeUrlJob(run=_run_analyze))
        pos = f"Position **#{depth}** in analyzer queue." if depth > 1 else "Next up."
        await status_msg.edit_text(
            f"📥 *Queued*\n{pos}\n\n⏳ Analysis starts shortly — then pick quality.",
            parse_mode=ParseMode.MARKDOWN,
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    query = update.callback_query
    await query.answer()
    
    data = query.data

    # ── Admin approval / denial ──────────────────────────────────────────────
    if data.startswith("approve_") or data.startswith("deny_"):
        # Only the configured admin may act on these
        if update.effective_user.id != ADMIN_USER_ID:
            await query.answer("Only the admin can approve/deny users.", show_alert=True)
            return
        target_id = int(data.split("_", 1)[1])
        action = data.split("_", 1)[0]
        info = user_manager.get_pending_info(target_id)
        name = info.get("name", str(target_id))
        if action == "approve":
            user_manager.approve(target_id)
            await query.edit_message_text(f"✅ Approved {name} ({target_id}).")
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="✅ Your access request was approved! Send a video link to get started.",
                )
            except Exception:
                pass
        else:
            user_manager.deny(target_id)
            await query.edit_message_text(f"❌ Denied {name} ({target_id}).")
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text="🚫 Your access request was denied.",
                )
            except Exception:
                pass
        return

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
    
    # Callback format: dl_{platform}_{format_type}_{format_id_encoded}_{url_hash}
    # url_hash is always the LAST segment (12 hex chars, no underscores).
    # format_id_encoded sits between parts[3] and the last part; joining with "_"
    # handles any future format_ids that might contain underscores after encoding.
    parts = data.split("_")
    if len(parts) < 4:
        await query.edit_message_text("❌ Invalid request.")
        return

    format_type = parts[2]  # 'video', 'audio', or 'playlist'
    url_hash = parts[-1]    # always last, always 12 hex chars

    if len(parts) >= 5:
        format_id_encoded = "_".join(parts[3:-1])
        format_id = format_id_encoded.replace('PLUS', '+').replace('SLASH', '/')
    else:
        format_id = "best"
    
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
        'threads': Platform.THREADS,
        'gif': Platform.GIF,
        'tiktok': Platform.TIKTOK,
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

        async def _on_playlist_complete(files: list, size_text: str) -> None:
            file_count = len(files)
            playlist_folder = files[0].parent if files else downloader.download_dir
            context.user_data['urls'][url_hash].update({
                'file_path': str(files[0]),
                'format_type': 'playlist',
                'is_playlist': True,
                'all_files': [str(f) for f in files],
                'playlist_folder': str(playlist_folder),
            })
            keyboard = [
                [InlineKeyboardButton("📤 Upload to Telegram", callback_data=f"upload_{url_hash}")],
                [InlineKeyboardButton("💾 Keep Local Only",    callback_data=f"local_{url_hash}")],
            ]
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=(
                        f"✅ Playlist download complete!\n\n"
                        f"📁 Files: {file_count} videos\n"
                        f"📦 Total Size: {size_text}\n\n"
                        "*Choose an option:*"
                    ),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                logger.error(f"Could not update message after playlist download: {e}")

        async def _on_playlist_error(error_msg: str) -> None:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=f"❌ Playlist download error: {error_msg}",
                )
            except Exception:
                pass

        async def _on_playlist_begin() -> None:
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=(
                        "⏳ Playlist download — *active*\n\n"
                        "_Worker started. Saving many files can take a long time; "
                        "other downloads still run in parallel._"
                    ),
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception:
                pass

        playlist_job = PlaylistDownloadJob(
            url=url,
            downloader=downloader,
            quality=format_id,
            url_hash=url_hash,
            chat_id=query.message.chat_id,
            status_message_id=query.message.message_id,
            on_complete=_on_playlist_complete,
            on_error=_on_playlist_error,
            on_begin=_on_playlist_begin,
        )
        depth = await queue_manager.enqueue_download(playlist_job)
        pos_text = f" (#{depth} in queue)" if depth > 1 else ""
        await query.edit_message_text(f"⏳ Playlist download queued{pos_text}...")
        return
    
    # Enqueue the download and return immediately
    format_text = "📹 Video" if format_type == "video" else "🎵 Audio"
    audio_only = (format_type == "audio")
    quality = format_id if (format_type == "video" and format_id and format_id != "best") else (
        MAX_VIDEO_QUALITY if format_type == "video" else "best"
    )

    loop = asyncio.get_running_loop()

    def _progress_cb(percent: str, speed: str, eta: str) -> None:
        async def _edit():
            try:
                await context.bot.edit_message_text(
                    chat_id=query.message.chat_id,
                    message_id=query.message.message_id,
                    text=(
                        f"⏳ Downloading {format_text}...\n\n"
                        f"📊 {percent}  🚀 {speed}  ⏱ ETA {eta}"
                    ),
                )
            except Exception:
                pass
        asyncio.run_coroutine_threadsafe(_edit(), loop)

    async def _on_download_complete(file_path: Path, size_text: str) -> None:
        context.user_data['urls'][url_hash].update({
            'file_path': str(file_path),
            'format_type': format_type,
        })
        keyboard = [
            [InlineKeyboardButton("📤 Upload to Telegram", callback_data=f"upload_{url_hash}")],
            [InlineKeyboardButton("💾 Keep Local Only",    callback_data=f"local_{url_hash}")],
        ]
        try:
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=(
                    f"✅ Download complete!\n\n"
                    f"📁 File: {file_path.name}\n"
                    f"📦 Size: {size_text}\n\n"
                    "*Choose an option:*"
                ),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Could not update message after download: {e}")

    async def _on_download_error(error_msg: str) -> None:
        try:
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=f"❌ Download error: {error_msg}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "🔄 Try Again (Best Quality)",
                        callback_data=f"dl_{platform_str}_video_best_{url_hash}",
                    ),
                ]]),
            )
        except Exception:
            pass

    async def _on_download_begin() -> None:
        try:
            await context.bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id,
                text=(
                    f"⏳ {format_text} — *active*\n\n"
                    f"_Worker reserved. The site is queried for metadata before byte progress; "
                    f"%/speed show once the file download starts. Each link updates its own message._"
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    job = DownloadJob(
        url=url,
        downloader=downloader,
        quality=quality,
        audio_only=audio_only,
        format_type=format_type,
        platform_str=platform_str,
        url_hash=url_hash,
        chat_id=query.message.chat_id,
        status_message_id=query.message.message_id,
        on_complete=_on_download_complete,
        on_error=_on_download_error,
        on_begin=_on_download_begin,
        progress_cb=_progress_cb,
    )
    depth = await queue_manager.enqueue_download(job)
    pos_text = f" (#{depth} in queue)" if depth > 1 else ""
    await query.edit_message_text(f"⏳ {format_text} download queued{pos_text}...")


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
            
            async def _run_playlist_upload():
                try:
                    await upload_playlist_queue(
                        context,
                        query.message.chat_id,
                        query.message.message_id,
                        video_files,
                        playlist_folder,
                    )
                except Exception as exc:
                    logger.error(f"Playlist upload task crashed: {exc}")
                    logger.error(traceback.format_exc())

            pl_depth = await queue_manager.enqueue_upload(
                PlaylistUploadJob(run=_run_playlist_upload)
            )
            pl_pos = f" (#{pl_depth} in upload queue)" if pl_depth > 1 else ""
            await query.edit_message_text(
                f"⏳ Playlist upload queued{pl_pos}...\n\n"
                f"📁 Total: {file_count} videos\n"
                f"📦 Total Size: {size_text}\n\n"
                f"Files upload with limited parallelism to respect Telegram limits.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        
        # Handle single file upload
        file_path = Path(file_info['file_path'])

        if not file_path.exists():
            await query.edit_message_text("❌ File not found.")
            return

        # Cloud Bot API limit (~50 MB default); Premium does not increase bot upload size.
        file_size = file_path.stat().st_size
        if file_size > MAX_BOT_UPLOAD_BYTES:
            size_mb = file_size / (1024**2)
            await query.edit_message_text(
                f"❌ File is {size_mb:.1f} MB — bots may only send about **{MAX_BOT_UPLOAD_MB} MB** "
                f"per file via Telegram's cloud API (Premium doesn't change this).\n\n"
                f"📁 Saved locally: `{file_path.name}`\n"
                f"_Tip: lower quality, or run a local Bot API server and set MAX_BOT_UPLOAD_MB._",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        file_size_mb = file_size / (1024 * 1024)
        size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"

        # Reply-to the original user message so the file appears in context
        reply_to = (
            query.message.reply_to_message.message_id
            if query.message.reply_to_message
            else None
        )

        async def _on_upload_done(success: bool, msg: str) -> None:
            try:
                if success:
                    await context.bot.edit_message_text(
                        chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                        text=f"✅ Uploaded!\n\n📁 {file_path.name}\n📦 {size_text}",
                    )
                else:
                    await context.bot.edit_message_text(
                        chat_id=query.message.chat_id,
                        message_id=query.message.message_id,
                        text=(
                            f"⚠️ Upload failed: {msg}\n\n"
                            f"📁 Saved locally: `{file_path.name}`\n📦 {size_text}"
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
            except Exception as e:
                logger.error(f"Could not update upload status: {e}")

        upload_job = UploadJob(
            file_path=file_path,
            format_type=format_type,
            chat_id=query.message.chat_id,
            reply_to_message_id=reply_to,
            size_text=size_text,
            bot=context.bot,
            on_done=_on_upload_done,
        )
        ul_depth = await queue_manager.enqueue_upload(upload_job)
        ul_pos_text = f" (#{ul_depth} in queue)" if ul_depth > 1 else ""
        await query.edit_message_text(f"⏳ Upload queued{ul_pos_text}...")
    
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
        
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        size_text = f"{file_size_mb:.2f} MB" if file_size_mb < 1024 else f"{file_size_mb / 1024:.2f} GB"

        await query.edit_message_text(
            f"💾 Saved locally.\n\n📁 {file_path.name}\n📦 {size_text}",
        )


async def upload_playlist_queue(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    status_message_id: int,
    video_files: list,
    playlist_folder: Path,
) -> None:
    """Upload playlist files in parallel (up to MAX_CONCURRENT_UPLOADS at once)."""
    max_upload = MAX_BOT_UPLOAD_BYTES  # cloud Bot API per-file cap (see config MAX_BOT_UPLOAD_MB)
    MAX_RETRIES = 3
    file_count = len(video_files)

    uploaded_count = 0
    failed_count = 0
    failed_files: list[str] = []
    counter_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

    async def _upload_one(video_file: Path) -> None:
        nonlocal uploaded_count, failed_count

        if not video_file.exists() or video_file.stat().st_size == 0:
            async with counter_lock:
                failed_count += 1
                failed_files.append(f"{video_file.name} (missing/empty)")
            return

        file_size = video_file.stat().st_size
        if file_size > max_upload:
            async with counter_lock:
                failed_count += 1
                failed_files.append(
                    f"{video_file.name} (exceeds {MAX_BOT_UPLOAD_MB} MB bot API limit)"
                )
            return

        size_text = (
            f"{file_size / (1024**2):.1f} MB"
            if file_size < 1024 ** 3
            else f"{file_size / (1024**3):.2f} GB"
        )

        async with semaphore:
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    await asyncio.wait_for(
                        context.bot.send_video(
                            chat_id=chat_id,
                            video=str(video_file),
                            caption=f"📹 {video_file.name[:200]}\n📦 {size_text}",
                            supports_streaming=True,
                            read_timeout=300,
                            write_timeout=300,
                        ),
                        timeout=600,
                    )
                    async with counter_lock:
                        uploaded_count += 1
                    logger.info(f"Uploaded: {video_file.name}")
                    return  # success

                except asyncio.TimeoutError:
                    logger.warning(f"Timeout uploading {video_file.name} (attempt {attempt})")
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(5 * attempt)
                    else:
                        async with counter_lock:
                            failed_count += 1
                            failed_files.append(f"{video_file.name} (timeout)")

                except Exception as exc:
                    err = str(exc)
                    logger.error(f"Error uploading {video_file.name} attempt {attempt}: {err}")
                    el = err.lower()
                    if "entity too large" in el or "request entity too large" in el:
                        async with counter_lock:
                            failed_count += 1
                            failed_files.append(
                                f"{video_file.name} (too large for bot API — max ~{MAX_BOT_UPLOAD_MB} MB)"
                            )
                        return
                    if "rate limit" in el or "429" in err or "flood" in el:
                        await asyncio.sleep(10 * attempt)
                        continue
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(5)
                    else:
                        async with counter_lock:
                            failed_count += 1
                            failed_files.append(f"{video_file.name} ({err[:50]})")

        # Brief pause after each slot release to stay under flood limits
        await asyncio.sleep(1)

    async def _progress_updater() -> None:
        """Periodically refresh the status message while uploads are in flight."""
        while True:
            await asyncio.sleep(5)
            try:
                done = uploaded_count + failed_count
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=status_message_id,
                    text=(
                        f"⏳ Uploading playlist...\n\n"
                        f"✅ Done: {done}/{file_count}\n"
                        f"📤 Uploaded: {uploaded_count}  ❌ Failed: {failed_count}"
                    ),
                )
            except Exception:
                pass  # Message may not have changed — ignore edit conflicts

    try:
        updater_task = asyncio.create_task(_progress_updater())
        await asyncio.gather(*[_upload_one(f) for f in video_files], return_exceptions=True)
        updater_task.cancel()

        # Final summary
        total_size = sum(f.stat().st_size for f in video_files if f.exists())
        size_text = (
            f"{total_size / (1024**2):.1f} MB"
            if total_size < 1024 ** 3
            else f"{total_size / (1024**3):.2f} GB"
        )
        summary = (
            f"✅ Playlist upload complete!\n\n"
            f"📤 Uploaded: {uploaded_count}/{file_count}\n"
        )
        if failed_count:
            summary += f"❌ Failed: {failed_count}\n"
            items = "\n".join(f"  • {f}" for f in failed_files[:5])
            if len(failed_files) > 5:
                items += f"\n  … and {len(failed_files) - 5} more"
            summary += f"\nFailed:\n{items}\n"
        summary += f"\n📦 Total: {size_text}"

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=summary,
            )
        except Exception as e:
            logger.error(f"Could not send upload summary: {e}")

    except Exception as e:
        logger.error(f"upload_playlist_queue crashed: {e}")
        logger.error(traceback.format_exc())
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=status_message_id,
                text=f"❌ Upload error: {e}",
            )
        except Exception:
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


async def _post_init(application: "Application") -> None:
    """Start background worker pools after the bot is fully initialized."""
    await queue_manager.start()


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return

    # Create application — post_init starts the queue workers inside the event loop
    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)
        .build()
    )
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    # Handle text messages and messages with captions (including forwarded messages with URLs)
    application.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.CAPTION, 
        handle_url
    ))
    
    # Run startup cleanup
    if FILE_CLEANUP_DAYS > 0:
        removed = cleanup_old_files()
        if removed:
            logger.info(f"Startup cleanup: removed {removed} old file(s)")

    # Sanity-check config
    if ENABLE_USER_VERIFICATION and not ADMIN_USER_ID:
        logger.warning(
            "ENABLE_USER_VERIFICATION=true but ADMIN_USER_ID is not set — "
            "new users cannot be approved without an admin."
        )

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
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()

