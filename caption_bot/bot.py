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
    if not update.effective_user:
        return False
    
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

Upload files directly to your channel with automatic filename captions!

*How it works:*
1. Set your channel using `/setchannel @your_channel`
2. Upload any file to this bot
3. The bot automatically:
   • Extracts the filename
   • Uploads to your channel instantly
   • Adds filename as caption
   • **Single upload** - file is uploaded once, no re-uploading!

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
/setchannel - Set channel for uploads (required)
/channel - Show current channel
/removechannel - Remove channel
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
   • Upload to your channel with the filename as the caption

*Channel Commands:*
• `/setchannel @channel_name` - Add public channel by username
• `/setchannel -1001234567890` - Add private channel by ID
• `/getchannelid` - Get channel ID (forward a message from channel first)
• `/channels` - View all channels and select default
• `/channel` - Show current default channel
• `/removechannel` - Remove a channel

*Private Channels (No Username):*
1. Forward any message from the private channel to this bot
2. Send `/getchannelid` to get the channel ID
3. Use `/setchannel <channel_id>` to add it

*Supported formats:*
• All video formats
• All document formats
• All image formats
• All audio formats
• Any other file type

*Note:*
• The bot must be an admin in the channel
• You can add multiple channels and choose which one to use
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
    """Handle /setchannel command - add channel to list"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    if not context.args or len(context.args) == 0:
        await message.reply_text(
            "❌ *Usage:* `/setchannel @channel_name` or `/setchannel -1001234567890`\n\n"
            "Examples:\n"
            "• `/setchannel @my_channel` (public channel)\n"
            "• `/setchannel -1001234567890` (private channel)\n\n"
            "*For Private Channels (no username):*\n"
            "1. Forward any message from the channel to this bot\n"
            "2. Use `/getchannelid` to get the channel ID\n"
            "3. Use that ID with `/setchannel`\n\n"
            "The bot must be an admin in the channel.\n\n"
            "Use `/channels` to see all your channels.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    channel_spec = context.args[0].strip()
    chat_id = get_chat_id(channel_spec)
    
    # Try to verify the channel exists and bot has access
    try:
        # First, try to get chat info
        chat = await context.bot.get_chat(chat_id)
        
        # Verify it's actually a channel
        if chat.type != "channel":
            await message.reply_text(
                f"❌ *Error:* The specified chat is not a channel.\n\n"
                f"Chat type: {chat.type}\n"
                f"Please use a channel ID or username.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        # Always get the actual channel ID (numeric ID)
        actual_chat_id = chat.id
        
        # Get username if available (for public channels)
        username = chat.username if hasattr(chat, 'username') and chat.username else None
        
        # Initialize channels list if not exists
        if 'channels' not in context.user_data:
            context.user_data['channels'] = {}
        
        # Use the actual channel ID as the key for storage (more reliable)
        # This ensures the bot works even if channel visibility changes
        channel_key = str(actual_chat_id)
        
        # Store channel with both ID and username (if available)
        channel_data = {
            'title': chat.title,
            'id': str(actual_chat_id),
            'username': username,  # Store username if available
            'original_spec': channel_spec  # Keep original input for reference
        }
        
        # If channel was added with username, also map username to same data
        if username and channel_spec.startswith('@'):
            # Store under both ID and username for easy lookup
            context.user_data['channels'][channel_key] = channel_data
            # Also create a reference from username to ID
            if '@' + username not in context.user_data['channels']:
                context.user_data['channels']['@' + username] = channel_key  # Reference to ID key
        else:
            # Store only under ID
            context.user_data['channels'][channel_key] = channel_data
        
        # Set as default if it's the first channel
        if 'channel' not in context.user_data:
            context.user_data['channel'] = channel_key
        
        # Build response message
        display_name = f"@{username}" if username else f"`{actual_chat_id}`"
        response_text = (
            f"✅ Channel added successfully!\n\n"
            f"📺 Channel: {display_name}\n"
            f"📝 Title: {chat.title}\n"
            f"🆔 ID: `{actual_chat_id}`\n"
        )
        if username:
            response_text += f"📋 Username: @{username}\n"
        response_text += (
            f"\nTotal channels: {len([k for k in context.user_data['channels'].keys() if isinstance(context.user_data['channels'][k], dict)])}\n\n"
            f"💡 *Note:* Channel ID is stored, so it will work even if visibility changes.\n\n"
            f"Use `/channels` to see all channels and select one."
        )
        
        await message.reply_text(
            response_text,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error setting channel '{channel_spec}': {error_msg}")
        
        # Provide more specific error messages
        if "Chat not found" in error_msg or "chat not found" in error_msg.lower():
            help_text = (
                f"❌ *Chat Not Found*\n\n"
                f"Channel ID/Username: `{channel_spec}`\n\n"
                f"*Possible reasons:*\n"
                f"1. **Bot is not in the channel**\n"
                f"   → Add the bot to the channel as admin\n"
                f"   → Give it permission to post messages\n\n"
                f"2. **Wrong channel ID format**\n"
                f"   → Channel IDs are usually: `-1001234567890`\n"
                f"   → Make sure you copied the full ID\n\n"
                f"3. **Channel doesn't exist or was deleted**\n\n"
                f"*To get the correct channel ID:*\n"
                f"1. Forward a message from the channel to this bot\n"
                f"2. Send `/getchannelid`\n"
                f"3. Use the ID shown (it will be verified)\n\n"
                f"*For private channels:*\n"
                f"Make sure the bot is added as admin first!"
            )
        elif "not enough rights" in error_msg.lower() or "not a member" in error_msg.lower():
            help_text = (
                f"❌ *Permission Error*\n\n"
                f"Channel: `{channel_spec}`\n\n"
                f"*The bot needs:*\n"
                f"• To be added to the channel as admin\n"
                f"• Permission to post messages\n"
                f"• Permission to read messages\n\n"
                f"*Steps to fix:*\n"
                f"1. Go to channel settings\n"
                f"2. Add bot as administrator\n"
                f"3. Enable 'Post Messages' permission\n"
                f"4. Try again with `/setchannel {channel_spec}`"
            )
        else:
            help_text = (
                f"❌ *Error Setting Channel*\n\n"
                f"Channel: `{channel_spec}`\n"
                f"Error: `{error_msg}`\n\n"
                f"*Troubleshooting:*\n"
                f"• Make sure the channel exists\n"
                f"• Bot must be an admin in the channel\n"
                f"• Use correct format: `@channel_name` or `-1001234567890`\n\n"
                f"*Get channel ID:*\n"
                f"Forward a message from channel → Send `/getchannelid`"
            )
        
        await message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )


async def channels_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /channels command - show detailed list of channels with IDs"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Get channels list
    channels = context.user_data.get('channels', {})
    current_channel = context.user_data.get('channel', None)
    
    if not channels:
        await message.reply_text(
            "📺 *No channels added*\n\n"
            "*How to add channels:*\n\n"
            "1. **Forward a message** from a channel to this bot\n"
            "2. Send `/getchannelid` to get the channel ID\n"
            "3. Use `/setchannel <channel_id>` to add it\n\n"
            "OR\n\n"
            "For public channels:\n"
            "`/setchannel @channel_name`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Filter out reference entries (username -> ID mappings)
    actual_channels = {k: v for k, v in channels.items() if isinstance(v, dict)}
    
    # Build detailed channel list text
    channel_list = "📺 *Your Channels* ({})\n\n".format(len(actual_channels))
    
    if current_channel:
        current_info = actual_channels.get(current_channel, {})
        current_display = current_info.get('username', f"`{current_channel}`")
        if current_display.startswith('`'):
            channel_list += f"✅ *Current Default:* {current_display}\n\n"
        else:
            channel_list += f"✅ *Current Default:* @{current_display}\n\n"
    
    channel_list += "─" * 40 + "\n"
    channel_list += "*Channel Details:*\n\n"
    
    # Build keyboard with channel buttons
    keyboard = []
    for idx, (channel_key, channel_info) in enumerate(actual_channels.items(), 1):
        title = channel_info.get('title', channel_key)
        channel_id = channel_info.get('id', channel_key)
        username = channel_info.get('username')
        
        # Add to text list
        is_current = "✅ " if channel_key == current_channel else f"{idx}. "
        channel_list += f"{is_current}*{title}*\n"
        channel_list += f"   🆔 ID: `{channel_id}`\n"
        if username:
            channel_list += f"   📋 Username: @{username}\n"
        channel_list += "\n"
        
        # Check if auto-upload is enabled for this channel
        autoupload_enabled = context.user_data.get('autoupload_channels', {}).get(channel_key, False)
        upload_status = "📤" if autoupload_enabled else "📥"
        
        # Add to keyboard with auto-upload status
        prefix = "✅ " if channel_key == current_channel else "📺 "
        button_text = f"{prefix}{upload_status} {title[:26]}"
        if len(title) > 26:
            button_text += "..."
        
        keyboard.append([InlineKeyboardButton(
            button_text,
            callback_data=f"select_channel_{channel_key}"
        )])
    
    # Add buttons for actions
    keyboard.append([InlineKeyboardButton("➕ Add New Channel", callback_data="add_channel")])
    keyboard.append([InlineKeyboardButton("🔄 Refresh List", callback_data="refresh_channels")])
    keyboard.append([InlineKeyboardButton("📤 Auto-Upload Settings", callback_data="autoupload_settings")])
    keyboard.append([InlineKeyboardButton("❌ Remove Channel", callback_data="remove_channel_list")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        channel_list,
        reply_markup=reply_markup,
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


async def getchannelid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /getchannelid command - get channel ID from forwarded message and optionally add it"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    channel_id = None
    channel_title = None
    channel_spec = None
    
    # Check if message is forwarded from a channel (python-telegram-bot v20+ uses forward_origin)
    if message.forward_origin:
        from telegram import MessageOriginChannel
        if isinstance(message.forward_origin, MessageOriginChannel):
            origin = message.forward_origin
            # MessageOriginChannel has chat attribute
            channel_id = origin.chat.id
            channel_title = origin.chat.title if origin.chat.title else "Unknown"
            channel_spec = str(channel_id)
    
    # Check if replying to a forwarded message
    elif message.reply_to_message and message.reply_to_message.forward_origin:
        from telegram import MessageOriginChannel
        if isinstance(message.reply_to_message.forward_origin, MessageOriginChannel):
            origin = message.reply_to_message.forward_origin
            channel_id = origin.chat.id
            channel_title = origin.chat.title if origin.chat.title else "Unknown"
            channel_spec = str(channel_id)
    
    # Check if message is from a channel (bot is in the channel)
    elif message.chat.type == "channel":
        channel_id = message.chat.id
        channel_title = message.chat.title or "Unknown"
        channel_spec = str(channel_id)
    
    # If channel found, show info and offer to add
    if channel_id and channel_title:
        # Initialize channels list if not exists
        if 'channels' not in context.user_data:
            context.user_data['channels'] = {}
        
        # Use the actual channel ID as the key (not the spec)
        channel_key = str(channel_id)
        actual_channels = {k: v for k, v in context.user_data['channels'].items() if isinstance(v, dict)}
        
        # Check if already added (by ID)
        is_already_added = channel_key in actual_channels
        
        # Build response with add button
        info_text = (
            f"📺 *Channel Information*\n\n"
            f"📝 Title: {channel_title}\n"
            f"🆔 Channel ID: `{channel_id}`\n"
            f"📋 Spec: `{channel_spec}`\n\n"
        )
        
        if is_already_added:
            info_text += "✅ *Already in your channel list*\n\n"
        else:
            info_text += "💡 *Not in your channel list yet*\n\n"
        
        info_text += "*To add this channel:*\n"
        info_text += f"`/setchannel {channel_spec}`\n\n"
        info_text += "*Note:* Make sure the bot is an admin in this channel."
        
        # Create keyboard with add button if not already added
        keyboard = []
        if not is_already_added:
            # Use the actual channel ID for the callback
            keyboard.append([InlineKeyboardButton(
                f"➕ Add '{channel_title[:30]}' to List",
                callback_data=f"quick_add_{channel_id}"
            )])
        keyboard.append([InlineKeyboardButton("📺 View All Channels", callback_data="view_channels")])
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        
        await message.reply_text(
            info_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # No channel found - provide helpful instructions
    await message.reply_text(
        "❌ *No channel detected*\n\n"
        "*To get a private channel ID:*\n\n"
        "1. **Forward a message** from the private channel to this bot\n"
        "2. **Then send** `/getchannelid` command\n\n"
        "OR\n\n"
        "1. **Add the bot to the channel** as admin\n"
        "2. **Send** `/getchannelid` from within the channel\n\n"
        "*For public channels:*\n"
        "Just use `/setchannel @channel_name`",
        parse_mode=ParseMode.MARKDOWN
    )


async def removechannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /removechannel command"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    channels = context.user_data.get('channels', {})
    if not channels:
        await message.reply_text(
            "ℹ️ No channels to remove.\n\n"
            "Add channels using `/setchannel @channel_name`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Build keyboard with channels to remove
    keyboard = []
    for channel_spec, channel_info in channels.items():
        title = channel_info.get('title', channel_spec)
        keyboard.append([InlineKeyboardButton(
            f"❌ Remove {title[:30]}",
            callback_data=f"remove_channel_{channel_spec}"
        )])
    
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_remove")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await message.reply_text(
        "🗑️ *Remove Channel*\n\n"
        "Select a channel to remove:",
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )


async def upload_file_to_channel(bot, file_obj, file_name, file_type, target_chat, channel_spec, message):
    """Helper function to upload file to channel with filename as caption"""
    # Truncate filename if too long
    caption_text = file_name
    if len(caption_text) > 200:
        caption_text = file_name[:197] + "..."
    
    try:
        # Send file to channel using file_id (single upload!)
        if file_type == "video":
            await bot.send_video(
                chat_id=target_chat,
                video=file_obj.file_id,
                caption=caption_text,
                supports_streaming=True
            )
        elif file_type == "document":
            await bot.send_document(
                chat_id=target_chat,
                document=file_obj.file_id,
                caption=caption_text
            )
        elif file_type == "photo":
            await bot.send_photo(
                chat_id=target_chat,
                photo=file_obj.file_id,
                caption=caption_text
            )
        elif file_type == "audio":
            await bot.send_audio(
                chat_id=target_chat,
                audio=file_obj.file_id,
                caption=caption_text
            )
        elif file_type == "voice":
            await bot.send_voice(
                chat_id=target_chat,
                voice=file_obj.file_id,
                caption=caption_text
            )
        elif file_type == "video_note":
            try:
                await bot.send_video(
                    chat_id=target_chat,
                    video=file_obj.file_id,
                    caption=caption_text,
                    supports_streaming=True
                )
            except Exception:
                file_path = await bot.get_file(file_obj.file_id)
                temp_dir = Path("temp_downloads")
                temp_dir.mkdir(exist_ok=True)
                temp_file = temp_dir / f"video_note_{file_obj.file_id}.mp4"
                await file_path.download_to_drive(temp_file)
                await bot.send_document(
                    chat_id=target_chat,
                    document=temp_file,
                    caption=caption_text
                )
                if temp_file.exists():
                    temp_file.unlink()
        elif file_type == "sticker":
            try:
                await bot.send_document(
                    chat_id=target_chat,
                    document=file_obj.file_id,
                    caption=caption_text
                )
            except Exception:
                file_path = await bot.get_file(file_obj.file_id)
                temp_dir = Path("temp_downloads")
                temp_dir.mkdir(exist_ok=True)
                temp_file = temp_dir / f"sticker_{file_obj.file_id}.webp"
                await file_path.download_to_drive(temp_file)
                await bot.send_document(
                    chat_id=target_chat,
                    document=temp_file,
                    caption=caption_text
                )
                if temp_file.exists():
                    temp_file.unlink()
        else:
            await bot.send_document(
                chat_id=target_chat,
                document=file_obj.file_id,
                caption=caption_text
            )
        
        # Confirm upload success
        display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
        await message.reply_text(
            f"✅ *Uploaded to channel!*\n\n"
            f"📝 Filename: `{display_name}`\n"
            f"📺 Channel: `{channel_spec}`",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as send_error:
        logger.error(f"Error uploading file: {str(send_error)}")
        display_name = file_name[:50] + "..." if len(file_name) > 50 else file_name
        error_msg = (
            f"❌ *Upload failed*\n\n"
            f"📝 Filename: `{display_name}`\n"
            f"📺 Channel: `{channel_spec}`\n\n"
            f"Error: `{str(send_error)}`\n\n"
            f"Make sure the bot is an admin in the channel."
        )
        await message.reply_text(error_msg, parse_mode=ParseMode.MARKDOWN)


async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages posted in channels (auto-upload feature)"""
    message = update.channel_post or update.message
    
    if not message:
        return
    
    # Get channel ID
    channel_id = str(message.chat.id)
    
    # Check if auto-upload is enabled for this channel
    autoupload_channels = context.user_data.get('autoupload_channels', {})
    
    if not autoupload_channels.get(channel_id, False):
        return  # Auto-upload not enabled for this channel
    
    # Get channel info
    channels = context.user_data.get('channels', {})
    actual_channels = {k: v for k, v in channels.items() if isinstance(v, dict)}
    channel_info = actual_channels.get(channel_id, {})
    
    if not channel_info:
        return  # Channel not in our list
    
    # Check if message has a file
    file_obj = None
    file_name = None
    file_type = None
    
    if message.video:
        file_obj = message.video
        file_name = message.video.file_name or f"video_{message.video.file_id}.mp4"
        file_type = "video"
    elif message.document:
        file_obj = message.document
        file_name = message.document.file_name or f"document_{message.document.file_id}"
        file_type = "document"
    elif message.photo:
        file_obj = message.photo[-1]  # Get largest photo
        file_name = f"photo_{file_obj.file_id}.jpg"
        file_type = "photo"
    elif message.audio:
        file_obj = message.audio
        file_name = message.audio.file_name or f"audio_{message.audio.file_id}.mp3"
        file_type = "audio"
    elif message.voice:
        file_obj = message.voice
        file_name = f"voice_{message.voice.file_id}.ogg"
        file_type = "voice"
    elif message.video_note:
        file_obj = message.video_note
        file_name = f"video_note_{message.video_note.file_id}.mp4"
        file_type = "video_note"
    elif message.sticker:
        file_obj = message.sticker
        file_name = f"sticker_{message.sticker.file_id}.webp"
        file_type = "sticker"
    
    # If file found, re-upload it with filename as caption
    if file_obj and file_name:
        try:
            target_chat_id = int(channel_info.get('id', channel_id))
            channel_title = channel_info.get('title', channel_id)
            
            # Upload file with filename as caption using file_id (no download!)
            await upload_file_to_channel(
                context.bot,
                file_obj,
                file_name,
                file_type,
                target_chat_id,
                channel_id,
                message
            )
            
            logger.info(f"Auto-uploaded file '{file_name}' to channel {channel_title} (ID: {channel_id})")
        except Exception as e:
            logger.error(f"Error auto-uploading file: {str(e)}")
            # Don't send error message to channel to avoid spam


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries for channel selection"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    # Handle channel selection for upload
    if data.startswith("upload_to_"):
        parts = data.split("_")
        if len(parts) >= 4:
            # Extract channel and file hash
            channel_parts = parts[2:-1]  # Everything between "upload_to" and file hash
            channel_spec = "_".join(channel_parts)
            file_id_hash = parts[-1]
            
            # Get stored file info
            file_info_key = f'pending_file_{file_id_hash}'
            file_info = context.user_data.get(file_info_key)
            
            if not file_info:
                await query.edit_message_text("❌ File upload expired. Please upload again.")
                return
            
            # Get target chat
            channels = context.user_data.get('channels', {})
            # Filter actual channel entries (not references)
            actual_channels = {k: v for k, v in channels.items() if isinstance(v, dict)}
            
            if channel_spec not in actual_channels:
                await query.edit_message_text("❌ Channel not found.")
                return
            
            # Get the actual channel ID
            channel_info = actual_channels[channel_spec]
            target_chat = int(channel_info.get('id', channel_spec))
            
            # Update status
            await query.edit_message_text(f"⏳ Uploading to `{channel_spec}`...", parse_mode=ParseMode.MARKDOWN)
            
            # Upload file
            await upload_file_to_channel(
                context.bot,
                file_info['file_obj'],
                file_info['file_name'],
                file_info['file_type'],
                target_chat,
                channel_spec,
                query.message
            )
            
            # Clean up
            del context.user_data[file_info_key]
            await query.edit_message_text(
                f"✅ Uploaded to `{channel_spec}`!",
                parse_mode=ParseMode.MARKDOWN
            )
    
    # Handle channel selection
    elif data.startswith("select_channel_"):
        channel_spec = data.replace("select_channel_", "")
        context.user_data['channel'] = channel_spec
        channels = context.user_data.get('channels', {})
        channel_info = channels.get(channel_spec, {})
        title = channel_info.get('title', channel_spec)
        
        await query.edit_message_text(
            f"✅ Channel selected!\n\n"
            f"📺 Channel: `{channel_spec}`\n"
            f"📝 Title: {title}\n\n"
            f"This will be used as default for uploads.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    # Handle channel removal
    elif data.startswith("remove_channel_"):
        channel_spec = data.replace("remove_channel_", "")
        channels = context.user_data.get('channels', {})
        
        if channel_spec in channels:
            removed_title = channels[channel_spec].get('title', channel_spec)
            del channels[channel_spec]
            
            # If it was the current channel, clear it
            if context.user_data.get('channel') == channel_spec:
                if channels:
                    context.user_data['channel'] = list(channels.keys())[0]
                else:
                    context.user_data.pop('channel', None)
            
            await query.edit_message_text(
                f"✅ Channel removed!\n\n"
                f"Removed: `{channel_spec}`\n"
                f"Title: {removed_title}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await query.edit_message_text("❌ Channel not found.")
    
    elif data == "cancel_remove":
        await query.edit_message_text("❌ Cancelled.")
    
    elif data == "add_channel":
        await query.edit_message_text(
            "➕ *Add New Channel*\n\n"
            "*Method 1:* Forward a message from channel, then send `/getchannelid`\n\n"
            "*Method 2:* Use `/setchannel @channel_name` for public channels\n\n"
            "*Method 3:* Use `/setchannel -1001234567890` for private channels",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "quick_add_":
        # Extract channel spec from callback data
        channel_spec = data.replace("quick_add_", "")
        try:
            # Try to get channel info
            chat_id = get_chat_id(channel_spec)
            chat = await context.bot.get_chat(chat_id)
            
            # Initialize channels list if not exists
            if 'channels' not in context.user_data:
                context.user_data['channels'] = {}
            
            # Add channel
            context.user_data['channels'][channel_spec] = {
                'title': chat.title,
                'id': str(chat_id)
            }
            
            # Set as default if it's the first channel
            if 'channel' not in context.user_data:
                context.user_data['channel'] = channel_spec
            
            await query.edit_message_text(
                f"✅ *Channel Added!*\n\n"
                f"📺 Channel: `{channel_spec}`\n"
                f"📝 Title: {chat.title}\n\n"
                f"Total channels: {len(context.user_data['channels'])}\n\n"
                f"Use `/channels` to see all channels.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await query.edit_message_text(
                f"❌ *Error adding channel*\n\n"
                f"Error: {str(e)}\n\n"
                f"Make sure the bot is an admin in the channel.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data.startswith("quick_add_"):
        # Extract channel spec from callback data
        channel_spec = data.replace("quick_add_", "")
        try:
            # Try to get channel info
            chat_id = int(channel_spec)  # Should be numeric ID from forward_origin
            chat = await context.bot.get_chat(chat_id)
            
            # Get actual channel ID and username
            actual_chat_id = chat.id
            username = chat.username if hasattr(chat, 'username') and chat.username else None
            
            # Initialize channels list if not exists
            if 'channels' not in context.user_data:
                context.user_data['channels'] = {}
            
            # Use actual channel ID as key
            channel_key = str(actual_chat_id)
            
            # Store channel with ID and username
            channel_data = {
                'title': chat.title,
                'id': str(actual_chat_id),
                'username': username,
                'original_spec': channel_spec
            }
            
            context.user_data['channels'][channel_key] = channel_data
            
            # If username available, create reference
            if username:
                context.user_data['channels']['@' + username] = channel_key
            
            # Set as default if it's the first channel
            if 'channel' not in context.user_data:
                context.user_data['channel'] = channel_key
            
            # Count actual channels
            actual_count = len([k for k in context.user_data['channels'].keys() if isinstance(context.user_data['channels'][k], dict)])
            
            display_name = f"@{username}" if username else f"`{actual_chat_id}`"
            await query.edit_message_text(
                f"✅ *Channel Added!*\n\n"
                f"📺 Channel: {display_name}\n"
                f"📝 Title: {chat.title}\n"
                f"🆔 ID: `{actual_chat_id}`\n\n"
                f"Total channels: {actual_count}\n\n"
                f"💡 *Note:* Channel ID is stored for reliability.\n\n"
                f"Use `/channels` to see all channels.",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            await query.edit_message_text(
                f"❌ *Error adding channel*\n\n"
                f"Error: {str(e)}\n\n"
                f"Make sure the bot is an admin in the channel.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif data == "view_channels":
        # Show channels list
        await channels_command(update, context)
        await query.answer()
    
    elif data == "refresh_channels":
        # Refresh and show channels list
        await query.answer("Refreshing channel list...")
        await channels_command(update, context)
    
    elif data == "remove_channel_list":
        await removechannel_command(update, context)
    
    elif data == "skip_add":
        await query.edit_message_text("❌ Skipped. Use `/getchannelid` anytime to add channels.", parse_mode=ParseMode.MARKDOWN)


async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-detect channels from forwarded messages"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Check if message is forwarded from a channel
    channel_id = None
    channel_title = None
    
    if message.forward_origin:
        from telegram import MessageOriginChannel
        if isinstance(message.forward_origin, MessageOriginChannel):
            origin = message.forward_origin
            channel_id = origin.chat.id
            channel_title = origin.chat.title if origin.chat.title else "Unknown"
    
    # If channel detected, offer to add it (only if it's not a file)
    if channel_id and channel_title and not (message.video or message.document or message.photo or message.audio):
        channel_spec = str(channel_id)
        
        # Initialize channels list if not exists
        if 'channels' not in context.user_data:
            context.user_data['channels'] = {}
        
        # Check if already added
        if channel_spec not in context.user_data['channels']:
            keyboard = [[InlineKeyboardButton(
                f"➕ Add '{channel_title[:30]}' to Channel List",
                callback_data=f"quick_add_{channel_spec}"
            )]]
            keyboard.append([InlineKeyboardButton("❌ Skip", callback_data="skip_add")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await message.reply_text(
                f"🔍 *Channel Detected*\n\n"
                f"📝 Title: {channel_title}\n"
                f"🆔 Channel ID: `{channel_id}`\n\n"
                f"Would you like to add this channel to your list?",
                reply_markup=reply_markup,
                parse_mode=ParseMode.MARKDOWN
            )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads - show channel selection or upload immediately"""
    # Check authorization
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    # Get channels list (filter out references)
    all_channels = context.user_data.get('channels', {})
    channels = {k: v for k, v in all_channels.items() if isinstance(v, dict)}
    current_channel = context.user_data.get('channel', None)
    
    # If no channels, prompt to add one
    if not channels:
        await message.reply_text(
            "❌ *No channels added*\n\n"
            "Please add a channel first using:\n"
            "`/setchannel @your_channel`\n\n"
            "Or use channel ID:\n"
            "`/setchannel -1001234567890`\n\n"
            "You can add multiple channels and select which one to use.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # If multiple channels, show selection
    if len(channels) > 1:
        # Store file info temporarily for channel selection
        file_info = {
            'file_obj': None,
            'file_name': None,
            'file_type': None
        }
        
        # Determine file type and get file object
        if message.video:
            file_info['file_obj'] = message.video
            file_info['file_name'] = message.video.file_name or f"video_{message.video.file_id}.mp4"
            file_info['file_type'] = "video"
        elif message.document:
            file_info['file_obj'] = message.document
            file_info['file_name'] = message.document.file_name or f"document_{message.document.file_id}"
            file_info['file_type'] = "document"
        elif message.photo:
            file_info['file_obj'] = message.photo[-1]
            file_info['file_name'] = f"photo_{message.photo[-1].file_id}.jpg"
            file_info['file_type'] = "photo"
        elif message.audio:
            file_info['file_obj'] = message.audio
            file_info['file_name'] = message.audio.file_name or f"audio_{message.audio.file_id}.mp3"
            file_info['file_type'] = "audio"
        elif message.voice:
            file_info['file_obj'] = message.voice
            file_info['file_name'] = f"voice_{message.voice.file_id}.ogg"
            file_info['file_type'] = "voice"
        elif message.video_note:
            file_info['file_obj'] = message.video_note
            file_info['file_name'] = f"video_note_{message.video_note.file_id}.mp4"
            file_info['file_type'] = "video_note"
        elif message.sticker:
            file_info['file_obj'] = message.sticker
            file_info['file_name'] = f"sticker_{message.sticker.file_id}.webp"
            file_info['file_type'] = "sticker"
        else:
            await message.reply_text("❌ No file detected in your message.")
            return
        
        # Store file info for callback
        file_id_hash = str(hash(file_info['file_obj'].file_id))[:12]
        context.user_data[f'pending_file_{file_id_hash}'] = file_info
        
        # Build channel selection keyboard
        keyboard = []
        for channel_spec, channel_info in channels.items():
            title = channel_info.get('title', channel_spec)
            prefix = "✅ " if channel_spec == current_channel else "📺 "
            button_text = f"{prefix}{title[:25]}"
            if len(title) > 25:
                button_text += "..."
            
            keyboard.append([InlineKeyboardButton(
                button_text,
                callback_data=f"upload_to_{channel_spec}_{file_id_hash}"
            )])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        display_name = file_info['file_name'][:50] + "..." if len(file_info['file_name']) > 50 else file_info['file_name']
        await message.reply_text(
            f"📤 *Select Channel for Upload*\n\n"
            f"📁 File: `{display_name}`\n\n"
            f"Choose which channel to upload to:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Single channel - upload immediately
    channel_key = current_channel or list(channels.keys())[0]
    channel_info = channels.get(channel_key, {})
    target_chat = int(channel_info.get('id', channel_key))
    
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
    
    # Upload immediately to channel
    await upload_file_to_channel(
        context.bot,
        file_obj,
        file_name,
        file_type,
        target_chat,
        context.user_data.get('channel') or list(channels.keys())[0],
        message
    )
    
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
    
    # Upload immediately to channel using helper function
    channel_spec = current_channel or list(channels.keys())[0]
    await upload_file_to_channel(
        context.bot,
        file_obj,
        file_name,
        file_type,
        target_chat,
        channel_spec,
        message
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
    application.add_handler(CommandHandler("getchannelid", getchannelid_command))
    application.add_handler(CommandHandler("channels", channels_command))
    application.add_handler(CommandHandler("channel", channel_command))
    application.add_handler(CommandHandler("removechannel", removechannel_command))
    application.add_handler(CallbackQueryHandler(handle_callback))
    
    # Handle forwarded messages to auto-detect channels (only text messages, not files)
    # Note: Files are handled separately, so we don't need to handle forwarded files here
    
    # Handle channel posts (for auto-upload feature)
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_post))
    
    # Handle all file types - use separate handlers to avoid filter mixing issues
    # Note: Document and Sticker need to be instantiated, others are constants
    application.add_handler(MessageHandler(filters.PHOTO, handle_file))
    application.add_handler(MessageHandler(filters.VIDEO, handle_file))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(MessageHandler(filters.AUDIO, handle_file))
    application.add_handler(MessageHandler(filters.VOICE, handle_file))
    application.add_handler(MessageHandler(filters.VIDEO_NOTE, handle_file))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_file))
    
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

