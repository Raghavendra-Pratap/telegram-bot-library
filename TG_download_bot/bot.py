"""
Main Telegram Bot for Fast File Downloads using Premium Account
"""
import logging
import asyncio
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
from telegram.error import NetworkError, TimedOut

from config import (
    TELEGRAM_BOT_TOKEN,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    ENABLE_FILE_SERVER,
    FILE_SERVER_HOST,
    FILE_SERVER_PORT,
    USE_DYNAMIC_USER_MANAGEMENT,
    USERS_FILE
)
from mtproto_downloader import PremiumDownloader
from file_server import FileServer
from user_manager import UserManager

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize components
premium_downloader = PremiumDownloader()
file_server = FileServer() if ENABLE_FILE_SERVER else None
user_manager = UserManager(USERS_FILE) if USE_DYNAMIC_USER_MANAGEMENT else None


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
        
        error_message = (
            "🚫 *Access Denied*\n\n"
            "This bot is restricted to authorized users only.\n\n"
            "If you believe you should have access, please contact the bot administrator."
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

*Features:*
• ⚡ Premium download speeds
• 📦 Files up to 4GB supported
• 🔗 Direct download links
• ⏱️ Links expire after 24 hours

*Commands:*
/start - Show this message
/help - Get help
/status - Check bot status

Just forward a file to get started!
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
        mtproto_status = "✅ Running" if premium_downloader._is_running else "❌ Stopped"
        
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
        
        # Download using MTProto with premium account (FAST!)
        file_path = await premium_downloader.download_file_from_message(
            chat_id=message.chat.id,
            message_id=message.message_id,
            filename=file_name,
            progress_callback=progress_callback
        )
        
        if not file_path or not file_path.exists():
            await status_msg.edit_text(
                f"❌ *Download Failed*\n\n"
                f"Could not download the file.\n"
                f"Please try again or check if the file is accessible.",
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
        
        # Generate download link if file server is enabled
        if file_server:
            token, download_url = file_server.generate_download_link(file_path, file_name)
            
            keyboard = [
                [InlineKeyboardButton("🔗 Open Download Link", url=download_url)],
                [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{token}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await status_msg.edit_text(
                f"✅ *Download Complete!*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {actual_size_text}\n"
                f"📋 Type: {file_type}\n\n"
                f"🔗 Fast Download Link:\n`{download_url}`\n\n"
                f"⚡ Downloaded at premium speeds!\n"
                f"⏱️ Link expires in 24 hours.",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            # File server disabled, just show success
            await status_msg.edit_text(
                f"✅ *Download Complete!*\n\n"
                f"📁 File: `{file_name}`\n"
                f"📦 Size: {actual_size_text}\n"
                f"📂 Path: `{file_path.absolute()}`\n\n"
                f"⚡ Downloaded at premium speeds!",
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot"""
    error = context.error
    
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}. Will retry...")
        return
    
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


async def main():
    """Start the bot and all services"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return
    
    # Start MTProto client (premium account)
    try:
        await premium_downloader.start()
    except Exception as e:
        logger.error(f"Failed to start MTProto client: {e}")
        logger.error("Make sure TELEGRAM_API_ID and TELEGRAM_API_HASH are set correctly")
        return
    
    # Start file server if enabled
    if file_server:
        try:
            await file_server.start(FILE_SERVER_HOST, FILE_SERVER_PORT)
        except Exception as e:
            logger.error(f"Failed to start file server: {e}")
            logger.warning("File server disabled, download links will not work")
    
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
    
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.ALL, handle_file))
    
    # Start bot
    logger.info("Bot starting...")
    try:
        await application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    finally:
        # Cleanup
        await premium_downloader.stop()
        if file_server:
            await file_server.stop()


if __name__ == "__main__":
    asyncio.run(main())
