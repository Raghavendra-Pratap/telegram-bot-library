"""
Telegram Bot that automatically sets filename as caption when files are uploaded
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
    ALLOWED_USER_IDS
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
        except Exception as e:
            logger.error(f"Error sending authorization message: {str(e)}")
        
        return False
    
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    # Get current channel setting
    current_channel = context.user_data.get('channel', None)
    channel_text = f"📺 Current channel: `{current_channel}`" if current_channel else "📺 No channel set (files will be sent back to you)"
    
    welcome_message = f"""
📝 *Caption Bot*

This bot automatically sets the filename as the caption when you upload files.

*How it works:*
1. Upload any file (video, document, photo, audio, etc.)
2. The bot will automatically fetch the filename
3. The file will be uploaded to your channel (or sent back to you) with the filename as the caption

{channel_text}

*Supported file types:*
• Videos (MP4, AVI, MOV, etc.)
• Documents (PDF, DOCX, etc.)
• Photos (JPG, PNG, etc.)
• Audio files (MP3, WAV, etc.)
• Any other file type

*Commands:*
/start - Show this message
/help - Get help
/setchannel - Set channel for uploads
/channel - Show current channel
/removechannel - Remove channel (send files back to you)
"""
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    help_text = """
*Caption Bot - Help*

*Usage:*
1. Set a channel using `/setchannel @your_channel` or `/setchannel -1001234567890`
2. Upload any file to this bot
3. The bot will automatically:
   • Extract the filename
   • Upload to your channel (or send back to you) with the filename as the caption

*Channel Commands:*
• `/setchannel @channel_name` - Set channel by username
• `/setchannel -1001234567890` - Set channel by ID
• `/channel` - Show current channel
• `/removechannel` - Remove channel (files will be sent back to you)

*Supported formats:*
• All video formats
• All document formats
• All image formats
• All audio formats
• Any other file type

*Note:*
• The bot must be an admin in the channel
• Channel username should start with @
• Channel ID is usually a negative number like -1001234567890
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def get_chat_id(channel_spec: str, default_chat_id: int = None):
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


