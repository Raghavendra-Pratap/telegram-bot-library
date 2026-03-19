"""
Main Telegram Bot for Fast File Downloads using Premium Account
"""
import logging
import asyncio
import time
from pathlib import Path
from datetime import datetime, timedelta
from urllib.parse import urlparse
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
from telegram.error import NetworkError, TimedOut, Conflict

from config import (
    TELEGRAM_BOT_TOKEN,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    ENABLE_FILE_SERVER,
    FILE_SERVER_HOST,
    FILE_SERVER_PORT,
    FILE_SERVER_BASE_URL,
    USE_DYNAMIC_USER_MANAGEMENT,
    USERS_FILE,
    INITIAL_ADMIN_USER_IDS
)
from mtproto_downloader import PremiumDownloader
from file_server import FileServer
from user_manager import UserManager
from port_utils import find_available_port

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize components
premium_downloader = PremiumDownloader()
file_server = FileServer() if ENABLE_FILE_SERVER else None
user_manager = UserManager(USERS_FILE, initial_admins=INITIAL_ADMIN_USER_IDS) if USE_DYNAMIC_USER_MANAGEMENT else None


def is_user_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot"""
    if not ENABLE_USER_VERIFICATION:
        return True
    
    # Use dynamic user management if enabled
    if USE_DYNAMIC_USER_MANAGEMENT and user_manager:
        return user_manager.is_allowed(user_id)
    
    # Fallback to legacy hardcoded list
    if not ALLOWED_USER_IDS:
        logger.warning("User verification enabled but no allowed users specified!")
        return False
    
    return user_id in ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    if USE_DYNAMIC_USER_MANAGEMENT and user_manager:
        return user_manager.is_admin(user_id)
    return False


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if user is authorized and send error message if not"""
    user_id = update.effective_user.id
    
    if not is_user_authorized(user_id):
        user_name = update.effective_user.username or update.effective_user.first_name or "User"
        logger.warning(f"Unauthorized access attempt by user {user_id} ({user_name})")
        
        # Check if user has pending request
        has_request = False
        if USE_DYNAMIC_USER_MANAGEMENT and user_manager:
            has_request = user_manager.has_pending_request(user_id)
        
        if has_request:
            error_message = (
                "🚫 *Access Denied*\n\n"
                "This bot is restricted to authorized users only.\n\n"
                "⏳ Your access request is pending approval.\n"
                "An admin will review your request soon."
            )
        else:
            error_message = (
                "🚫 *Access Denied*\n\n"
                "This bot is restricted to authorized users only.\n\n"
                "Use /request to request access from an admin."
            )
        
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
    if not await check_authorization(update, context):
        return
    
    welcome_message = """
⚡ *Telegram Download Accelerator Bot*

Download files from Telegram at **premium speeds**!

*How it works:*
1. Forward or share a file to this bot
2. Bot downloads it using premium account (fast!)
3. Get a fast download link
4. Download from our server (no throttling!)

*How It Works:*
1. 📤 Send or forward any file to this bot
2. ⚡ Bot downloads it using premium account (fast speeds!)
3. 🔗 Bot shares a direct download link from the server
4. ✅ Download the file from the link

*Features:*
• ⚡ Premium download speeds (up to 10x faster)
• 📦 Files up to 4GB supported
• 🔗 Direct download links
• ⏱️ Links expire after 24 hours

*Commands:*
/start - Show this message
/help - Get help
/status - Check bot status
/request - Request access (if verification enabled)

Just forward a file to get started!

*Admin Commands:*
/requests - View pending access requests
/approve <user_id> - Approve a user
/reject <user_id> - Reject a user
/adduser - Add a user directly
/listusers - List all users
"""
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    if not await check_authorization(update, context):
        return
    
    help_text = """
*How to use:*

1. **Forward a file** to this bot (from any chat)
2. Bot will download it using premium speeds
3. You'll get a **fast download link**
4. Download from the link (no Telegram throttling!)

*Supported file types:*
• Documents
• Videos
• Audio files
• Photos
• Voice messages
• Video notes
• Stickers

*File size limits:*
• Up to 4GB files supported
• No 20MB Bot API limit!

*Download links:*
• Links expire after 24 hours
• Files are automatically deleted after expiration
• Secure token-based access

*Note:*
This bot uses a premium Telegram account to download files faster.
Your files are processed securely and deleted after expiration.
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command"""
    if not await check_authorization(update, context):
        return
    
    try:
        # Check MTProto client status
        mtproto_running = premium_downloader.is_running if hasattr(premium_downloader, 'is_running') else premium_downloader._is_running
        mtproto_status = "✅ Running" if mtproto_running else "❌ Stopped"
        
        # Check file server status
        if file_server:
            server_status = "✅ Running"
        else:
            server_status = "❌ Disabled"
        
        # User management status
        if user_manager:
            total_users = len(user_manager.get_all_users())
            admin_count = len(user_manager.get_admin_users())
            user_count = len(user_manager.get_allowed_users())
            user_mgmt_status = f"✅ Enabled ({total_users} users: {admin_count} admins, {user_count} users)"
        else:
            user_mgmt_status = "❌ Disabled (using legacy mode)"
        
        status_text = f"""
*Bot Status*

*MTProto Client:* {mtproto_status}
*File Server:* {server_status}
*User Management:* {user_mgmt_status}

*Download Directory:*
`{premium_downloader.download_dir.absolute()}`

*Active Download Links:*
{len(file_server.file_store) if file_server else 0}
"""
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text(f"❌ Error getting status: {str(e)}")


