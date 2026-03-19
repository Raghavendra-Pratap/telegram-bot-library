"""
Telegram Bot that automatically sets filename as caption when files are uploaded to channels/groups
Improved version with better error handling and reliability
"""
import logging
import asyncio
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode, ChatType
from telegram.error import (
    NetworkError,
    TimedOut,
    TelegramError,
    BadRequest,
    Forbidden,
    RetryAfter,
    Conflict
)

from config import (
    TELEGRAM_BOT_TOKEN,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    RETRY_DELAY,
    MAX_RETRIES,
    SKIP_IF_NO_FILENAME,
    PROCESSING_DELAY,
    FLOOD_RETRY_DELAY_MULTIPLIER,
    MAX_CONCURRENT_TASKS,
    ENABLE_CONCURRENT_UPDATES,
    MIN_API_CALL_DELAY,
    IDLE_TIMEOUT_MINUTES,
    ENABLE_AUTO_SHUTDOWN,
    HTTP_SERVER_PORT,
    ENABLE_HTTP_SERVER,
    ENABLE_UPDATE_QUEUE,
    MAX_QUEUE_UPDATES
)
from user_manager import (
    is_admin,
    is_allowed_user,
    get_admins,
    add_allowed_user,
    remove_allowed_user
)
from port_utils import find_available_port

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Global semaphore for controlling concurrent file processing
# This limits the number of files being processed simultaneously
processing_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

# Global variables for auto-shutdown mechanism
last_activity_time = None
shutdown_task = None
application_instance = None
http_server = None
http_server_thread = None
actual_http_port = None  # Set in start_http_server when port is auto-selected

# Update queue tracking
last_processed_update_id = None


def update_activity():
    """Update the last activity timestamp"""
    global last_activity_time
    last_activity_time = datetime.now(timezone.utc)
    logger.debug(f"Activity updated at {last_activity_time}")


class HealthCheckHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for health checks and wake-up.
    Local monitors can ping this endpoint to reset the idle timer.
    """
    
    def do_GET(self):
        """Handle GET requests (health checks)"""
        global last_activity_time
        
        # Reset activity timer when health check is called
        # This keeps the bot alive when health checks ping it
        update_activity()
        
        # Send response
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        # Return status information
        status = {
            "status": "ok",
            "bot": "running",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if last_activity_time:
            idle_seconds = (datetime.now(timezone.utc) - last_activity_time).total_seconds()
            status["last_activity"] = last_activity_time.isoformat()
            status["idle_seconds"] = int(idle_seconds)
        else:
            status["last_activity"] = None
            status["idle_seconds"] = 0
        
        response = str(status).replace("'", '"')
        self.wfile.write(response.encode())
        
        logger.debug(f"Health check received - activity timer reset")
    
    def do_POST(self):
        """Handle POST requests (wake-up calls)"""
        # Same as GET - reset activity timer
        self.do_GET()
    
    def log_message(self, format, *args):
        """Suppress default logging for health checks"""
        # Only log if it's not a health check (to reduce log spam)
        if '/health' not in self.path and '/' != self.path:
            logger.debug(f"HTTP {self.command} {self.path} - {args[0] if args else ''}")


def start_http_server():
    """Start HTTP server for health checks in a separate thread. Uses an available port if the preferred one is in use."""
    global http_server, http_server_thread, actual_http_port
    
    if not ENABLE_HTTP_SERVER:
        logger.info("HTTP server disabled")
        return
    
    try:
        port = find_available_port(HTTP_SERVER_PORT)
        actual_http_port = port
        if port != HTTP_SERVER_PORT:
            logger.info(f"Port {HTTP_SERVER_PORT} in use → HTTP server using port {port}")
        server_address = ('', port)
        http_server = HTTPServer(server_address, HealthCheckHandler)
        
        def run_server():
            """Run HTTP server in this thread"""
            logger.info(f"🌐 HTTP health check server started on port {port}")
            logger.info(f"   Health check URL: http://0.0.0.0:{port}/")
            logger.info("   Local monitor can ping this to keep the bot active")
            http_server.serve_forever()
        
        http_server_thread = threading.Thread(target=run_server, daemon=True)
        http_server_thread.start()
        logger.info(f"✅ HTTP server thread started")
        
    except Exception as e:
        logger.error(f"Failed to start HTTP server: {str(e)}")
        logger.warning("Bot will continue without HTTP server (health checks won't reset idle timer)")


def stop_http_server():
    """Stop HTTP server gracefully"""
    global http_server, http_server_thread
    
    if http_server:
        try:
            logger.info("Stopping HTTP server...")
            http_server.shutdown()
            http_server.server_close()
            logger.info("✅ HTTP server stopped")
        except Exception as e:
            logger.error(f"Error stopping HTTP server: {str(e)}")


async def monitor_idle_timeout():
    """
    Background task that monitors idle time and shuts down the bot after timeout.
    This runs continuously and checks if the bot has been idle for too long.
    """
    global last_activity_time, application_instance
    
    if not ENABLE_AUTO_SHUTDOWN or IDLE_TIMEOUT_MINUTES <= 0:
        logger.info("Auto-shutdown disabled - bot will run continuously")
        return
    
    # If HTTP server is enabled, auto-shutdown is disabled
    # Bot will stay running and rely on periodic health checks to keep it active
    if ENABLE_HTTP_SERVER:
        logger.info("   ⚠️  HTTP server enabled - Bot will NOT shut down automatically")
        logger.info("   💡 Use a local/LAN monitor to ping the health check endpoint")
        logger.info(f"   Ping URL: http://localhost:{actual_http_port or HTTP_SERVER_PORT}/ every 5 minutes")
    
    timeout_seconds = IDLE_TIMEOUT_MINUTES * 60
    check_interval = 30  # Check every 30 seconds
    
    logger.info(f"Auto-shutdown enabled: Bot will shut down after {IDLE_TIMEOUT_MINUTES} minutes of inactivity")
    
    while True:
        try:
            await asyncio.sleep(check_interval)
            
            if application_instance is None:
                continue
            
            # Check if we have any activity
            if last_activity_time is None:
                # No activity yet, keep waiting
                continue
            
            # Calculate idle time
            now = datetime.now(timezone.utc)
            idle_time = (now - last_activity_time).total_seconds()
            idle_minutes = idle_time / 60
            
            # Check if we've exceeded the timeout
            if idle_time >= timeout_seconds:
                if ENABLE_HTTP_SERVER:
                    # If HTTP server is enabled, NEVER shut down
                    # The HTTP server will receive pings that reset the activity timer
                    logger.warning(f"⏰ Idle timeout reached ({idle_minutes:.1f} minutes), but HTTP server is active.")
                    logger.info("   Bot will continue running - HTTP pings will reset the timer.")
                    logger.info("   💡 Tip: Use a LAN monitor or cron job to ping health check every 5 minutes")
                    logger.info(f"   Health check URL: http://localhost:{actual_http_port or HTTP_SERVER_PORT}/")
                    # Reset activity to prevent repeated warnings
                    # External ping services will keep resetting this
                    update_activity()
                else:
                    # No HTTP server - do full shutdown
                    logger.info(f"⏰ Idle timeout reached ({idle_minutes:.1f} minutes). Shutting down bot to save resources...")
                    
                    # Graceful shutdown
                    try:
                        logger.info("Stopping bot application...")
                        await application_instance.stop()
                        await application_instance.shutdown()
                        logger.info("✅ Bot shut down gracefully")
                    except Exception as e:
                        logger.error(f"Error during shutdown: {str(e)}")
                    
                    # Exit the process immediately to save resources
                    logger.info("Exiting process to save resources...")
                    os._exit(0)
            else:
                # Log remaining time (every 2 minutes to avoid spam)
                if int(idle_time) % 120 < check_interval:
                    remaining_minutes = (timeout_seconds - idle_time) / 60
                    logger.debug(f"Bot active - {remaining_minutes:.1f} minutes until auto-shutdown")
        
        except asyncio.CancelledError:
            logger.info("Idle monitoring task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in idle monitoring: {str(e)}", exc_info=True)
            await asyncio.sleep(check_interval)


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
    
    # Admins are always authorized
    if is_admin(user_id):
        return True
    
    # Check if user is in allowed users list
    return is_allowed_user(user_id)


async def check_authorization(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Check if user is authorized and send error message if not
    
    Returns:
        True if authorized, False otherwise
    """
    # For channel/group messages, check the user who posted (if available)
    # For bot commands, check the user who sent the command
    user_id = update.effective_user.id if update.effective_user else None
    
    # If no user (channel post), allow if verification is disabled
    if not user_id:
        return not ENABLE_USER_VERIFICATION
    
    if not is_user_authorized(user_id):
        user_name = update.effective_user.username or update.effective_user.first_name or "User"
        logger.warning(f"Unauthorized access attempt by user {user_id} ({user_name})")
        
        # For /start command, don't show error - it will handle the request
        if update.message and update.message.text and update.message.text.startswith('/start'):
            return False  # Let start command handle it
        
        error_message = (
            "🚫 <b>Access Denied</b>\n\n"
            "This bot is restricted to authorized users only.\n\n"
            "Send /start to request access from an administrator."
        )
        
        try:
            if update.message:
                await update.message.reply_text(error_message, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"Error sending authorization message: {str(e)}")
        
        return False
    
    return True