async def setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setchannel command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    if not context.args or len(context.args) == 0:
        await message.reply_text(
            "❌ *Usage:* `/setchannel @channel_name` or `/setchannel -1001234567890`\n\n"
            "Examples:\n"
            "• `/setchannel @my_channel`\n"
            "• `/setchannel -1001234567890`\n\n"
            "The bot must be an admin in the channel.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    channel_spec = context.args[0]
    chat_id = get_chat_id(channel_spec)
    
    # Try to verify the channel exists and bot has access
    try:
        chat = await context.bot.get_chat(chat_id)
        # Store channel in user_data
        context.user_data['channel'] = channel_spec
        
        await message.reply_text(
            f"✅ Channel set successfully!\n\n"
            f"📺 Channel: `{channel_spec}`\n"
            f"📝 Title: {chat.title}\n\n"
            f"All uploaded files will now be sent to this channel with filename as caption.",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error setting channel: {str(e)}")
        await message.reply_text(
            f"❌ Error setting channel: {str(e)}\n\n"
            f"Make sure:\n"
            f"• The channel exists\n"
            f"• The bot is an admin in the channel\n"
            f"• You're using the correct format (@channel or -1001234567890)",
            parse_mode=ParseMode.MARKDOWN
        )


async def channel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /channel command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    current_channel = context.user_data.get('channel', None)
    
    if current_channel:
        try:
            chat_id = get_chat_id(current_channel)
            chat = await context.bot.get_chat(chat_id)
            await message.reply_text(
                f"📺 *Current Channel*\n\n"
                f"Channel: `{current_channel}`\n"
                f"Title: {chat.title}\n\n"
                f"All files will be uploaded to this channel.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await message.reply_text(
                f"⚠️ Channel set but cannot be accessed: {str(e)}\n\n"
                f"Channel: `{current_channel}`\n\n"
                f"Use `/setchannel` to set a new channel.",
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        await message.reply_text(
            "📺 *No channel set*\n\n"
            "Files will be sent back to you.\n\n"
            "Use `/setchannel @channel_name` to set a channel.",
            parse_mode=ParseMode.MARKDOWN
        )


async def removechannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removechannel command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    if 'channel' in context.user_data:
        removed_channel = context.user_data.pop('channel')
        await message.reply_text(
            f"✅ Channel removed!\n\n"
            f"Removed: `{removed_channel}`\n\n"
            f"Files will now be sent back to you instead of the channel.",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await message.reply_text(
            "ℹ️ No channel was set.\n\n"
            "Files are already being sent back to you.",
            parse_mode=ParseMode.MARKDOWN
        )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads and set filename as caption"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Determine file type and get file object
    file_obj = None
    file_name = None
    file_type = None
    
    # Check for video
    if message.video:
        file_obj = message.video
        file_name = message.video.file_name or f"video_{message.video.file_id}.mp4"
        file_type = "video"
    # Check for document
    elif message.document:
        file_obj = message.document
        file_name = message.document.file_name or f"document_{message.document.file_id}"
        file_type = "document"
    # Check for photo (largest one)
    elif message.photo:
        file_obj = message.photo[-1]  # Get largest photo
        file_name = f"photo_{file_obj.file_id}.jpg"
        file_type = "photo"
    # Check for audio
    elif message.audio:
        file_obj = message.audio
        file_name = message.audio.file_name or f"audio_{message.audio.file_id}.mp3"
        file_type = "audio"
    # Check for voice message
    elif message.voice:
        file_obj = message.voice
        file_name = f"voice_{message.voice.file_id}.ogg"
        file_type = "voice"
    # Check for video note
    elif message.video_note:
        file_obj = message.video_note
        file_name = f"video_note_{message.video_note.file_id}.mp4"
        file_type = "video_note"
    # Check for sticker
    elif message.sticker:
        file_obj = message.sticker
        file_name = f"sticker_{message.sticker.file_id}.webp"
        file_type = "sticker"
    else:
        await message.reply_text(
            "❌ No file detected in your message.\n\n"
            "Please upload a file (video, document, photo, audio, etc.)"
        )
        return
    
    if not file_obj or not file_name:
        await message.reply_text("❌ Could not extract file information.")
        return
    
    # Truncate filename if too long for caption (Telegram limit: 1024 characters)
    # But keep it reasonable - use first 200 characters
    caption_text = file_name
    if len(caption_text) > 200:
        caption_text = file_name[:197] + "..."
    
    # Send processing message
    status_msg = await message.reply_text(f"⏳ Processing file: `{file_name[:50]}...`" if len(file_name) > 50 else f"⏳ Processing file: `{file_name}`", parse_mode=ParseMode.MARKDOWN)
    
    try:
        # Determine target chat (channel or user)
        target_chat = context.user_data.get('channel', None)
        if target_chat:
            target_chat = get_chat_id(target_chat, message.chat.id)
        else:
            target_chat = message.chat.id
        
        # Use file_id directly - no download/upload needed!
        # Telegram Bot API allows sending files using their file_id
        # This references files already on Telegram's servers
        logger.info(f"Sending file using file_id: {file_name} ({file_type})")
        
        # Send file to target chat with filename as caption
        # Use appropriate method based on file type
        try:
            if file_type == "video":
                await context.bot.send_video(
                    chat_id=target_chat,
                    video=file_obj.file_id,  # Use file_id directly
                    caption=caption_text,
                    supports_streaming=True
                )
            elif file_type == "document":
                await context.bot.send_document(
                    chat_id=target_chat,
                    document=file_obj.file_id,  # Use file_id directly
                    caption=caption_text
                )
            elif file_type == "photo":
                await context.bot.send_photo(
                    chat_id=target_chat,
                    photo=file_obj.file_id,  # Use file_id directly
                    caption=caption_text
                )
            elif file_type == "audio":
                await context.bot.send_audio(
                    chat_id=target_chat,
                    audio=file_obj.file_id,  # Use file_id directly
                    caption=caption_text
                )
            elif file_type == "voice":
                await context.bot.send_voice(
                    chat_id=target_chat,
                    voice=file_obj.file_id,  # Use file_id directly
                    caption=caption_text
                )
            elif file_type == "video_note":
                # Video notes don't support captions, send as video instead
                # Note: video_note file_id might not work with send_video, may need to download
                # For now, try using file_id, fallback to download if needed
                try:
                    await context.bot.send_video(
                        chat_id=target_chat,
                        video=file_obj.file_id,
                        caption=caption_text,
                        supports_streaming=True
                    )
                except Exception:
                    # Fallback: download and send as document if file_id doesn't work
                    file_path = await context.bot.get_file(file_obj.file_id)
                    temp_dir = Path("temp_downloads")
                    temp_dir.mkdir(exist_ok=True)
                    temp_file = temp_dir / f"video_note_{file_obj.file_id}.mp4"
                    await file_path.download_to_drive(temp_file)
                    await context.bot.send_document(
                        chat_id=target_chat,
                        document=temp_file,
                        caption=caption_text
                    )
                    if temp_file.exists():
                        temp_file.unlink()
            elif file_type == "sticker":
                # Stickers can't have captions, send as document instead
                # Sticker file_id might not work with send_document, may need to download
                try:
                    await context.bot.send_document(
                        chat_id=target_chat,
                        document=file_obj.file_id,
                        caption=caption_text
                    )
                except Exception:
                    # Fallback: download and send
                    file_path = await context.bot.get_file(file_obj.file_id)
                    temp_dir = Path("temp_downloads")
                    temp_dir.mkdir(exist_ok=True)
                    temp_file = temp_dir / f"sticker_{file_obj.file_id}.webp"
                    await file_path.download_to_drive(temp_file)
                    await context.bot.send_document(
                        chat_id=target_chat,
                        document=temp_file,
                        caption=caption_text
                    )
                    if temp_file.exists():
                        temp_file.unlink()
            else:
                # Fallback to document
                await context.bot.send_document(
                    chat_id=target_chat,
                    document=file_obj.file_id,  # Use file_id directly
                    caption=caption_text
                )
            
            # Update status message
            display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
            if context.user_data.get('channel'):
                await status_msg.edit_text(
                    f"✅ File uploaded to channel!\n\n📝 Caption: `{display_name}`\n📺 Channel: `{context.user_data.get('channel')}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await status_msg.edit_text(
                    f"✅ File processed successfully!\n\n📝 Caption: `{display_name}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as send_error:
            logger.error(f"Error sending file: {str(send_error)}")
            display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
            error_msg = f"❌ Error sending file: {str(send_error)}\n\n📝 Filename: `{display_name}`"
            if context.user_data.get('channel'):
                error_msg += f"\n📺 Channel: `{context.user_data.get('channel')}`"
            await status_msg.edit_text(error_msg, parse_mode=ParseMode.MARKDOWN)
    
    except NetworkError as e:
        logger.error(f"Network error: {str(e)}")
        display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
        await status_msg.edit_text(
            "❌ Network error occurred. Please try again.\n\n"
            f"📝 Filename: `{display_name}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except TimedOut as e:
        logger.error(f"Timeout error: {str(e)}")
        display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
        await status_msg.edit_text(
            "❌ Request timed out. Please try again.\n\n"
            f"📝 Filename: `{display_name}`",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
        await status_msg.edit_text(
            f"❌ Error processing file: {str(e)}\n\n"
            f"📝 Filename: `{display_name}`",
            parse_mode=ParseMode.MARKDOWN
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors in the bot"""
    error = context.error
    
    # Handle network errors
    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning(f"Network error: {error}. Will retry...")
        return
    
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
    application.add_handler(CommandHandler("setchannel", setchannel_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("removechannel", removechannel_command))
    
    # Handle all file types - use separate handlers to avoid filter mixing issues
    application.add_handler(MessageHandler(filters.PHOTO, handle_file))
    application.add_handler(MessageHandler(filters.VIDEO, handle_file))
    application.add_handler(MessageHandler(filters.Document(), handle_file))
    application.add_handler(MessageHandler(filters.AUDIO, handle_file))
    application.add_handler(MessageHandler(filters.VOICE, handle_file))
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_file))
    application.add_handler(MessageHandler(filters.Sticker(), handle_file))
    
    # Start bot
    logger.info("Caption bot starting...")
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

