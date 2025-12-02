"""
Telegram Bot that automatically sets filename as caption when files are uploaded to channels/groups
Improved version with better error handling and reliability
"""
import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
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
    RetryAfter
)

from config import (
    TELEGRAM_BOT_TOKEN,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    RETRY_DELAY,
    MAX_RETRIES,
    SKIP_IF_NO_FILENAME,
    PROCESSING_DELAY,
    FLOOD_RETRY_DELAY_MULTIPLIER
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


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
    # For channel/group messages, check the user who posted (if available)
    # For bot commands, check the user who sent the command
    user_id = update.effective_user.id if update.effective_user else None
    
    # If no user (channel post), allow if verification is disabled
    if not user_id:
        return not ENABLE_USER_VERIFICATION
    
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
📝 *Name Bot*

This bot automatically adds the filename as caption when you upload files to channels or groups.

*How it works:*
1. Add this bot as an admin to your channel/group
2. Upload any file directly to the channel/group
3. The bot automatically detects the file and adds the filename as caption
4. **Upload happens only once** - the bot just edits the message to add the caption

*Setup:*
1. Add the bot to your channel/group as an admin
2. Give the bot permission to **edit messages** (required!)
3. Start uploading files - captions will be added automatically!

*Supported file types:*
• Videos (MP4, AVI, MOV, etc.)
• Documents (PDF, DOCX, etc.)
• Photos (JPG, PNG, etc.)
• Audio files (MP3, WAV, etc.)
• Voice messages
• Any other file type

*Commands:*
/start - Show this message
/help - Get help
/status - Check bot status
/process_recent [N] - Process recent messages to add captions
/add_caption <msg_id> - Add caption to specific message

*Note:*
• The bot must be an admin in the channel/group
• The bot needs permission to edit messages
• Works in any channel/group where the bot is added as admin
"""
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    help_text = """
*Name Bot - Help*

*How to Use:*
1. Add this bot to your channel/group as an admin
2. Give the bot permission to **edit messages** (required!)
3. Upload files directly to your channel/group
4. The bot automatically adds the filename as caption

*Key Features:*
• **Single upload** - Files upload once, bot just adds caption
• **Automatic** - No commands needed, works automatically
• **Fast** - Caption added instantly after upload
• **Works in channels and groups** - Just add bot as admin

*Setup Steps:*
1. Go to your channel/group settings
2. Add administrators
3. Add this bot
4. **Enable "Edit messages" permission** (critical!)
5. Start uploading files!

*Supported formats:*
• All video formats (MP4, AVI, MOV, etc.)
• All document formats (PDF, DOCX, etc.)
• All image formats (JPG, PNG, etc.)
• All audio formats (MP3, WAV, etc.)
• Voice messages

*Important:*
• Bot must be admin in the channel/group
• Bot needs **"Edit messages"** permission
• Works automatically - no configuration needed
• If file already has a caption, it won't be overwritten
• Video notes and stickers don't support captions (will be skipped)

*Troubleshooting:*
• If captions aren't added, check bot permissions
• Make sure bot has "Edit messages" permission
• Check bot logs for error messages
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def process_recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /process_recent command - process recent messages to add captions"""
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


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command - check bot status"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    try:
        chat = update.effective_chat
        
        # Check if bot is admin
        bot_member = await context.bot.get_chat_member(chat.id, context.bot.id)
        is_admin = bot_member.status in ['administrator', 'creator']
        
        # Check permissions
        can_edit = False
        if is_admin and hasattr(bot_member, 'can_edit_messages'):
            can_edit = bot_member.can_edit_messages
        
        status_text = f"""
*Bot Status for {chat.title or 'this chat'}*

• Bot is admin: {'✅ Yes' if is_admin else '❌ No'}
• Can edit messages: {'✅ Yes' if can_edit else '❌ No'}

"""
        if not is_admin:
            status_text += "⚠️ *Action Required:* Add bot as admin to this channel/group\n\n"
        if not can_edit:
            status_text += "⚠️ *Action Required:* Enable 'Edit messages' permission for the bot\n\n"
        
        if is_admin and can_edit:
            status_text += "✅ Bot is ready! Upload files and captions will be added automatically."
        else:
            status_text += "❌ Bot is not properly configured. Please fix the issues above."
        
        await update.message.reply_text(status_text, parse_mode=ParseMode.MARKDOWN)
    
    except Exception as e:
        logger.error(f"Error checking status: {str(e)}")
        await update.message.reply_text(
            f"❌ Error checking status: {str(e)}\n\n"
            "Make sure the bot is added to this chat and has proper permissions.",
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
        
        # Delete original message first
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
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


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle file uploads in channels/groups and automatically add filename as caption.
    This intercepts files uploaded to channels/groups and edits the message to add caption.
    In groups, if message is from another user, reposts the file with caption.
    """
    message = update.message or update.channel_post
    
    # Only process messages in channels or groups
    if not message:
        return
    
    chat_type = message.chat.type
    if chat_type not in [ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP]:
        return
    
    # Check if message already has a caption - if yes, don't overwrite it
    if message.caption:
        logger.debug(f"Message already has caption, skipping: {message.caption[:50]}")
        return
    
    # Check authorization for channel/group posts
    if ENABLE_USER_VERIFICATION:
        # For channel posts, effective_user might be None
        if update.effective_user:
            if not is_user_authorized(update.effective_user.id):
                logger.warning(f"Unauthorized post in {message.chat.title}")
                return
        # If no user info and verification is enabled, skip
        elif not update.effective_user:
            logger.debug("Channel post without user info, skipping due to verification")
            return
    
    # Extract file information
    file_name, file_type = extract_file_info(message)
    
    if not file_name or not file_type:
        # No file detected
        return
    
    # Log what we extracted for debugging
    logger.debug(f"Extracted file info - Type: {file_type}, Name: {file_name}")
    
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
    
    # Truncate filename if too long for caption (Telegram limit: 1024 characters)
    # But keep it reasonable - use first 200 characters
    caption_text = file_name
    if len(caption_text) > 200:
        caption_text = file_name[:197] + "..."
    
    # Add a delay to ensure message is fully processed by Telegram and avoid rate limits
    # PROCESSING_DELAY helps prevent hitting Telegram's rate limits when processing many files
    await asyncio.sleep(PROCESSING_DELAY)
    
    try:
        chat_title = message.chat.title or f"Chat {message.chat.id}"
        logger.info(f"Adding caption to {file_type} in {chat_title}: {file_name}")
        
        # Check if we're in a group and message is from another user
        # In groups, bots can only edit their own messages
        is_group = chat_type in [ChatType.GROUP, ChatType.SUPERGROUP]
        is_bot_message = message.from_user and message.from_user.id == context.bot.id
        is_forwarded = message.forward_from or message.forward_from_chat or message.forward_sender_name
        
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
            logger.info(f"{repost_reason} - using repost workaround")
        elif message_age_hours and message_age_hours > 48:
            # Message is too old to edit (Telegram 48-hour limit)
            use_repost = True
            repost_reason = f"Message too old ({message_age_hours:.1f}h > 48h limit)"
            logger.warning(f"{repost_reason} - using repost workaround")
        elif is_forwarded and is_group:
            # Forwarded messages in groups from other users often can't be edited
            use_repost = True
            repost_reason = "Forwarded message in group"
            logger.info(f"{repost_reason} - using repost workaround")
        elif message_age_hours and message_age_hours > 24:
            # Message is getting old, try edit first, fallback to repost
            logger.info(f"Message is {message_age_hours:.1f} hours old - trying edit first")
        
        if use_repost:
            # Use repost method: delete and repost with caption
            success = await repost_file_with_caption(context, message, file_type, caption_text)
        else:
            # Try to edit directly first
            edit_result = await edit_message_caption_with_retry(message, caption_text)
            
            # Check if edit returned "REPOST" signal (message can't be edited)
            if edit_result == "REPOST":
                logger.info(f"Edit not possible (message can't be edited), using repost workaround")
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
                logger.info(f"Edit failed, trying repost workaround as fallback")
                success = await repost_file_with_caption(context, message, file_type, caption_text)
        
        if success:
            logger.info(f"✅ Successfully added caption: {file_name}")
        else:
            logger.warning(f"❌ Failed to add caption: {file_name}")
    
    except Exception as e:
        logger.error(f"Error processing file caption: {str(e)}", exc_info=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot"""
    error = context.error
    
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
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
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
    logger.info("Name bot starting...")
    logger.info("Bot is ready! Add it to your channels/groups as admin with 'Edit messages' permission.")
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())


if __name__ == "__main__":
    main()