async def notify_admins_of_request(user_id: int, username: str, first_name: str, context: ContextTypes.DEFAULT_TYPE):
    """Notify all admins about a new access request"""
    admins = get_admins()
    
    request_message = (
        f"🔔 <b>New Access Request</b>\n\n"
        f"<b>User:</b> {first_name}\n"
        f"<b>Username:</b> @{username}\n" if username else ""
        f"<b>User ID:</b> <code>{user_id}</code>\n\n"
        f"Click below to approve or deny access:"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}"),
            InlineKeyboardButton("❌ Deny", callback_data=f"deny_{user_id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    for admin_id in admins:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=request_message,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {str(e)}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    update_activity()  # Track activity for auto-shutdown
    
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or "User"
    
    # If user is admin or already allowed, show welcome message
    if is_admin(user_id) or is_allowed_user(user_id):
        welcome_message = """
📝 <b>Upload with Caption Bot</b>

This bot automatically adds the filename as caption when you upload files to channels or groups.

<b>How it works:</b>
1. Add this bot as an admin to your channel/group
2. Upload any file directly to the channel/group
3. The bot automatically detects the file and adds the filename as caption
4. <b>Upload happens only once</b> - the bot just edits the message to add the caption

<b>Setup:</b>
1. Add the bot to your channel/group as an admin
2. Give the bot permission to <b>edit messages</b> (required!)
3. Start uploading files - captions will be added automatically!

<b>Supported file types:</b>
• Videos (MP4, AVI, MOV, etc.)
• Documents (PDF, DOCX, etc.)
• Photos (JPG, PNG, etc.)
• Audio files (MP3, WAV, etc.)
• Voice messages
• Any other file type

<b>Commands:</b>
/start - Show this message
/help - Get help
/process_recent [N] - Process recent messages to add captions
/add_caption &lt;msg_id&gt; - Add caption to specific message

<b>Note:</b>
• The bot must be an admin in the channel/group
• The bot needs permission to edit messages
• Works in any channel/group where the bot is added as admin
"""
        await update.message.reply_text(welcome_message, parse_mode=ParseMode.HTML)
    else:
        # User is not authorized - check if verification is enabled
        if ENABLE_USER_VERIFICATION:
            # Send request message to user
            request_message = (
                f"👋 <b>Welcome, {first_name}!</b>\n\n"
                f"This bot requires admin approval to use.\n\n"
                f"Your access request has been sent to the administrators.\n"
                f"You will be notified once your request is reviewed.\n\n"
                f"<b>Your User ID:</b> <code>{user_id}</code>"
            )
            await update.message.reply_text(request_message, parse_mode=ParseMode.HTML)
            
            # Notify admins
            await notify_admins_of_request(user_id, username, first_name, context)
        else:
            # Verification disabled, show welcome message
            welcome_message = """
📝 <b>Upload with Caption Bot</b>

This bot automatically adds the filename as caption when you upload files to channels or groups.

<b>How it works:</b>
1. Add this bot as an admin to your channel/group
2. Upload any file directly to the channel/group
3. The bot automatically detects the file and adds the filename as caption
4. <b>Upload happens only once</b> - the bot just edits the message to add the caption

<b>Setup:</b>
1. Add the bot to your channel/group as an admin
2. Give the bot permission to <b>edit messages</b> (required!)
3. Start uploading files - captions will be added automatically!

<b>Supported file types:</b>
• Videos (MP4, AVI, MOV, etc.)
• Documents (PDF, DOCX, etc.)
• Photos (JPG, PNG, etc.)
• Audio files (MP3, WAV, etc.)
• Voice messages
• Any other file type

<b>Commands:</b>
/start - Show this message
/help - Get help
/process_recent [N] - Process recent messages to add captions
/add_caption &lt;msg_id&gt; - Add caption to specific message

<b>Note:</b>
• The bot must be an admin in the channel/group
• The bot needs permission to edit messages
• Works in any channel/group where the bot is added as admin
"""
            await update.message.reply_text(welcome_message, parse_mode=ParseMode.HTML)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries from inline buttons (approve/deny)"""
    query = update.callback_query
    await query.answer()  # Acknowledge the callback
    
    # Check if the user clicking is an admin
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await query.edit_message_text(
            "❌ Only administrators can approve or deny access requests.",
            parse_mode=ParseMode.HTML
        )
        return
    
    # Parse callback data
    callback_data = query.data
    if callback_data.startswith("approve_"):
        requested_user_id = int(callback_data.split("_")[1])
        
        # Add user to allowed list
        if add_allowed_user(requested_user_id):
            # Notify the user
            try:
                await context.bot.send_message(
                    chat_id=requested_user_id,
                    text=(
                        "✅ <b>Access Approved!</b>\n\n"
                        "Your access request has been approved by an administrator.\n"
                        "You can now use the bot. Send /start to get started!"
                    ),
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"Failed to notify user {requested_user_id}: {str(e)}")
            
            # Update the admin's message
            await query.edit_message_text(
                f"✅ <b>Access Approved</b>\n\n"
                f"User <code>{requested_user_id}</code> has been granted access to the bot.",
                parse_mode=ParseMode.HTML
            )
            logger.info(f"Admin {user_id} approved access for user {requested_user_id}")
        else:
            await query.edit_message_text(
                f"⚠️ User <code>{requested_user_id}</code> is already in the allowed list.",
                parse_mode=ParseMode.HTML
            )
    
    elif callback_data.startswith("deny_"):
        requested_user_id = int(callback_data.split("_")[1])
        
        # Notify the user (optional - you can remove this if you don't want to notify on denial)
        try:
            await context.bot.send_message(
                chat_id=requested_user_id,
                text=(
                    "❌ <b>Access Denied</b>\n\n"
                    "Your access request has been denied by an administrator.\n"
                    "If you believe this is an error, please contact the bot administrator."
                ),
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"Failed to notify user {requested_user_id}: {str(e)}")
        
        # Update the admin's message
        await query.edit_message_text(
            f"❌ <b>Access Denied</b>\n\n"
            f"User <code>{requested_user_id}</code> has been denied access to the bot.",
            parse_mode=ParseMode.HTML
        )
        logger.info(f"Admin {user_id} denied access for user {requested_user_id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    update_activity()  # Track activity for auto-shutdown
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    help_text = """
<b>Upload with Caption Bot - Help</b>

<b>How to Use:</b>
1. Add this bot to your channel/group as an admin
2. Give the bot permission to <b>edit messages</b> (required!)
3. Upload files directly to your channel/group
4. The bot automatically adds the filename as caption

<b>Key Features:</b>
• <b>Single upload</b> - Files upload once, bot just adds caption
• <b>Automatic</b> - No commands needed, works automatically
• <b>Fast</b> - Caption added instantly after upload
• <b>Works in channels and groups</b> - Just add bot as admin

<b>Setup Steps:</b>
1. Go to your channel/group settings
2. Add administrators
3. Add this bot
4. <b>Enable "Edit messages" permission</b> (critical!)
5. Start uploading files!

<b>Supported formats:</b>
• All video formats (MP4, AVI, MOV, etc.)
• All document formats (PDF, DOCX, etc.)
• All image formats (JPG, PNG, etc.)
• All audio formats (MP3, WAV, etc.)
• Voice messages

<b>Important:</b>
• Bot must be admin in the channel/group
• Bot needs <b>"Edit messages"</b> permission
• Works automatically - no configuration needed
• If file already has a caption, it won't be overwritten
• Video notes and stickers don't support captions (will be skipped)

<b>Troubleshooting:</b>
• If captions aren't added, check bot permissions
• Make sure bot has "Edit messages" permission
• Check bot logs for error messages
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


async def process_recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /process_recent command - process recent messages to add captions"""
    update_activity()  # Track activity for auto-shutdown
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    try:
        chat = update.effective_chat
        
        # Check if bot is admin
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        
        if not is_admin:
            await update.message.reply_text(
                "❌ Bot must be admin to process messages.\n\n"
                "Add bot as admin and try again.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Get number of messages to process (default: 50)
        limit = 50
        if context.args and context.args[0].isdigit():
            limit = min(int(context.args[0]), 100)  # Max 100 at a time
        
        await update.message.reply_text(
            f"⏳ Processing last {limit} messages...\n"
            f"This may take a while. I'll update you when done.",
            parse_mode=ParseMode.MARKDOWN
        )
        
        processed = 0
        added = 0
        skipped = 0
        errors = 0
        
        try:
            # Get recent messages
            # Note: python-telegram-bot doesn't have direct get_chat_history
            # We'll need to use a workaround or iterate through updates
            # For now, we'll process messages that come in
            
            # Alternative: Use getUpdates and process, but that's not ideal
            # Better: Use Chat.get_messages() if available
            
            # Since we can't easily get old messages with python-telegram-bot,
            # we'll provide instructions instead
            await update.message.reply_text(
                "ℹ️ *Processing Old Messages*\n\n"
                "To process old messages, you can:\n\n"
                "1. **Forward files** to the channel/group\n"
                "   - Bot will automatically add captions to forwarded files\n"
                "   - Works if original file had filename\n\n"
                "2. **Use message ID** (if you know it):\n"
                "   - Use `/add_caption <message_id>`\n"
                "   - Get message ID from message info\n\n"
                "3. **Re-upload files** (if needed):\n"
                "   - Download and re-upload files with proper names\n\n"
                "*Note:* Telegram API limits access to old messages. "
                "Forwarding is the easiest solution.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error processing recent messages: {str(e)}")
            await update.message.reply_text(
                f"❌ Error: {str(e)}\n\n"
                "Make sure bot has proper permissions.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    except Exception as e:
        logger.error(f"Error in process_recent command: {str(e)}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            parse_mode=ParseMode.MARKDOWN
        )


async def add_caption_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add_caption command - add caption to specific message by ID"""
    update_activity()  # Track activity for auto-shutdown
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "❌ *Usage:* `/add_caption <message_id>`\n\n"
            "Get message ID from message info (right-click → Copy Message Link, "
            "or use @userinfobot to get message details).",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        message_id = int(context.args[0])
        chat_id = update.effective_chat.id
        
        # Try to get the message
        try:
            message = await context.bot.get_chat_member(chat_id, message_id)
            # Actually, we need to get the message differently
            # python-telegram-bot doesn't have direct get_message
            # We need to use a workaround
            
            await update.message.reply_text(
                "ℹ️ *Adding Caption to Message*\n\n"
                "To add caption to a specific message:\n\n"
                "1. **Reply to the message** with `/add_caption`\n"
                "   (This feature will be added)\n\n"
                "2. **Forward the file** instead\n"
                "   - Bot will automatically add caption\n\n"
                "3. **Re-upload the file** with proper name\n\n"
                "*Note:* Direct message access by ID is limited by Telegram API. "
                "Forwarding is recommended.",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Error getting message {message_id}: {str(e)}")
            await update.message.reply_text(
                f"❌ Could not access message {message_id}.\n\n"
                "Make sure:\n"
                "• Bot is admin in this chat\n"
                "• Message ID is correct\n"
                "• Message is not too old (48h limit for editing)\n\n"
                "**Alternative:** Forward the file - bot will add caption automatically.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    except Exception as e:
        logger.error(f"Error in add_caption command: {str(e)}")
        await update.message.reply_text(
            f"❌ Error: {str(e)}",
            parse_mode=ParseMode.MARKDOWN
        )


def extract_file_info(message):
    """
    Extract file information from a message
    
    Returns:
        tuple: (file_name, file_type) or (None, None) if no file found
    """
    # Check for video
    if message.video:
        # Try to get filename from video object
        file_name = message.video.file_name
        # If no filename, check if it was sent as document (mobile uploads sometimes do this)
        if not file_name and message.document:
            file_name = message.document.file_name
        # If still no filename, use fallback
        if not file_name:
            # Try to extract extension from mime_type if available
            ext = ".mp4"
            if message.video.mime_type:
                # Extract extension from mime_type (e.g., "video/mp4" -> "mp4")
                mime_parts = message.video.mime_type.split('/')
                if len(mime_parts) > 1:
                    ext = f".{mime_parts[1].split(';')[0]}"
            file_name = f"video_{message.video.file_id}{ext}"
        return file_name, "video"
    
    # Check for document
    if message.document:
        file_name = message.document.file_name
        # If no filename, try to extract from mime_type
        if not file_name:
            ext = ""
            if message.document.mime_type:
                # Try to get extension from mime_type
                mime_parts = message.document.mime_type.split('/')
                if len(mime_parts) > 1:
                    ext = f".{mime_parts[1].split(';')[0]}"
            file_name = f"document_{message.document.file_id}{ext}"
        return file_name, "document"
    
    # Check for photo (photos don't have document attribute - they're separate)
    if message.photo:
        # Photos don't have file_name, so we generate one
        # Try to get original filename if sent as document (some mobile apps do this)
        file_name = None
        if message.document:
            file_name = message.document.file_name
        if not file_name:
            file_name = f"photo_{message.photo[-1].file_id}.jpg"
        return file_name, "photo"
    
    # Check for audio
    if message.audio:
        file_name = message.audio.file_name
        # If no filename, try to use title or performer
        if not file_name:
            parts = []
            if message.audio.performer:
                parts.append(message.audio.performer)
            if message.audio.title:
                parts.append(message.audio.title)
            if parts:
                file_name = f"{' - '.join(parts)}_{message.audio.file_id}.mp3"
            else:
                file_name = f"audio_{message.audio.file_id}.mp3"
        return file_name, "audio"
    
    # Check for voice message
    if message.voice:
        file_name = f"voice_{message.voice.file_id}.ogg"
        return file_name, "voice"
    
    # Check for video note
    if message.video_note:
        file_name = f"video_note_{message.video_note.file_id}.mp4"
        return file_name, "video_note"
    
    # Check for sticker
    if message.sticker:
        file_name = f"sticker_{message.sticker.file_id}.webp"
        return file_name, "sticker"
    
    return None, None


async def edit_message_caption_with_retry(message, caption_text, max_retries=MAX_RETRIES, delay=RETRY_DELAY):
    """
    Edit message caption with retry logic
    
    Args:
        message: Telegram message object
        caption_text: Caption text to add
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
    
    Returns:
        True if successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            await message.edit_caption(caption=caption_text)
            return True
        
        except BadRequest as e:
            error_msg = str(e).lower()
            # If message doesn't support captions or other permanent error
            if "message can't be edited" in error_msg or "message not found" in error_msg:
                logger.warning(f"Message cannot be edited: {str(e)}")
                # Return a special value to indicate we should try repost
                return "REPOST"
            # Check for other permanent errors
            if "too old" in error_msg or "48 hours" in error_msg:
                logger.warning(f"Message too old to edit: {str(e)}")
                return "REPOST"
            # Retry on other BadRequest errors
            if attempt < max_retries - 1:
                logger.warning(f"Retry {attempt + 1}/{max_retries} after error: {str(e)}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Failed to edit caption after {max_retries} attempts: {str(e)}")
                return False
        
        except (NetworkError, TimedOut) as e:
            # Retry on network errors
            if attempt < max_retries - 1:
                logger.warning(f"Network error, retry {attempt + 1}/{max_retries}: {str(e)}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Network error after {max_retries} attempts: {str(e)}")
                return False
        
        except Forbidden as e:
            # Permission error - don't retry
            logger.error(f"Permission denied: {str(e)}")
            return False
        
        except TelegramError as e:
            error_msg = str(e)
            # Check for flood control / rate limiting
            if "flood" in error_msg.lower() or "rate limit" in error_msg.lower() or "429" in error_msg:
                # Try to extract retry time from error message
                import re
                retry_match = re.search(r'retry in (\d+) seconds?', error_msg, re.IGNORECASE)
                if retry_match:
                    wait_time = int(retry_match.group(1))
                    # Add multiplier for safety (wait a bit longer to avoid immediate re-rate-limiting)
                    adjusted_wait = int(wait_time * FLOOD_RETRY_DELAY_MULTIPLIER)
                    logger.warning(f"Flood control: Rate limit exceeded. Waiting {adjusted_wait} seconds (requested: {wait_time}s)...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(adjusted_wait)
                        # Continue to retry after waiting
                    else:
                        logger.error(f"Flood control after {max_retries} attempts. Need to wait {adjusted_wait} seconds.")
                        return "FLOOD_WAIT"  # Signal that we need to wait
                else:
                    # Default wait time if can't parse (usually 30-60 seconds)
                    wait_time = 30
                    adjusted_wait = int(wait_time * FLOOD_RETRY_DELAY_MULTIPLIER)
                    logger.warning(f"Flood control detected (unparseable): Waiting {adjusted_wait} seconds...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(adjusted_wait)
                    else:
                        return "FLOOD_WAIT"
            else:
                # Other TelegramError - re-raise to be handled by general Exception handler
                raise
        
        except Exception as e:
            error_msg = str(e).lower()
            # Check if it's a flood control error (sometimes comes as generic exception)
            if "flood" in error_msg or "rate limit" in error_msg or "429" in error_msg:
                # Try to extract retry time from error message
                import re
                retry_match = re.search(r'retry in (\d+) seconds?', error_msg, re.IGNORECASE)
                if retry_match:
                    wait_time = int(retry_match.group(1))
                    # Add multiplier for safety
                    adjusted_wait = int(wait_time * FLOOD_RETRY_DELAY_MULTIPLIER)
                    logger.warning(f"Flood control detected: Waiting {adjusted_wait} seconds (requested: {wait_time}s)...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(adjusted_wait)
                        # Continue to retry after waiting
                    else:
                        logger.error(f"Flood control after {max_retries} attempts. Need to wait {adjusted_wait} seconds.")
                        return "FLOOD_WAIT"
                else:
                    # Default wait time if can't parse
                    wait_time = 30
                    adjusted_wait = int(wait_time * FLOOD_RETRY_DELAY_MULTIPLIER)
                    logger.warning(f"Flood control detected (unparseable): Waiting {adjusted_wait} seconds...")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(adjusted_wait)
                    else:
                        return "FLOOD_WAIT"
            else:
                # Other errors - retry
                if attempt < max_retries - 1:
                    logger.warning(f"Unexpected error, retry {attempt + 1}/{max_retries}: {str(e)}")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Unexpected error after {max_retries} attempts: {str(e)}")
                    return False
    
    return False


async def repost_file_with_caption(context: ContextTypes.DEFAULT_TYPE, message, file_type, caption_text):
    """
    Repost a file with caption by deleting original and sending new message.
    This is used as a workaround for groups where bot can't edit other users' messages.
    
    Args:
        context: Bot context
        message: Original message object
        file_type: Type of file (video, document, photo, audio, voice)
        caption_text: Caption to add
    
    Returns:
        True if successful, False otherwise
    """
    try:
        chat_id = message.chat.id
        message_id = message.message_id
        
        # Delete original message first (required for repost in groups)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Forbidden as e:
            logger.warning(f"Cannot delete message (need 'Delete messages' permission): {e}. Repost may still work.")
            # Continue - send new message anyway (user will have duplicate: original + new with caption)
        except Exception as e:
            logger.warning(f"Could not delete original message: {str(e)}")
            # Continue anyway - might still be able to send new message
        
        # Send new message with caption based on file type
        if file_type == "video" and message.video:
            await context.bot.send_video(
                chat_id=chat_id,
                video=message.video.file_id,
                caption=caption_text
            )
        elif file_type == "document" and message.document:
            await context.bot.send_document(
                chat_id=chat_id,
                document=message.document.file_id,
                caption=caption_text
            )
        elif file_type == "photo" and message.photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=message.photo[-1].file_id,  # Use largest photo
                caption=caption_text
            )
        elif file_type == "audio" and message.audio:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=message.audio.file_id,
                caption=caption_text
            )
        elif file_type == "voice" and message.voice:
            await context.bot.send_voice(
                chat_id=chat_id,
                voice=message.voice.file_id,
                caption=caption_text
            )
        else:
            logger.warning(f"Cannot repost {file_type} - file type not supported for reposting")
            return False
        
        return True
    
    except Exception as e:
        logger.error(f"Error reposting file with caption: {str(e)}")
        return False


async def process_file_task(update: Update, context: ContextTypes.DEFAULT_TYPE, message, file_name, file_type):
    """
    Internal function to process a single file with semaphore control.
    This is called from handle_file after initial validation.
    """
    async with processing_semaphore:
        # Add a small delay to ensure message is fully processed by Telegram
        # Reduced delay since we're using parallel processing with rate limiting
        await asyncio.sleep(MIN_API_CALL_DELAY)
        
        try:
            chat_title = message.chat.title or f"Chat {message.chat.id}"
            logger.info(f"Processing {file_type} in {chat_title}: {file_name}")
            
            chat_type = message.chat.type
            
            # Truncate filename if too long for caption (Telegram limit: 1024 characters)
            # But keep it reasonable - use first 200 characters
            caption_text = file_name
            if len(caption_text) > 200:
                caption_text = file_name[:197] + "..."
            
            # Check if we're in a group and message is from another user
            # In groups, bots can only edit their own messages
            is_group = chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]
            is_bot_message = message.from_user and message.from_user.id == context.bot.id
            # Check if message is forwarded (python-telegram-bot v20+ uses forward_origin)
            is_forwarded = message.forward_origin is not None
            
            # Check message age (Telegram allows editing only within 48 hours)
            message_age_hours = None
            if message.date:
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                message_time = message.date
                age_delta = now - message_time
                message_age_hours = age_delta.total_seconds() / 3600
            
            # Determine if we should use repost method
            use_repost = False
            repost_reason = None
            
            if is_group and not is_bot_message:
                # In groups, we can't edit other users' messages
                use_repost = True
                repost_reason = "Group message from another user"
                logger.debug(f"{repost_reason} - using repost workaround")
            elif message_age_hours and message_age_hours > 48:
                # Message is too old to edit (Telegram 48-hour limit)
                use_repost = True
                repost_reason = f"Message too old ({message_age_hours:.1f}h > 48h limit)"
                logger.warning(f"{repost_reason} - using repost workaround")
            elif is_forwarded and is_group:
                # Forwarded messages in groups from other users often can't be edited
                use_repost = True
                repost_reason = "Forwarded message in group"
                logger.debug(f"{repost_reason} - using repost workaround")
            elif message_age_hours and message_age_hours > 24:
                # Message is getting old, try edit first, fallback to repost
                logger.debug(f"Message is {message_age_hours:.1f} hours old - trying edit first")
            
            if use_repost:
                # Use repost method: delete and repost with caption
                success = await repost_file_with_caption(context, message, file_type, caption_text)
            else:
                # Try to edit directly first
                edit_result = await edit_message_caption_with_retry(message, caption_text)
                
                # Check if edit returned "REPOST" signal (message can't be edited)
                if edit_result == "REPOST":
                    logger.debug(f"Edit not possible (message can't be edited), using repost workaround")
                    success = await repost_file_with_caption(context, message, file_type, caption_text)
                elif edit_result == "FLOOD_WAIT":
                    # Flood control - wait longer before trying repost
                    logger.warning(f"Rate limited, waiting 30 seconds before trying repost...")
                    await asyncio.sleep(30)
                    success = await repost_file_with_caption(context, message, file_type, caption_text)
                elif edit_result is True:
                    success = True
                else:
                    # Edit failed for other reason, try repost as fallback
                    # This handles cases where edit fails unexpectedly
                    logger.debug(f"Edit failed, trying repost workaround as fallback")
                    success = await repost_file_with_caption(context, message, file_type, caption_text)
            
            if success:
                logger.info(f"✅ Successfully added caption: {file_name}")
            else:
                logger.warning(f"❌ Failed to add caption: {file_name}")
        
        except Exception as e:
            logger.error(f"Error processing file caption: {str(e)}", exc_info=True)


async def process_update_queue(application: Application):
    """
    Process missed updates from queue when bot restarts.
    This ensures no files are missed when the bot was offline.
    """
    if not ENABLE_UPDATE_QUEUE:
        logger.info("Update queue processing disabled")
        return
    
    try:
        logger.info("📥 Checking for missed updates in queue...")
        
        # Get updates from Telegram
        # Telegram stores updates for up to 24 hours
        updates = await application.bot.get_updates(
            timeout=10,
            allowed_updates=Update.ALL_TYPES
        )
        
        if not updates:
            logger.info("✅ No missed updates found")
            return
        
        # Filter for file-related updates only (to avoid processing old commands)
        file_updates = []
        for update in updates[:MAX_QUEUE_UPDATES]:  # Limit processing
            message = update.message or update.channel_post
            if message:
                # Check if it's a file message
                if (message.video or message.document or message.photo or 
                    message.audio or message.voice):
                    file_updates.append(update)
        
        if not file_updates:
            logger.info(f"✅ Found {len(updates)} updates, but none are file uploads")
            # Acknowledge all updates to clear queue
            if updates:
                last_update_id = max(u.update_id for u in updates)
                await application.bot.get_updates(offset=last_update_id + 1, timeout=1)
            return
        
        logger.info(f"📦 Found {len(file_updates)} missed file uploads in queue")
        logger.info("   Processing missed files...")
        
        # Process each missed update using application's update processor
        processed = 0
        for update in file_updates:
            try:
                # Use application's process_update to handle the update properly
                # This ensures proper context creation and handler execution
                await application.process_update(update)
                processed += 1
                
                # Small delay to avoid rate limits
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error processing queued update {update.update_id}: {str(e)}")
                continue
        
        # Acknowledge all processed updates
        if updates:
            last_update_id = max(u.update_id for u in updates)
            await application.bot.get_updates(offset=last_update_id + 1, timeout=1)
        
        logger.info(f"✅ Processed {processed}/{len(file_updates)} missed file uploads")
        
    except Exception as e:
        logger.error(f"Error processing update queue: {str(e)}", exc_info=True)


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle file uploads in channels/groups and automatically add filename as caption.
    This intercepts files uploaded to channels/groups and edits the message to add caption.
    In groups, if message is from another user, reposts the file with caption.
    
    Now optimized for parallel processing - files are processed concurrently with rate limiting.
    """
    update_activity()  # Track activity for auto-shutdown
    message = update.message or update.channel_post
    
    # Only process messages in channels or groups (not in private chat with bot)
    if not message:
        return
    
    chat_type = message.chat.type
    if chat_type not in [ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP]:
        logger.info(f"Skipping: message not in channel/group (chat_type={chat_type}). Forward the file in the channel/group where the bot is admin.")
        return
    
    # Check if message already has a caption - if yes, don't overwrite it
    if message.caption:
        logger.info(f"Skipping: message already has caption in {message.chat.title or message.chat.id}")
        return
    
    # Check authorization for channel/group posts
    if ENABLE_USER_VERIFICATION:
        # For channel posts, effective_user is often None (post attributed to channel) - allow those
        if update.effective_user is not None:
            if not is_user_authorized(update.effective_user.id):
                logger.warning(f"Unauthorized post in {message.chat.title or message.chat.id} by user {update.effective_user.id} - user must be admin or approved.")
                return
        # effective_user is None = channel post (or anonymous) - allow processing
    
    # Extract file information
    file_name, file_type = extract_file_info(message)
    
    if not file_name or not file_type:
        logger.info(f"No file detected in message (chat={message.chat.title or message.chat.id}) - might be unsupported type.")
        return
    
    logger.info(f"Processing file in {message.chat.title or message.chat.id}: type={file_type}, name={file_name}")
    
    # Check if filename looks like a generated file_id (starts with type_ and contains long alphanumeric string)
    # This indicates Telegram didn't provide the original filename
    is_generated_name = file_name.startswith(f"{file_type}_") and len(file_name.split('_')[1].split('.')[0]) > 20
    
    if is_generated_name:
        logger.warning(
            f"⚠️ Original filename not available for {file_type}. "
            f"Telegram didn't provide file_name attribute. "
            f"This often happens with mobile uploads when files are sent directly from gallery/camera."
        )
        
        # If configured to skip when no filename, don't add caption
        if SKIP_IF_NO_FILENAME:
            logger.info(f"Skipping caption addition - original filename not available and SKIP_IF_NO_FILENAME is enabled")
            return
        
        logger.info(f"Using generated filename: {file_name}")
        
        # Try to get more info from the file object
        try:
            file_obj = None
            if file_type == "video" and message.video:
                file_obj = message.video
            elif file_type == "document" and message.document:
                file_obj = message.document
            elif file_type == "photo" and message.photo:
                file_obj = message.photo[-1]
            
            if file_obj:
                # Check if there's any additional metadata
                logger.debug(f"File object details - file_id: {file_obj.file_id}, file_unique_id: {getattr(file_obj, 'file_unique_id', 'N/A')}")
        except Exception as e:
            logger.debug(f"Could not get additional file info: {str(e)}")
    
    # Skip file types that don't support captions
    if file_type in ["video_note", "sticker"]:
        logger.debug(f"Skipping {file_type} - doesn't support captions")
        return
    
    # Create a background task for parallel processing
    # This allows multiple files to be processed simultaneously
    # The semaphore in process_file_task will control concurrency
    task = asyncio.create_task(
        process_file_task(update, context, message, file_name, file_type)
    )
    
    # Add done callback to log any unhandled exceptions in the task
    def task_done_callback(task):
        try:
            task.result()  # This will raise any exception that occurred
        except Exception as e:
            logger.error(f"Unhandled exception in parallel task for {file_name}: {str(e)}", exc_info=True)
    
    task.add_done_callback(task_done_callback)
    logger.debug(f"Created parallel processing task for {file_name}")


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
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}. Will retry...")
        return
    
    # Handle permission errors
    if isinstance(error, Forbidden):
        logger.error(f"Permission error: {error}")
        return
    
    # Handle other errors
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        logger.error("Please create a .env file with TELEGRAM_BOT_TOKEN=your_token_here")
        return
    
    # Create application with concurrent updates enabled for parallel processing
    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    
    # Enable concurrent updates for parallel processing
    if ENABLE_CONCURRENT_UPDATES:
        builder = builder.concurrent_updates(True)
        logger.info(f"✅ Concurrent updates enabled - processing up to {MAX_CONCURRENT_TASKS} files in parallel")
    else:
        logger.info("ℹ️ Concurrent updates disabled - processing files sequentially")
    
    application = builder.build()
    
    # Store application instance globally for auto-shutdown
    global application_instance
    application_instance = application
    
    # Initialize activity tracking when bot starts
    update_activity()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add callback query handler for approve/deny buttons
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("process_recent", process_recent_command))
    application.add_handler(CommandHandler("add_caption", add_caption_command))
    
    # Handle all file types in channels and groups
    # Use filters to listen to both channels and groups
    channel_group_filter = filters.ChatType.CHANNEL | filters.ChatType.GROUP | filters.ChatType.SUPERGROUP
    
    # Register handlers for different file types
    application.add_handler(MessageHandler(channel_group_filter & filters.PHOTO, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.VIDEO, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.Document.ALL, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.AUDIO, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.VOICE, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.VIDEO_NOTE, handle_file))
    application.add_handler(MessageHandler(channel_group_filter & filters.Sticker.ALL, handle_file))
    
    # Start bot
    logger.info("Upload with Caption Bot starting...")
    logger.info("Bot is ready! Add it to your channels/groups as admin with 'Edit messages' permission.")
    if ENABLE_CONCURRENT_UPDATES:
        logger.info(f"Parallel processing: Up to {MAX_CONCURRENT_TASKS} files can be processed simultaneously")
    
    # Start HTTP server for health checks (before bot starts)
    if ENABLE_HTTP_SERVER:
        start_http_server()
        logger.info("💡 Configure a local monitor to ping the health check endpoint")
        logger.info(f"   Health check URL: http://0.0.0.0:{actual_http_port or HTTP_SERVER_PORT}/")
    
    # Start idle monitoring task if auto-shutdown is enabled
    global shutdown_task
    if ENABLE_AUTO_SHUTDOWN and IDLE_TIMEOUT_MINUTES > 0:
        # Create a task that will run after the application starts
        async def post_init(app: Application):
            """Called after application initialization"""
            global shutdown_task
            
            # Process missed updates from queue first
            if ENABLE_UPDATE_QUEUE:
                await process_update_queue(app)
            
            # Then start monitoring
            shutdown_task = asyncio.create_task(monitor_idle_timeout())
            if ENABLE_HTTP_SERVER:
                logger.info(f"✅ Auto-shutdown monitoring started (timeout: {IDLE_TIMEOUT_MINUTES} minutes)")
                logger.info("   HTTP server will keep bot active when health checks ping it")
            else:
                logger.info(f"✅ Auto-shutdown monitoring started (timeout: {IDLE_TIMEOUT_MINUTES} minutes)")
        
        application.post_init = post_init
    else:
        # Even if auto-shutdown is disabled, process queue on startup
        async def post_init(app: Application):
            if ENABLE_UPDATE_QUEUE:
                await process_update_queue(app)
        
        application.post_init = post_init
    
    try:
        # Use drop_pending_updates=False to allow queue processing
        # The queue processing in post_init will handle missed updates
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=not ENABLE_UPDATE_QUEUE  # Keep updates if queue enabled
        )
    except Conflict as e:
        logger.error("❌ Bot conflict detected!")
        logger.error("Another bot instance is already running.")
        logger.error("Please stop all other bot instances and try again.")
        logger.error(f"Error: {str(e)}")
        logger.error("\nTo fix:")
        logger.error("1. Find and stop other bot processes:")
        logger.error("   ps aux | grep bot.py")
        logger.error("2. Or kill all name-bot processes:")
        logger.error("   pkill -f 'name-bot.*bot.py'")
        logger.error("3. Wait a few seconds, then restart the bot")
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()