def has_file(message) -> bool:
    """Check if message contains a file"""
    return bool(
        message.document or
        message.video or
        message.audio or
        message.photo or
        message.video_note or
        message.voice or
        message.sticker
    )


def get_file_info(message):
    """Extract file information from message"""
    file = None
    file_name = None
    file_size = 0
    file_type = None
    
    if message.document:
        file = message.document
        file_name = file.file_name or "document"
        file_size = file.file_size or 0
        file_type = "Document"
    elif message.video:
        file = message.video
        file_name = file.file_name or "video.mp4"
        file_size = file.file_size or 0
        file_type = "Video"
    elif message.audio:
        file = message.audio
        file_name = file.file_name or "audio.mp3"
        file_size = file.file_size or 0
        file_type = "Audio"
    elif message.photo:
        file = message.photo[-1]  # Largest
        file_name = "photo.jpg"
        file_size = file.file_size or 0
        file_type = "Photo"
    elif message.video_note:
        file = message.video_note
        file_name = "video_note.mp4"
        file_size = file.file_size or 0
        file_type = "Video Note"
    elif message.voice:
        file = message.voice
        file_name = "voice.ogg"
        file_size = file.file_size or 0
        file_type = "Voice"
    elif message.sticker:
        file = message.sticker
        file_name = "sticker.webp"
        file_size = file.file_size or 0
        file_type = "Sticker"
    
    return file, file_name, file_size, file_type


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file messages"""
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Check if message has a file
    if not has_file(message):
        return  # Not a file message, ignore
    
    # Get file information
    file, file_name, file_size, file_type = get_file_info(message)
    
    if not file:
        return
    
    # Format file size
    if file_size > 0:
        if file_size < 1024 * 1024:
            size_text = f"{file_size / 1024:.1f} KB"
        elif file_size < 1024 * 1024 * 1024:
            size_text = f"{file_size / (1024 * 1024):.1f} MB"
        else:
            size_text = f"{file_size / (1024 * 1024 * 1024):.2f} GB"
    else:
        size_text = "Unknown"
    
    # Show status message
    status_msg = await message.reply_text(
        f"⚡ *Fast Download Started*\n\n"
        f"📁 File: `{file_name}`\n"
        f"📦 Size: {size_text}\n"
        f"📋 Type: {file_type}\n\n"
        f"🚀 Downloading using premium account...",
        parse_mode=ParseMode.MARKDOWN
    )
    
    # Record download start time
    download_start_time = time.time()
    
    try:
        # Progress callback
        last_progress = [0]
        
        def progress_callback(current: int, total: int):
            if total > 0:
                percent = (current / total) * 100
                # Update every 10% or when complete
                if percent - last_progress[0] >= 10 or current == total:
                    last_progress[0] = percent
                    asyncio.create_task(
                        status_msg.edit_text(
                            f"⚡ *Downloading...*\n\n"
                            f"📁 File: `{file_name}`\n"
                            f"📦 Size: {size_text}\n\n"
                            f"⏳ Progress: {percent:.1f}%",
                            parse_mode=ParseMode.MARKDOWN
                        )
                    )
        
        # Check if MTProto is available - this is the ONLY download method
        # Use property to check if actually running and connected
        use_mtproto = premium_downloader.is_running if hasattr(premium_downloader, 'is_running') else premium_downloader._is_running
        
        if not use_mtproto:
            logger.error("MTProto client is not running - cannot download files")
            logger.error(f"MTProto _is_running flag: {premium_downloader._is_running}")
            logger.error(f"MTProto client object: {premium_downloader.client}")
            if hasattr(premium_downloader.client, 'is_connected'):
                logger.error(f"MTProto client is_connected: {premium_downloader.client.is_connected}")
            await status_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {size_text}\n\n"
                f"⚠️ *Premium download service is unavailable.*\n\n"
                f"The MTProto client is not running. Please contact the bot administrator.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        file_path = None
        mtproto_failed = False
        mtproto_error = None
        
        # Use MTProto for ALL files (fastest method, supports up to 4GB)
        if use_mtproto:
            try:
                logger.info(f"Downloading via MTProto (premium speeds): {file_name} ({size_text})")
                mtproto_running_check = premium_downloader.is_running if hasattr(premium_downloader, 'is_running') else premium_downloader._is_running
                logger.info(f"MTProto client status: Running={mtproto_running_check}")
                
                # For MTProto, we need to get the message from the user's perspective
                # When user sends/forwards to bot, from MTProto (user account) perspective:
                # We need to use the bot's username to access the chat
                bot_info = await context.bot.get_me()
                bot_username = bot_info.username
                
                # From MTProto (user account) perspective:
                # - Use bot's username to identify the chat (e.g., "@my_bot")
                # - message_id = same message_id from Bot API
                download_chat_id = bot_username  # Bot's username (Pyrogram accepts usernames)
                download_message_id = message.message_id  # Message ID in the chat
                
                logger.info(f"Getting message via MTProto: chat_id={download_chat_id} (bot username), message_id={download_message_id}")
                if message.forward_origin:
                    logger.info("Forwarded message detected - downloading from user's chat with bot")
                
                file_path = await premium_downloader.download_file_from_message(
                    chat_id=download_chat_id,
                    message_id=download_message_id,
                    filename=file_name,
                    progress_callback=progress_callback
                )
                
                # Check if MTProto download succeeded
                if file_path and file_path.exists():
                    downloaded_size = file_path.stat().st_size
                    logger.info(f"Downloaded file size: {downloaded_size / 1024 / 1024:.2f} MB")
                    
                    # Verify download is complete
                    if file_size > 0:
                        size_ratio = downloaded_size / file_size
                        logger.info(f"Size ratio: {size_ratio * 100:.1f}% (expected: ~100%)")
                        
                        if size_ratio < 0.9:
                            # Download is incomplete - mark as failed and try fallback
                            logger.error(f"CRITICAL: Download is only {size_ratio * 100:.1f}% complete!")
                            logger.error(f"Expected: {file_size / 1024 / 1024:.2f} MB, Got: {downloaded_size / 1024 / 1024:.2f} MB")
                            try:
                                file_path.unlink()
                            except:
                                pass
                            file_path = None
                            mtproto_failed = True
                            mtproto_error = f"Incomplete download: {size_ratio * 100:.1f}%"
                        else:
                            # Download successful - continue to file server
                            pass
                else:
                    # MTProto returned None - file not found or access denied
                    mtproto_failed = True
                    mtproto_error = "File not found or access denied"
                    logger.warning(f"MTProto returned None - download failed")
                    
            except ValueError as e:
                # Size mismatch error from downloader
                error_msg = str(e)
                logger.warning(f"MTProto download size mismatch: {e}")
                mtproto_failed = True
                mtproto_error = error_msg
            except Exception as e:
                error_str = str(e).lower()
                logger.warning(f"MTProto download failed: {e}")
                mtproto_failed = True
                mtproto_error = str(e)
        
        # If MTProto failed, show error (no fallback - MTProto is the only method)
        if mtproto_failed:
            logger.error(f"MTProto download failed: {mtproto_error}")
            await status_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {size_text}\n\n"
                f"⚠️ *Premium download failed.*\n\n"
                f"Error: {mtproto_error or 'Unknown error'}\n\n"
                f"Please try again later or contact the bot administrator.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        if not file_path or not file_path.exists():
            await status_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {size_text}\n\n"
                f"⚠️ *Sorry, the download could not be completed.*\n\n"
                f"Please try again in a few moments. If the problem persists, the file may be inaccessible.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Get actual file size
        actual_size = file_path.stat().st_size
        if actual_size < 1024 * 1024:
            actual_size_text = f"{actual_size / 1024:.1f} KB"
        elif actual_size < 1024 * 1024 * 1024:
            actual_size_text = f"{actual_size / (1024 * 1024):.1f} MB"
        else:
            actual_size_text = f"{actual_size / (1024 * 1024 * 1024):.2f} GB"
        
        # Calculate download time and speed
        download_end_time = time.time()
        download_duration = download_end_time - download_start_time
        
        # Format time
        if download_duration < 60:
            time_text = f"{download_duration:.1f} seconds"
        elif download_duration < 3600:
            minutes = int(download_duration // 60)
            seconds = int(download_duration % 60)
            time_text = f"{minutes}m {seconds}s"
        else:
            hours = int(download_duration // 3600)
            minutes = int((download_duration % 3600) // 60)
            time_text = f"{hours}h {minutes}m"
        
        # Calculate speed
        if download_duration > 0:
            speed_mbps = (actual_size / (1024 * 1024)) / download_duration
            if speed_mbps < 1:
                speed_text = f"{speed_mbps * 1024:.1f} KB/s"
            else:
                speed_text = f"{speed_mbps:.1f} MB/s"
        else:
            speed_text = "N/A"
        
        # Check for size difference
        size_diff_note = ""
        if file_size > 0:
            size_diff = abs(actual_size - file_size)
            size_diff_percent = (size_diff / file_size) * 100
            if size_diff_percent > 1.0:  # More than 1% difference
                if actual_size < file_size:
                    size_diff_note = f"\n\n⚠️ Note: Downloaded size ({actual_size_text}) is slightly smaller than expected ({size_text})."
                else:
                    size_diff_note = f"\n\nℹ️ Note: Downloaded size ({actual_size_text}) differs slightly from expected ({size_text})."
        
        # Generate download link if file server is enabled
        if file_server:
            token, download_url = file_server.generate_download_link(file_path, file_name)
            
            # Check if URL is localhost/local/private IP - Telegram doesn't allow these in inline buttons
            # Telegram's servers can't access localhost or private IPs (192.168.x.x, 10.x.x.x)
            parsed_url = urlparse(download_url)
            hostname = parsed_url.hostname or ""
            is_private = hostname in ['localhost', '127.0.0.1', '0.0.0.0'] or \
                        hostname.startswith('192.168.') or \
                        hostname.startswith('10.') or \
                        hostname.startswith('172.16.') or \
                        hostname.startswith('172.17.') or \
                        hostname.startswith('172.18.') or \
                        hostname.startswith('172.19.') or \
                        (hostname.startswith('172.') and 16 <= int(hostname.split('.')[1]) <= 31)
            
            if is_private:
                # For localhost URLs, don't use inline button (Telegram rejects it)
                # Just show the link as text with copy button
                keyboard = [
                    [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{token}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await status_msg.edit_text(
                    f"✅ *Download Complete!*\n\n"
                    f"📁 File: `{file_name}`\n"
                    f"📦 Size: {actual_size_text}\n"
                    f"📋 Type: {file_type}\n"
                    f"⏱️ Time: {time_text}\n"
                    f"🚀 Speed: {speed_text}\n\n"
                    f"🔗 *Download Link:*\n`{download_url}`\n\n"
                    f"⚠️ *Note:* This is a local network URL. Works on same WiFi.\n"
                    f"For clickable buttons, use a public IP/domain in `FILE_SERVER_BASE_URL`.\n\n"
                    f"⚡ Downloaded at premium speeds!\n"
                    f"⏱️ Link expires in 24 hours.{size_diff_note}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                # Public URL - can use inline button
                keyboard = [
                    [InlineKeyboardButton("🔗 Open Download Link", url=download_url)],
                    [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{token}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await status_msg.edit_text(
                    f"✅ *Download Complete!*\n\n"
                    f"📁 File: `{file_name}`\n"
                    f"📦 Size: {actual_size_text}\n"
                    f"📋 Type: {file_type}\n"
                    f"⏱️ Time: {time_text}\n"
                    f"🚀 Speed: {speed_text}\n\n"
                    f"🔗 Fast Download Link:\n`{download_url}`\n\n"
                    f"⚡ Downloaded at premium speeds!\n"
                    f"⏱️ Link expires in 24 hours.{size_diff_note}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            # File server disabled, just show success
            await status_msg.edit_text(
                f"✅ *Download Complete!*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {actual_size_text}\n"
                f"📋 Type: {file_type}\n"
                f"⏱️ Time: {time_text}\n"
                f"🚀 Speed: {speed_text}\n"
                f"📂 Path: `{file_path.absolute()}`\n\n"
                f"⚡ Downloaded at premium speeds!{size_diff_note}",
                parse_mode=ParseMode.MARKDOWN
            )
        
    except Exception as e:
        logger.error(f"Error handling file: {e}", exc_info=True)
        await status_msg.edit_text(
            f"❌ *Error*\n\n"
            f"`{str(e)}`\n\n"
            f"Please try again.",
            parse_mode=ParseMode.MARKDOWN
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("copy_"):
        token = data.replace("copy_", "")
        if file_server and token in file_server.file_store:
            file_info = file_server.file_store[token]
            from config import FILE_SERVER_BASE_URL
            download_url = f"{FILE_SERVER_BASE_URL}/download/{token}"
            await query.answer(f"Link copied! Use: {download_url}", show_alert=True)
        else:
            await query.answer("Link not found", show_alert=True)
    
    elif data.startswith("approve_"):
        # Approve request from callback
        target_user_id = int(data.replace("approve_", ""))
        
        if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
            await query.answer("Dynamic user management is disabled", show_alert=True)
            return
        
        if not is_admin(query.from_user.id):
            await query.answer("Only admins can approve requests", show_alert=True)
            return
        
        if not user_manager.has_pending_request(target_user_id):
            await query.answer("No pending request for this user", show_alert=True)
            return
        
        # Get request info
        req_info = user_manager.get_pending_requests().get(target_user_id, {})
        username = req_info.get('username', f'User {target_user_id}')
        
        # Approve
        user_manager.remove_request(target_user_id)
        user_manager.add_user(target_user_id, is_admin=False)
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "✅ *Access Approved!*\n\n"
                    "Your access request has been approved.\n"
                    "You can now use the bot!\n\n"
                    "Send /start to get started."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_user_id}: {e}")
        
        await query.edit_message_text(
            f"✅ *Approved*\n\n"
            f"👤 {username}\n"
            f"🆔 `{target_user_id}`\n\n"
            f"User has been notified and can now use the bot.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data.startswith("reject_"):
        # Reject request from callback
        target_user_id = int(data.replace("reject_", ""))
        
        if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
            await query.answer("Dynamic user management is disabled", show_alert=True)
            return
        
        if not is_admin(query.from_user.id):
            await query.answer("Only admins can reject requests", show_alert=True)
            return
        
        if not user_manager.has_pending_request(target_user_id):
            await query.answer("No pending request for this user", show_alert=True)
            return
        
        # Get request info
        req_info = user_manager.get_pending_requests().get(target_user_id, {})
        username = req_info.get('username', f'User {target_user_id}')
        
        # Reject
        user_manager.remove_request(target_user_id)
        
        # Notify user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    "❌ *Access Request Rejected*\n\n"
                    "Your access request has been rejected.\n\n"
                    "If you believe this is a mistake, please contact the bot administrator."
                ),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.warning(f"Could not notify user {target_user_id}: {e}")
        
        await query.edit_message_text(
            f"❌ *Rejected*\n\n"
            f"👤 {username}\n"
            f"🆔 `{target_user_id}`\n\n"
            f"User has been notified.",
            parse_mode=ParseMode.MARKDOWN
        )


async def adduser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /adduser command - Add a user to allowed list (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        await update.message.reply_text(
            "❌ Dynamic user management is disabled.\n"
            "Enable it in config to use this command."
        )
        return
    
    user_id = update.effective_user.id
    
    # Check if this is the first admin (no admins exist yet)
    # This must be checked BEFORE the admin check to allow bootstrap
    if len(user_manager.get_admin_users()) == 0:
        user_manager.set_initial_admin(user_id)
        await update.message.reply_text(
            "✅ *You are now the first admin!*\n\n"
            "You can now manage users with:\n"
            "• /adduser - Add a user\n"
            "• /removeuser - Remove a user\n"
            "• /listusers - List all users\n"
            "• /addadmin - Make someone admin",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if user is admin (only after bootstrap check)
    if not is_admin(user_id):
        await update.message.reply_text(
            "🚫 *Access Denied*\n\n"
            "Only admins can add users.\n\n"
            "Contact an admin to get access.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if replying to a message (easier way)
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        target_username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
    elif context.args and len(context.args) > 0:
        # Try to parse user ID from args
        try:
            target_user_id = int(context.args[0])
            target_username = f"User {target_user_id}"
        except ValueError:
            await update.message.reply_text(
                "❌ Invalid user ID. Please provide a number or reply to a user's message."
            )
            return
    else:
        await update.message.reply_text(
            "❌ *Usage:* `/adduser <user_id>`\n\n"
            "To get a user ID:\n"
            "• Forward a message from them to @userinfobot\n"
            "• Or reply to their message with `/adduser`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if making admin
    is_admin_flag = "--admin" in context.args or "-a" in context.args
    
    # Add user
    user_manager.add_user(target_user_id, is_admin=is_admin_flag)
    
    role = "admin" if is_admin_flag else "user"
    await update.message.reply_text(
        f"✅ *User Added*\n\n"
        f"👤 User: {target_username}\n"
        f"🆔 ID: `{target_user_id}`\n"
        f"👑 Role: {role}\n\n"
        f"They can now use the bot!",
        parse_mode=ParseMode.MARKDOWN
    )


async def removeuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removeuser command - Remove a user from allowed list (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        await update.message.reply_text(
            "❌ Dynamic user management is disabled."
        )
        return
    
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        await update.message.reply_text(
            "🚫 *Access Denied*\n\n"
            "Only admins can remove users.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if replying to a message (easier way)
    if update.message.reply_to_message:
        target_user_id = update.message.reply_to_message.from_user.id
        target_username = update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name
    elif context.args and len(context.args) > 0:
        try:
            target_user_id = int(context.args[0])
            target_username = f"User {target_user_id}"
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
    else:
        await update.message.reply_text(
            "❌ *Usage:* `/removeuser <user_id>`\n\n"
            "Or reply to a user's message with `/removeuser`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if removing admin
    is_admin_user = user_manager.is_admin(target_user_id)
    
    if is_admin_user:
        # Can't remove yourself
        if target_user_id == user_id:
            await update.message.reply_text("❌ You cannot remove yourself as admin!")
            return
        user_manager.remove_admin(target_user_id)
        role = "admin"
        removed = True
    else:
        removed = user_manager.remove_user(target_user_id)
        role = "user"
    
    if removed:
        await update.message.reply_text(
            f"✅ *User Removed*\n\n"
            f"👤 User: {target_username}\n"
            f"🆔 ID: `{target_user_id}`\n"
            f"👑 Role: {role}\n\n"
            f"They can no longer use the bot.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("❌ User not found in allowed list.")


async def listusers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /listusers command - List all allowed users (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        await update.message.reply_text(
            "❌ Dynamic user management is disabled."
        )
        return
    
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        await update.message.reply_text(
            "🚫 *Access Denied*\n\n"
            "Only admins can view user list.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    admins = user_manager.get_admin_users()
    users = user_manager.get_allowed_users()
    
    text = "👑 *Admins:*\n"
    if admins:
        for admin_id in admins:
            text += f"• `{admin_id}`\n"
    else:
        text += "• None\n"
    
    text += f"\n👤 *Users ({len(users)}):*\n"
    if users:
        for user_id in users:
            text += f"• `{user_id}`\n"
    else:
        text += "• None\n"
    
    text += f"\n*Total:* {len(admins) + len(users)} users"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def request_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /request command - Request access to the bot"""
    if not ENABLE_USER_VERIFICATION:
        await update.message.reply_text(
            "✅ Access verification is not enabled.\n"
            "You can use the bot freely!"
        )
        return
    
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        await update.message.reply_text(
            "❌ Dynamic user management is disabled.\n"
            "Please contact the bot administrator directly."
        )
        return
    
    user_id = update.effective_user.id
    
    # Check if already authorized
    if is_user_authorized(user_id):
        await update.message.reply_text(
            "✅ *You already have access!*\n\n"
            "You can use all bot features.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Check if already has pending request
    if user_manager.has_pending_request(user_id):
        await update.message.reply_text(
            "⏳ *Request Already Pending*\n\n"
            "You have already requested access.\n"
            "An admin will review your request soon.\n\n"
            "Please wait for approval.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Add request
    user_name = update.effective_user.username or update.effective_user.first_name or "User"
    user_manager.add_request(user_id, user_name, update.message.message_id)
    
    # Notify all admins
    admin_users = user_manager.get_admin_users()
    if admin_users:
        notification_text = (
            f"🔔 *New Access Request*\n\n"
            f"👤 User: {user_name}\n"
            f"🆔 ID: `{user_id}`\n\n"
            f"Use /requests to view all pending requests.\n"
            f"Or use buttons below to approve/reject."
        )
        
        # Create inline keyboard for quick approval
        keyboard = [
            [
                InlineKeyboardButton(f"✅ Approve {user_name[:15]}", callback_data=f"approve_{user_id}"),
                InlineKeyboardButton(f"❌ Reject", callback_data=f"reject_{user_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        for admin_id in admin_users:
            try:
                await update.message.bot.send_message(
                    chat_id=admin_id,
                    text=notification_text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                logger.warning(f"Could not notify admin {admin_id}: {e}")
    
    await update.message.reply_text(
        "✅ *Access Request Submitted*\n\n"
        "Your request has been sent to the administrators.\n"
        "You will be notified when your request is reviewed.\n\n"
        "⏳ Please wait for approval.",
        parse_mode=ParseMode.MARKDOWN
    )


async def requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /requests command - List pending access requests (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        await update.message.reply_text(
            "❌ Dynamic user management is disabled."
        )
        return
    
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        await update.message.reply_text(
            "🚫 *Access Denied*\n\n"
            "Only admins can view pending requests.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    pending = user_manager.get_pending_requests()
    
    if not pending:
        await update.message.reply_text(
            "✅ *No Pending Requests*\n\n"
            "There are no pending access requests.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    text = f"⏳ *Pending Access Requests ({len(pending)}):*\n\n"
    
    for req_user_id, req_info in pending.items():
        username = req_info.get('username', 'Unknown')
        timestamp = req_info.get('timestamp', time.time())
        req_time = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        
        text += f"👤 *{username}*\n"
        text += f"🆔 ID: `{req_user_id}`\n"
        text += f"⏰ Requested: {req_time}\n"
        text += f"✅ /approve_{req_user_id} | ❌ /reject_{req_user_id}\n\n"
    
    # Create inline keyboard for quick actions
    keyboard = []
    for req_user_id, req_info in list(pending.items())[:10]:  # Limit to 10 buttons
        username = req_info.get('username', f'User {req_user_id}')[:20]
        keyboard.append([
            InlineKeyboardButton(
                f"✅ Approve {username}",
                callback_data=f"approve_{req_user_id}"
            ),
            InlineKeyboardButton(
                f"❌ Reject {username}",
                callback_data=f"reject_{req_user_id}"
            )
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /approve command - Approve a user's access request (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        if update.message:
            await update.message.reply_text(
                "❌ Dynamic user management is disabled."
            )
        return
    
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text(
                "🚫 *Access Denied*\n\n"
                "Only admins can approve requests.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Get target user ID from command args
    target_user_id = None
    
    if update.message and context.args and len(context.args) > 0:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
    
    if not target_user_id:
        if update.message:
            await update.message.reply_text(
                "❌ *Usage:* `/approve <user_id>`\n\n"
                "Or use /requests to see pending requests with approve buttons.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Check if user has pending request
    if not user_manager.has_pending_request(target_user_id):
        await update.message.reply_text(
            f"❌ User `{target_user_id}` does not have a pending request.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get request info before removing
    req_info = user_manager.get_pending_requests().get(target_user_id, {})
    username = req_info.get('username', f'User {target_user_id}')
    
    # Remove request and add user
    user_manager.remove_request(target_user_id)
    user_manager.add_user(target_user_id, is_admin=False)
    
    # Notify the user
    try:
        bot = update.message.bot if update.message else context.bot
        await bot.send_message(
            chat_id=target_user_id,
            text=(
                "✅ *Access Approved!*\n\n"
                "Your access request has been approved.\n"
                "You can now use the bot!\n\n"
                "Send /start to get started."
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Could not notify user {target_user_id}: {e}")
    
    await update.message.reply_text(
        f"✅ *User Approved*\n\n"
        f"👤 User: {username}\n"
        f"🆔 ID: `{target_user_id}`\n\n"
        f"They can now use the bot!",
        parse_mode=ParseMode.MARKDOWN
    )


async def reject_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reject command - Reject a user's access request (Admin only)"""
    if not USE_DYNAMIC_USER_MANAGEMENT or not user_manager:
        if update.message:
            await update.message.reply_text(
                "❌ Dynamic user management is disabled."
            )
        return
    
    user_id = update.effective_user.id
    
    # Check if user is admin
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text(
                "🚫 *Access Denied*\n\n"
                "Only admins can reject requests.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Get target user ID from command args
    target_user_id = None
    
    if update.message and context.args and len(context.args) > 0:
        try:
            target_user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
    
    if not target_user_id:
        if update.message:
            await update.message.reply_text(
                "❌ *Usage:* `/reject <user_id>`\n\n"
                "Or use /requests to see pending requests with reject buttons.",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Check if user has pending request
    if not user_manager.has_pending_request(target_user_id):
        await update.message.reply_text(
            f"❌ User `{target_user_id}` does not have a pending request.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Get request info before removing
    req_info = user_manager.get_pending_requests().get(target_user_id, {})
    username = req_info.get('username', f'User {target_user_id}')
    
    # Remove request
    user_manager.remove_request(target_user_id)
    
    # Notify the user
    try:
        await context.bot.send_message(
            chat_id=target_user_id,
            text=(
                "❌ *Access Request Rejected*\n\n"
                "Your access request has been rejected.\n\n"
                "If you believe this is a mistake, please contact the bot administrator."
            ),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.warning(f"Could not notify user {target_user_id}: {e}")
    
    await update.message.reply_text(
        f"❌ *Request Rejected*\n\n"
        f"👤 User: {username}\n"
        f"🆔 ID: `{target_user_id}`\n\n"
        f"The user has been notified.",
        parse_mode=ParseMode.MARKDOWN
    )


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
            await asyncio.sleep(2)
        except Exception as e:
            logger.debug(f"Could not clear webhook: {str(e)}")
        return  # Don't log as error, just warn
    
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}. Will retry...")
        return
    
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


async def main():
    """Start the bot and all services"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return
    
    # Start MTProto client (premium account) - REQUIRED for all downloads
    # Uses retry logic with database lock handling
    try:
        logger.info("Starting MTProto client (with retry logic for database locks)...")
        await premium_downloader.start(max_retries=3, retry_delay=5)
        # Verify it actually started
        if not premium_downloader.is_running:
            logger.error("❌ CRITICAL: MTProto client failed to start!")
            logger.error("   Downloads will NOT work without MTProto client.")
            logger.error("   Please check the logs above for authentication errors.")
            raise RuntimeError("MTProto client failed to start")
        logger.info("✅ MTProto client started and verified")
    except RuntimeError as e:
        # Database lock or other critical errors
        if "database is locked" in str(e).lower():
            logger.error(f"❌ CRITICAL: {e}")
            logger.error("   Another bot instance may be running.")
            logger.error("   To fix:")
            logger.error("   1. Stop all instances: ./start_production.sh stop")
            logger.error("   2. Wait 5 seconds")
            logger.error("   3. Start again: ./start_production.sh start")
        raise
    except Exception as e:
        logger.error(f"❌ CRITICAL: Failed to start MTProto client: {e}")
        logger.error("   Downloads will NOT work without MTProto client.")
        logger.error("   This bot requires MTProto to be running for ALL downloads.")
        logger.error("   To fix:")
        logger.error("   1. Check your .env file has correct TELEGRAM_API_ID and TELEGRAM_API_HASH")
        logger.error("   2. Run bot interactively: python bot.py")
        logger.error("   3. Complete Pyrogram authentication (phone + code)")
        logger.error("   4. Restart the bot using: ./start_production.sh restart")
        raise
    
    # Start file server if enabled (use an available port if preferred one is in use)
    if file_server:
        try:
            actual_port = find_available_port(FILE_SERVER_PORT)
            if actual_port != FILE_SERVER_PORT:
                logger.info(f"Port {FILE_SERVER_PORT} in use → file server using port {actual_port}")
            if "://" in FILE_SERVER_BASE_URL and ":" in FILE_SERVER_BASE_URL.split("://", 1)[1]:
                base_url = FILE_SERVER_BASE_URL.rsplit(":", 1)[0] + ":" + str(actual_port)
            else:
                base_url = f"http://localhost:{actual_port}"
            await file_server.start(FILE_SERVER_HOST, actual_port, base_url=base_url)
        except Exception as e:
            logger.error(f"Failed to start file server: {e}")
            logger.warning("File server disabled, download links will not work")
    
    # Initialize admins from config if provided
    if USE_DYNAMIC_USER_MANAGEMENT and user_manager and INITIAL_ADMIN_USER_IDS:
        for admin_id in INITIAL_ADMIN_USER_IDS:
            if not user_manager.is_admin(admin_id):
                user_manager.add_user(admin_id, is_admin=True)
                logger.info(f"Initialized admin from config: {admin_id}")
    
    # Create bot application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    
    # User management commands (if dynamic management is enabled)
    if USE_DYNAMIC_USER_MANAGEMENT and user_manager:
        application.add_handler(CommandHandler("adduser", adduser_command))
        application.add_handler(CommandHandler("removeuser", removeuser_command))
        application.add_handler(CommandHandler("listusers", listusers_command))
        application.add_handler(CommandHandler("approve", approve_command))
        application.add_handler(CommandHandler("reject", reject_command))
        application.add_handler(CommandHandler("requests", requests_command))
    
    # Access request command (available to all users)
    if ENABLE_USER_VERIFICATION:
        application.add_handler(CommandHandler("request", request_command))
    
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.ALL, handle_file))
    
    # Start bot
    logger.info("Bot starting...")
    logger.info("✅ Bot is ready!")
    try:
        await application.initialize()
        await application.start()
        try:
            await application.updater.start_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
        except Conflict as e:
            logger.error("❌ Bot conflict detected during polling startup!")
            logger.error("Another bot instance is already running.")
            logger.warning("Bot will continue - conflict handler will manage this")
            # Don't return, let the bot continue - the error handler will catch future conflicts
        
        logger.info("✅ Bot polling started! Press Ctrl+C to stop.")
        # Keep the event loop running
        try:
            # Wait indefinitely until interrupted
            while True:
                await asyncio.sleep(3600)  # Sleep for 1 hour, then check again
        except asyncio.CancelledError:
            logger.info("Bot shutdown requested")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Error in bot polling: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Cleanup
        try:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()
        except:
            pass
        try:
            await premium_downloader.stop()
        except:
            pass
        if file_server:
            try:
                await file_server.stop()
            except:
                pass


if __name__ == "__main__":
    # Use asyncio.run for proper event loop management
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
