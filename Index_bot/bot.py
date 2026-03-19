"""
Main Telegram Bot for Index Bot
"""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ChatType

from config import Config
from database import Database, Channel, FileUpload, CustomList
from name_parser import NameParser
from tmdb_helper import tmdb_helper

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Enable debug logging for channel detection
logging.getLogger('telegram.ext').setLevel(logging.INFO)

# Initialize components
db = Database(Config.DB_PATH)
parser = NameParser()


def is_admin(user_id):
    """Check if user is admin"""
    return Config.is_admin(user_id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    welcome_message = f"""
👋 Welcome to Index Bot, {user.first_name}!

I help you search for movies and series across Telegram channels.

**Search & Browse:**
/search <name> [--list <list>] - Search movies/series
/library <name> [--list <list>] - Detailed library view
/channel_index <channel> - View files in a specific channel

**Lists (Filter by Channels):**
/lists - View all custom lists
/create_list <name> <channels> - Create custom list
/delete_list <name> - Delete a list
Example: /create_list Movies @channel1 @channel2

**Info:**
/list_channels - List all monitored channels
/stats - View indexing statistics

**Admin Commands:**
/remove_channel <username> - Remove channel
/backfill <username> [limit] - Backfill messages
/pending - Files needing confirmation
/confirm <file_id> <name> - Confirm file name
/test_tmdb <name> - Test TMDB lookup

**Note:** Channels auto-detect when bot is added as admin!

Let's get started! Use /search to find your favorite content.
"""
    await update.message.reply_text(welcome_message, parse_mode='Markdown')


async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a channel to monitor (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /add_channel <channel_username>")
        return
    
    channel_username = context.args[0].lstrip('@')
    
    try:
        # Try to get channel info
        bot = context.bot
        chat = await bot.get_chat(f"@{channel_username}")
        
        if chat.type not in [ChatType.CHANNEL, ChatType.GROUP]:
            await update.message.reply_text("❌ This is not a channel or group.")
            return
        
        # Check if channel already exists
        existing = db.get_channel(str(chat.id))
        if existing:
            await update.message.reply_text(f"✅ Channel @{channel_username} is already being monitored.")
            return
        
        # Add channel to database
        channel = db.add_channel(
            channel_id=str(chat.id),
            channel_username=channel_username,
            channel_title=chat.title
        )
        
        await update.message.reply_text(
            f"✅ Channel @{channel_username} ({chat.title}) has been added to monitoring.\n\n"
            f"Make sure the bot is added as an admin to the channel with read permissions."
        )
        
        logger.info(f"Channel {channel_username} added by admin {update.effective_user.id}")
        
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        await update.message.reply_text(f"❌ Error adding channel: {str(e)}")


async def remove_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a channel from monitoring (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /remove_channel <channel_username>")
        return
    
    channel_username = context.args[0].lstrip('@')
    
    try:
        session = db.get_session()
        channel = session.query(Channel).filter_by(channel_username=channel_username).first()
        
        if channel:
            channel.is_active = False
            session.commit()
            await update.message.reply_text(f"✅ Channel @{channel_username} has been removed from monitoring.")
        else:
            await update.message.reply_text(f"❌ Channel @{channel_username} is not being monitored.")
        
        session.close()
        
    except Exception as e:
        logger.error(f"Error removing channel: {e}")
        await update.message.reply_text(f"❌ Error removing channel: {str(e)}")


async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all monitored channels (auto-detected when bot is admin)"""
    channels = db.get_all_channels()
    
    if not channels:
        await update.message.reply_text(
            "📭 No channels are being monitored yet.\n\n"
            "**To start monitoring:**\n"
            "1. Add the bot as admin to your channels\n"
            "2. Give it 'read messages' permission\n"
            "3. The bot will automatically detect and start indexing!"
        )
        return
    
    message = "📺 **Monitored Channels** (Auto-detected):\n\n"
    for channel in channels:
        username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel.channel_id}"
        status = "✅ Active" if channel.is_active else "❌ Inactive"
        message += f"• {channel.channel_title or 'Unknown'} ({username}) - {status}\n"
    
    message += f"\n**Total:** {len(channels)} channel(s)"
    await update.message.reply_text(message, parse_mode='Markdown')


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search for movies/series"""
    if not context.args:
        await update.message.reply_text("Usage: /search <movie/series name> [--list <list_name>]")
        return
    
    # Parse arguments for optional list filter
    args = context.args
    list_name = None
    search_terms = []
    
    i = 0
    while i < len(args):
        if args[i] == '--list' and i + 1 < len(args):
            list_name = args[i + 1]
            i += 2
        else:
            search_terms.append(args[i])
            i += 1
    
    if not search_terms:
        await update.message.reply_text("Usage: /search <movie/series name> [--list <list_name>]")
        return
    
    search_term = ' '.join(search_terms)
    
    # Get channel IDs for list if specified
    channel_ids = None
    if list_name:
        channel_ids = db.get_channels_for_list(list_name)
        if channel_ids is None:
            await update.message.reply_text(f"❌ List '{list_name}' not found. Use /lists to see available lists.")
            return
    
    # Search in specific channels or all
    if channel_ids:
        results = db.search_files_in_channels(search_term, channel_ids)
    else:
        results = db.search_files(search_term)
    
    if not results:
        await update.message.reply_text(f"❌ No results found for '{search_term}'")
        return
    
    # Group results by confirmed/parsed name
    grouped = {}
    for result in results:
        name = result.confirmed_name or result.parsed_name or result.file_name
        if name not in grouped:
            grouped[name] = []
        grouped[name].append(result)
    
    message = f"🔍 **Search Results for '{search_term}':**\n\n"
    
    # If multiple results, show buttons for selection
    if len(grouped) > 1:
        message += "Select a movie/series to view details:\n\n"
        
        keyboard = []
        for name, uploads in list(grouped.items())[:10]:
            if channel_ids:
                stats = db.get_upload_stats_in_channels(name, channel_ids)
            else:
                stats = db.get_upload_stats(name)
            total = stats['total_uploads']
            button_text = f"🎬 {name[:35]}... ({total})" if len(name) > 35 else f"🎬 {name} ({total})"
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"select_movie:{name}"
                )
            ])
        
        if len(grouped) > 10:
            message += f"... and {len(grouped) - 10} more result(s)"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        # Single result, show details directly
        name = list(grouped.keys())[0]
        if channel_ids:
            stats = db.get_upload_stats_in_channels(name, channel_ids)
        else:
            stats = db.get_upload_stats(name)
        
        total = stats['total_uploads']
        channels_count = len(stats['channels'])
        
        message += f"**{name}**\n"
        message += f"📊 Uploaded {total} time(s) across {channels_count} channel(s)\n"
        
        # Show channel breakdown
        for channel_id, channel_data in stats['channels'].items():
            count = channel_data['count']
            channel_title = channel_data.get('channel_title') or 'Unknown'
            channel_username = channel_data.get('channel_username')
            username = f"@{channel_username}" if channel_username else channel_id
            message += f"  • {channel_title} ({username}): {count} time(s)\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')


async def pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View files pending admin confirmation with interactive buttons (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    pending_files = db.get_pending_confirmations(limit=20)
    
    if not pending_files:
        await update.message.reply_text("✅ No files pending confirmation.")
        return
    
    message = "⏳ **Files Pending Confirmation:**\n\n"
    message += "Click a button below to confirm the file name:\n\n"
    
    keyboard = []
    for file in pending_files:
        channel = db.get_channel(file.channel_id)
        channel_name = channel.channel_title if channel else "Unknown"
        
        # Create button with file info
        button_text = f"📄 {file.file_name[:30]}..." if len(file.file_name) > 30 else f"📄 {file.file_name}"
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"confirm_file:{file.id}"
            )
        ])
        
        message += f"**ID: {file.id}** - `{file.file_name}`\n"
        message += f"Channel: {channel_name}\n"
        message += f"Parsed: {file.parsed_name or 'N/A'}\n\n"
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)


async def confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Confirm file name (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /confirm <file_id> <correct_name>")
        return
    
    try:
        file_id = int(context.args[0])
        confirmed_name = ' '.join(context.args[1:])
        
        upload = db.confirm_file_name(file_id, confirmed_name)
        
        if upload:
            await update.message.reply_text(
                f"✅ File name confirmed!\n\n"
                f"File: `{upload.file_name}`\n"
                f"Confirmed Name: **{confirmed_name}**"
            )
        else:
            await update.message.reply_text(f"❌ File with ID {file_id} not found.")
            
    except ValueError:
        await update.message.reply_text("❌ Invalid file ID. Please provide a number.")
    except Exception as e:
        logger.error(f"Error confirming file: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def library(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View detailed library information for a movie/series"""
    if not context.args:
        await update.message.reply_text("Usage: /library <movie/series name> [--list <list_name>]")
        return
    
    # Parse arguments for optional list filter
    args = context.args
    list_name = None
    name_terms = []
    
    i = 0
    while i < len(args):
        if args[i] == '--list' and i + 1 < len(args):
            list_name = args[i + 1]
            i += 2
        else:
            name_terms.append(args[i])
            i += 1
    
    if not name_terms:
        await update.message.reply_text("Usage: /library <movie/series name> [--list <list_name>]")
        return
    
    movie_name = ' '.join(name_terms)
    
    # Get channel IDs for list if specified
    channel_ids = None
    if list_name:
        channel_ids = db.get_channels_for_list(list_name)
        if channel_ids is None:
            await update.message.reply_text(f"❌ List '{list_name}' not found. Use /lists to see available lists.")
            return
    
    # First, try to find exact match
    uploads = db.get_library_view(movie_name, channel_ids)
    
    if not uploads:
        # Try searching for similar names
        if channel_ids:
            search_results = db.search_files_in_channels(movie_name, channel_ids)
        else:
            search_results = db.search_files(movie_name)
        
        if search_results:
            # Group by name
            grouped = {}
            for result in search_results:
                name = result.confirmed_name or result.parsed_name
                if name and name not in grouped:
                    grouped[name] = []
                if name:
                    grouped[name].append(result)
            
            if len(grouped) == 1:
                # Only one match, show it
                movie_name = list(grouped.keys())[0]
                uploads = db.get_library_view(movie_name, channel_ids)
            else:
                # Multiple matches, show list
                message = f"🔍 **Multiple matches found:**\n\n"
                for name in list(grouped.keys())[:10]:
                    if channel_ids:
                        stats = db.get_upload_stats_in_channels(name, channel_ids)
                    else:
                        stats = db.get_upload_stats(name)
                    message += f"• **{name}** ({stats['total_uploads']} uploads)\n"
                message += "\nUse /library <exact_name> to view details"
                await update.message.reply_text(message, parse_mode='Markdown')
                return
    
    if not uploads:
        await update.message.reply_text(f"❌ No library information found for '{movie_name}'")
        return
    
    # Get stats with channel filter if list specified
    if channel_ids:
        stats = db.get_upload_stats_in_channels(movie_name, channel_ids)
    else:
        stats = db.get_upload_stats(movie_name)
    
    message = f"📚 **Library: {movie_name}**\n\n"
    message += f"📊 Total Uploads: {stats['total_uploads']}\n"
    message += f"📺 Channels: {len(stats['channels'])}\n\n"
    message += "**Upload Details:**\n\n"
    
    # Group by channel and show uploads
    for channel_id, channel_data in stats['channels'].items():
        channel_title = channel_data.get('channel_title') or 'Unknown'
        channel_username = channel_data.get('channel_username')
        channel_uploads = channel_data['uploads']
        username = f"@{channel_username}" if channel_username else channel_id
        
        message += f"📺 **{channel_title}** ({username})\n"
        message += f"   Uploaded {len(channel_uploads)} time(s):\n"
        
        # Sort by uploaded_at (extracted as datetime)
        for upload_data in sorted(channel_uploads, key=lambda x: x.get('uploaded_at') or datetime.min.replace(tzinfo=None), reverse=True):
            uploaded_at = upload_data.get('uploaded_at')
            date_str = uploaded_at.strftime("%Y-%m-%d %H:%M") if uploaded_at else "Unknown"
            status = "✅" if upload_data.get('is_confirmed') else "⏳"
            file_name = upload_data.get('file_name', 'Unknown')
            message += f"   {status} `{file_name}` ({date_str})\n"
        
        message += "\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def create_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create a custom list of channels with interactive selection"""
    if not context.args:
        await update.message.reply_text(
            "Usage: /create_list <list_name>\n\n"
            "Example: /create_list MyMovies\n\n"
            "Then select channels from the list that appears."
        )
        return
    
    list_name = context.args[0]
    
    # Check if list already exists
    existing = db.get_custom_list(list_name)
    if existing:
        await update.message.reply_text(f"❌ List '{list_name}' already exists. Use a different name.")
        return
    
    # Store list name in context
    context.user_data['creating_list_name'] = list_name
    
    # Get all available channels
    channels = db.get_all_channels()
    
    if not channels:
        await update.message.reply_text(
            "❌ No channels available.\n\n"
            "Add the bot as admin to channels first, then they will appear here."
        )
        return
    
    # Initialize selected channels for this list
    key = f'selected_channels_{list_name}'
    context.user_data[key] = []
    
    message = f"📋 **Create List: {list_name}**\n\n"
    message += "Select channels to include (click to toggle):\n\n"
    
    keyboard = []
    for channel in channels:
        if not channel.is_active:
            continue
        username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel.channel_id}"
        button_text = f"📺 {channel.channel_title or 'Unknown'} ({username})"
        # Truncate if too long
        if len(button_text) > 60:
            button_text = button_text[:57] + "..."
        
        keyboard.append([
            InlineKeyboardButton(
                button_text,
                callback_data=f"toggle_list_channel:{channel.channel_id}:{list_name}"
            )
        ])
    
    # Add create and cancel buttons
    keyboard.append([
        InlineKeyboardButton("✅ Create List", callback_data=f"create_list_final:{list_name}"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)


async def delete_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a custom list"""
    if not context.args:
        await update.message.reply_text("Usage: /delete_list <list_name>")
        return
    
    list_name = context.args[0]
    
    try:
        if db.delete_custom_list(list_name):
            await update.message.reply_text(f"✅ List '{list_name}' deleted successfully.")
        else:
            await update.message.reply_text(
                f"❌ List '{list_name}' not found or cannot be deleted.\n"
                f"(Default 'All Channels' list cannot be deleted)"
            )
    except Exception as e:
        logger.error(f"Error deleting list: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def list_lists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all custom lists"""
    try:
        lists = db.get_all_custom_lists()
        
        if not lists:
            await update.message.reply_text("📋 No custom lists created yet.\n\nUse /create_list to create one.")
            return
        
        message = "📋 **Available Lists:**\n\n"
        
        for custom_list in lists:
            list_type = "🔵 Default" if custom_list.is_default else "📌 Custom"
            channel_ids_str = custom_list.channel_ids
            if not channel_ids_str or custom_list.is_default:
                channel_count = "All Channels"
            else:
                channel_count = f"{len(channel_ids_str.split(','))} channel(s)"
            
            message += f"{list_type} **{custom_list.list_name}**\n"
            message += f"   Channels: {channel_count}\n\n"
        
        message += "**Usage:**\n"
        message += "/search <name> --list <list_name>\n"
        message += "/library <name> --list <list_name>"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error listing lists: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def channel_index(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View index for a specific channel with interactive selection"""
    # If no args, show channel selection buttons
    if not context.args:
        channels = db.get_all_channels()
        
        if not channels:
            await update.message.reply_text(
                "📭 No channels available.\n\n"
                "Add the bot as admin to channels first, then they will appear here."
            )
            return
        
        message = "📺 **Select Channel to View Index:**\n\n"
        message += "Click a channel to view its file index:\n\n"
        
        keyboard = []
        for channel in channels:
            if not channel.is_active:
                continue
            username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel.channel_id}"
            button_text = f"📺 {channel.channel_title or 'Unknown'} ({username})"
            if len(button_text) > 60:
                button_text = button_text[:57] + "..."
            
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"select_channel:{channel.channel_id}:view"
                )
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        return
    
    # Legacy support: if channel username provided, use it
    channel_username = context.args[0].lstrip('@')
    
    try:
        bot = context.bot
        chat = await bot.get_chat(f"@{channel_username}" if not channel_username.startswith('-') else channel_username)
        channel_id = str(chat.id)
        
        # Get all files from this channel
        results = db.search_files_in_channels("", [channel_id])  # Empty search = all files
        
        if not results:
            await update.message.reply_text(f"📭 No files indexed from @{channel_username} yet.")
            return
        
        # Group by movie/series name
        grouped = {}
        for result in results:
            name = result.confirmed_name or result.parsed_name or result.file_name
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(result)
        
        message = f"📺 **Channel Index: {chat.title}** (@{channel_username})\n\n"
        message += f"📊 Total Files: {len(results)}\n"
        message += f"🎬 Unique Movies/Series: {len(grouped)}\n\n"
        message += "**Select a movie/series to view details:**\n\n"
        
        # Create buttons for each movie/series
        keyboard = []
        for name, uploads in list(grouped.items())[:20]:
            button_text = f"🎬 {name[:40]}... ({len(uploads)})" if len(name) > 40 else f"🎬 {name} ({len(uploads)})"
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"view_movie:{name}"
                )
            ])
        
        if len(grouped) > 20:
            message += f"... and {len(grouped) - 20} more"
        
        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await update.message.reply_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error getting channel index: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}")


async def test_channel_detection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test if bot can detect channels (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    message = "🔍 **Channel Detection Test**\n\n"
    
    # Check if bot is receiving channel updates
    message += "**Bot Status:**\n"
    message += "✅ Bot is running\n"
    message += "✅ Channel message handler registered\n\n"
    
    # List all registered channels
    channels = db.get_all_channels()
    message += f"**Registered Channels:** {len(channels)}\n"
    if channels:
        for ch in channels[:10]:  # Show first 10
            username = f"@{ch.channel_username}" if ch.channel_username else f"ID: {ch.channel_id}"
            status = "✅ Active" if ch.is_active else "❌ Inactive"
            message += f"• {ch.channel_title or 'Unknown'} ({username}) - {status}\n"
        if len(channels) > 10:
            message += f"... and {len(channels) - 10} more\n"
    else:
        message += "📭 No channels registered yet\n\n"
        message += "**To test auto-detection:**\n"
        message += "1. Add bot as admin to a channel\n"
        message += "2. Upload a file to that channel\n"
        message += "3. Check logs for 'Auto-registered channel'\n"
        message += "4. Run /list_channels to verify"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def test_tmdb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test TMDB lookup (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /test_tmdb <movie/series name>")
        return
    
    if not tmdb_helper.enabled:
        await update.message.reply_text("❌ TMDB API is not configured or not available.")
        return
    
    search_term = ' '.join(context.args)
    result = tmdb_helper.search(search_term)
    
    if result:
        message = f"""
✅ **TMDB Lookup Result:**

**Title:** {result['title']}
**Type:** {result['type'].upper()}
**Year:** {result.get('year', 'N/A')}
**TMDB ID:** {result['id']}
"""
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text(f"❌ No results found for '{search_term}' in TMDB")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View indexing statistics"""
    session = db.get_session()
    try:
        total_files = session.query(FileUpload).count()
        confirmed_files = session.query(FileUpload).filter_by(is_confirmed=True).count()
        pending_files = session.query(FileUpload).filter_by(needs_confirmation=True).count()
        total_channels = session.query(Channel).filter_by(is_active=True).count()
        
        tmdb_status = "✅ Enabled" if tmdb_helper.enabled else "❌ Disabled"
        
        message = f"""
📊 **Indexing Statistics:**

📁 Total Files: {total_files}
✅ Confirmed: {confirmed_files}
⏳ Pending: {pending_files}
📺 Channels: {total_channels}
🎬 TMDB API: {tmdb_status}
"""
        await update.message.reply_text(message, parse_mode='Markdown')
    finally:
        session.close()


async def backfill_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Backfill existing messages from a channel (admin only)"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You don't have permission to use this command.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /backfill <channel_username> [limit]")
        return
    
    channel_username = context.args[0].lstrip('@')
    limit = int(context.args[1]) if len(context.args) > 1 else 100
    
    try:
        bot = context.bot
        chat = await bot.get_chat(f"@{channel_username}")
        
        channel = db.get_channel(str(chat.id))
        if not channel or not channel.is_active:
            await update.message.reply_text(f"❌ Channel @{channel_username} is not being monitored.")
            return
        
        await update.message.reply_text(f"⏳ Backfilling up to {limit} messages from @{channel_username}...")
        
        count = 0
        # Note: get_chat_history might not be available in all versions
        # Using alternative approach with get_chat_member_count and manual message fetching
        try:
            # Try to use get_chat_history if available
            if hasattr(bot, 'get_chat_history'):
                async for message in bot.get_chat_history(chat.id, limit=limit):
                    if message.document or message.video or message.audio:
                        # Process the message
                        file = message.document or message.video or message.audio
                        file_name = file.file_name or f"file_{message.message_id}"
                        
                        if not db.file_exists(str(chat.id), message.message_id):
                            parsed = parser.parse_name(file_name)
                            parsed_name = parsed['name']
                            parsed_year = parsed.get('year')
                            
                            # Try to validate with TMDB if available
                            validated_name = parsed_name
                            if tmdb_helper.enabled and parsed_name:
                                tmdb_result = tmdb_helper.validate_name(parsed_name, parsed_year)
                                if tmdb_result:
                                    validated_name = tmdb_result['correct_name']
                                    parsed_name = validated_name
                            
                            # Auto-confirm if confidence is high or TMDB validated
                            auto_confirm = (
                                (parsed['confidence'] == 'high' and parsed_name and len(parsed_name) > 3) or
                                (tmdb_helper.enabled and validated_name != parsed.get('name', ''))
                            )
                            
                            db.add_file_upload(
                                channel_id=str(chat.id),
                                message_id=message.message_id,
                                file_name=file_name,
                                file_size=getattr(file, 'file_size', None),
                                file_id=file.file_id,
                                parsed_name=parsed_name,
                                auto_confirm=auto_confirm
                            )
                            count += 1
            else:
                await update.message.reply_text(
                    f"⚠️ Backfill feature requires get_chat_history method which is not available in this version.\n"
                    f"The bot will automatically index new messages going forward."
                )
                return
        except AttributeError:
            await update.message.reply_text(
                f"⚠️ Backfill is not supported in this version of python-telegram-bot.\n"
                f"The bot will automatically index new messages going forward."
            )
            return
        except Exception as e:
            logger.error(f"Error during backfill: {e}")
            await update.message.reply_text(f"❌ Error during backfill: {str(e)}")
            return
        
        await update.message.reply_text(f"✅ Backfilled {count} files from @{channel_username}")
        
    except Exception as e:
        logger.error(f"Error backfilling channel: {e}")
        await update.message.reply_text(f"❌ Error backfilling channel: {str(e)}")


async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle messages from monitored channels - auto-detects channels"""
    if update.channel_post is None:
        logger.debug("Received update but channel_post is None")
        return
    
    chat = update.channel_post.chat
    message = update.channel_post
    
    logger.info(f"Received message from channel: {chat.id} ({chat.title or 'Unknown'})")
    
    # Auto-register channel if bot is admin (bot receives messages from channels it's admin of)
    # This automatically adds the channel to monitoring
    channel = db.get_channel(str(chat.id))
    if not channel or not channel.is_active:
        # Auto-register the channel
        try:
            logger.info(f"Auto-registering new channel: {chat.id} - {chat.title or 'Unknown'}")
            channel = db.auto_register_channel(
                channel_id=str(chat.id),
                channel_username=chat.username,
                channel_title=chat.title
            )
            logger.info(f"✅ Auto-registered channel: {chat.title or chat.username or chat.id}")
        except Exception as e:
            logger.error(f"❌ Error auto-registering channel: {e}", exc_info=True)
            return  # Skip indexing if we can't register
    else:
        logger.debug(f"Channel {chat.id} already registered and active")
    
    # If channel is not active, skip
    if not channel.is_active:
        return
    
    # Check if message has a document/video
    file = None
    file_name = None
    file_size = None
    file_id = None
    
    if message.document:
        file = message.document
        file_name = file.file_name
        file_size = file.file_size
        file_id = file.file_id
    elif message.video:
        file = message.video
        file_name = file.file_name or f"video_{message.message_id}.mp4"
        file_size = file.file_size
        file_id = file.file_id
    elif message.audio:
        file = message.audio
        file_name = file.file_name or f"audio_{message.message_id}.mp3"
        file_size = file.file_size
        file_id = file.file_id
    
    if not file_name:
        return
    
    # Check if file already exists
    if db.file_exists(str(chat.id), message.message_id):
        return
    
    # Parse the file name
    parsed = parser.parse_name(file_name)
    parsed_name = parsed['name']
    parsed_year = parsed.get('year')
    
    # Try to validate with TMDB if available
    validated_name = parsed_name
    if tmdb_helper.enabled and parsed_name:
        tmdb_result = tmdb_helper.validate_name(parsed_name, parsed_year)
        if tmdb_result:
            validated_name = tmdb_result['correct_name']
            # Use TMDB-validated name for higher confidence
            parsed_name = validated_name
            logger.info(f"TMDB validated: '{parsed_name}' -> '{validated_name}' (TMDB ID: {tmdb_result['tmdb_id']})")
    
    # Auto-confirm if confidence is high or TMDB validated
    auto_confirm = (
        (parsed['confidence'] == 'high' and parsed_name and len(parsed_name) > 3) or
        (tmdb_helper.enabled and validated_name != parsed.get('name', ''))
    )
    
    # Add to database
    try:
        upload = db.add_file_upload(
            channel_id=str(chat.id),
            message_id=message.message_id,
            file_name=file_name,
            file_size=file_size,
            file_id=file_id,
            parsed_name=parsed_name,
            auto_confirm=auto_confirm
        )
        
        logger.info(f"Indexed file: {file_name} -> {parsed_name} (confidence: {parsed['confidence']}, confirmed: {auto_confirm}) from channel {chat.title}")
        
    except Exception as e:
        logger.error(f"Error indexing file: {e}")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages (for custom name input)"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.effective_user.id
    
    # Check if user is entering custom name for file confirmation
    if 'pending_confirm_file_id' in context.user_data:
        file_id = context.user_data['pending_confirm_file_id']
        custom_name = update.message.text.strip()
        
        if not is_admin(user_id):
            await update.message.reply_text("❌ You don't have permission.")
            del context.user_data['pending_confirm_file_id']
            return
        
        try:
            upload = db.confirm_file_name(file_id, custom_name)
            if upload:
                await update.message.reply_text(
                    f"✅ **File name confirmed!**\n\n"
                    f"File: `{upload.file_name}`\n"
                    f"Confirmed Name: **{custom_name}**",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ File with ID {file_id} not found.")
        except Exception as e:
            logger.error(f"Error confirming file: {e}")
            await update.message.reply_text(f"❌ Error: {str(e)}")
        finally:
            del context.user_data['pending_confirm_file_id']


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors"""
    error = context.error
    
    # Handle Conflict errors (409) - another bot instance is running
    if isinstance(error, Exception) and ("409" in str(error) or "Conflict" in str(error) or "terminated by other getUpdates" in str(error)):
        logger.error(
            "⚠️ CONFLICT ERROR: Another bot instance is running or webhook is active!\n"
            "This error means:\n"
            "1. Another instance of this bot is running (check other terminals/processes)\n"
            "2. A webhook is still active for this bot\n"
            "3. The bot was stopped incorrectly and Telegram still has pending updates\n\n"
            "Solutions:\n"
            "- Stop all other bot instances\n"
            "- Wait a few minutes for Telegram to clear the conflict\n"
            "- Or use webhooks instead of polling"
        )
        # Don't try to fix it automatically - it will just keep failing
        # The user needs to stop the other instance
        return
    
    # Log other errors
    logger.error(f"Exception while handling an update: {error}", exc_info=error)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle callback queries for interactive buttons"""
    query = update.callback_query
    await query.answer()
    
    if not query.data:
        return
    
    data = query.data
    user_id = query.from_user.id
    
    # Handle file confirmation
    if data.startswith("confirm_file:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission to use this.")
            return
        
        # Get file info and show name input options
        session = db.get_session()
        try:
            file_upload = session.query(FileUpload).filter_by(id=file_id).first()
            if not file_upload:
                await query.edit_message_text("❌ File not found.")
                return
            
            # Show options: use parsed name, or enter custom name
            message = f"**Confirm File Name**\n\n"
            message += f"File: `{file_upload.file_name}`\n"
            message += f"Parsed Name: {file_upload.parsed_name or 'N/A'}\n\n"
            message += "Select an option:"
            
            keyboard = []
            if file_upload.parsed_name:
                keyboard.append([
                    InlineKeyboardButton(
                        f"✅ Use: {file_upload.parsed_name}",
                        callback_data=f"confirm_use_parsed:{file_id}"
                    )
                ])
            keyboard.append([
                InlineKeyboardButton(
                    "✏️ Enter Custom Name",
                    callback_data=f"confirm_custom:{file_id}"
                )
            ])
            keyboard.append([
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
        finally:
            session.close()
    
    # Use parsed name
    elif data.startswith("confirm_use_parsed:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        
        session = db.get_session()
        try:
            file_upload = session.query(FileUpload).filter_by(id=file_id).first()
            if file_upload and file_upload.parsed_name:
                upload = db.confirm_file_name(file_id, file_upload.parsed_name)
                if upload:
                    await query.edit_message_text(
                        f"✅ **File name confirmed!**\n\n"
                        f"File: `{upload.file_name}`\n"
                        f"Confirmed Name: **{upload.confirmed_name}**",
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ Error confirming file.")
            else:
                await query.edit_message_text("❌ File or parsed name not found.")
        finally:
            session.close()
    
    # Enter custom name (prompt user)
    elif data.startswith("confirm_custom:"):
        file_id = int(data.split(":")[1])
        if not is_admin(user_id):
            await query.edit_message_text("❌ You don't have permission.")
            return
        
        # Store file_id in context for next message
        context.user_data['pending_confirm_file_id'] = file_id
        await query.edit_message_text(
            f"✏️ **Enter Custom Name**\n\n"
            f"File ID: {file_id}\n\n"
            f"Please reply with the correct movie/series name:",
            parse_mode='Markdown'
        )
    
    # Select channel for operations
    elif data.startswith("select_channel:"):
        channel_id = data.split(":")[1]
        operation = data.split(":")[2] if ":" in data.split(":")[2:] else "view"
        
        channel = db.get_channel(channel_id)
        if channel:
            if operation == "view":
                # Show channel index
                results = db.search_files_in_channels("", [channel_id])
                if results:
                    grouped = {}
                    for result in results:
                        name = result.confirmed_name or result.parsed_name or result.file_name
                        if name not in grouped:
                            grouped[name] = []
                        grouped[name].append(result)
                    
                    message = f"📺 **Channel Index: {channel.channel_title}**\n\n"
                    message += f"📊 Total Files: {len(results)}\n"
                    message += f"🎬 Unique Movies/Series: {len(grouped)}\n\n"
                    
                    # Show buttons for each movie/series
                    keyboard = []
                    for name, uploads in list(grouped.items())[:20]:
                        keyboard.append([
                            InlineKeyboardButton(
                                f"🎬 {name[:40]}... ({len(uploads)})" if len(name) > 40 else f"🎬 {name} ({len(uploads)})",
                                callback_data=f"view_movie:{name}"
                            )
                        ])
                    
                    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
                    await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
                else:
                    await query.edit_message_text(f"📭 No files indexed from this channel yet.")
    
    # Select movie/series from search results
    elif data.startswith("select_movie:"):
        movie_name = data.split(":", 1)[1]
        # Show library view for selected movie
        uploads = db.get_library_view(movie_name)
        if uploads:
            stats = db.get_upload_stats(movie_name)
            message = f"📚 **Library: {movie_name}**\n\n"
            message += f"📊 Total Uploads: {stats['total_uploads']}\n"
            message += f"📺 Channels: {len(stats['channels'])}\n\n"
            message += "**Upload Details:**\n\n"
            
            for channel_id, channel_data in stats['channels'].items():
                channel_title = channel_data.get('channel_title') or 'Unknown'
                channel_username = channel_data.get('channel_username')
                channel_uploads = channel_data['uploads']
                username = f"@{channel_username}" if channel_username else channel_id
                
                message += f"📺 **{channel_title}** ({username})\n"
                message += f"   Uploaded {len(channel_uploads)} time(s):\n"
                
                for upload_data in sorted(channel_uploads, key=lambda x: x.get('uploaded_at') or datetime.min.replace(tzinfo=None), reverse=True):
                    uploaded_at = upload_data.get('uploaded_at')
                    date_str = uploaded_at.strftime("%Y-%m-%d %H:%M") if uploaded_at else "Unknown"
                    status = "✅" if upload_data.get('is_confirmed') else "⏳"
                    file_name = upload_data.get('file_name', 'Unknown')
                    message += f"   {status} `{file_name}` ({date_str})\n"
                
                message += "\n"
            
            await query.edit_message_text(message, parse_mode='Markdown')
        else:
            await query.edit_message_text(f"❌ No library information found for '{movie_name}'")
    
    # View movie details
    elif data.startswith("view_movie:"):
        movie_name = data.split(":", 1)[1]
        uploads = db.get_library_view(movie_name)
        if uploads:
            stats = db.get_upload_stats(movie_name)
            message = f"📚 **{movie_name}**\n\n"
            message += f"📊 Total: {stats['total_uploads']} uploads\n"
            message += f"📺 Channels: {len(stats['channels'])}\n\n"
            
            for channel_id, channel_data in list(stats['channels'].items())[:5]:
                message += f"• {channel_data.get('channel_title', 'Unknown')}: {channel_data['count']} time(s)\n"
            
            if len(stats['channels']) > 5:
                message += f"\n... and {len(stats['channels']) - 5} more channels"
            
            await query.edit_message_text(message, parse_mode='Markdown')
    
    # Cancel operation
    elif data == "cancel":
        await query.edit_message_text("❌ Operation cancelled.")
    
    # Toggle channel for list creation
    elif data.startswith("toggle_list_channel:"):
        parts = data.split(":")
        channel_id = parts[1]
        list_name = parts[2] if len(parts) > 2 else None
        
        # Initialize selected channels for this list
        key = f'selected_channels_{list_name}'
        if key not in context.user_data:
            context.user_data[key] = []
        
        # Toggle selection
        if channel_id in context.user_data[key]:
            context.user_data[key].remove(channel_id)
            await query.answer("❌ Removed from selection")
        else:
            context.user_data[key].append(channel_id)
            await query.answer("✅ Added to selection")
        
        # Update the message to show current selection
        channels = db.get_all_channels()
        message = f"📋 **Create List: {list_name}**\n\n"
        selected = context.user_data.get(key, [])
        message += f"Selected: {len(selected)} channel(s)\n\n"
        message += "Click channels to toggle selection:\n\n"
        
        keyboard = []
        for channel in channels:
            if not channel.is_active:
                continue
            is_selected = str(channel.channel_id) in selected
            prefix = "✅ " if is_selected else "📺 "
            username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel.channel_id}"
            button_text = f"{prefix}{channel.channel_title or 'Unknown'} ({username})"
            if len(button_text) > 60:
                button_text = button_text[:57] + "..."
            
            keyboard.append([
                InlineKeyboardButton(
                    button_text,
                    callback_data=f"toggle_list_channel:{channel.channel_id}:{list_name}"
                )
            ])
        
        keyboard.append([
            InlineKeyboardButton("✅ Create List", callback_data=f"create_list_final:{list_name}"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)
    
    # Finalize list creation
    elif data.startswith("create_list_final:"):
        list_name = data.split(":", 1)[1]
        key = f'selected_channels_{list_name}'
        selected_channels = context.user_data.get(key, [])
        
        if not selected_channels:
            await query.edit_message_text("❌ Please select at least one channel.")
            return
        
        try:
            custom_list = db.create_custom_list(list_name, selected_channels, user_id)
            if custom_list:
                # Get channel info
                channel_info = []
                for channel_id in selected_channels:
                    channel = db.get_channel(channel_id)
                    if channel:
                        username = f"@{channel.channel_username}" if channel.channel_username else f"ID: {channel_id}"
                        channel_info.append(f"• {channel.channel_title or 'Unknown'} ({username})")
                
                channels_text = '\n'.join(channel_info)
                await query.edit_message_text(
                    f"✅ **List '{list_name}' created successfully!**\n\n"
                    f"**Channels in list:**\n{channels_text}\n\n"
                    f"Use: /search <name> --list {list_name}\n"
                    f"Or: /library <name> --list {list_name}",
                    parse_mode='Markdown'
                )
                # Clean up
                del context.user_data[key]
            else:
                await query.edit_message_text(f"❌ List '{list_name}' already exists.")
        except Exception as e:
            logger.error(f"Error creating list: {e}")
            await query.edit_message_text(f"❌ Error: {str(e)}")


async def post_init(application: Application) -> None:
    """Post-initialization hook to clear pending updates and check for conflicts"""
    bot = application.bot
    try:
        # First, delete any webhook
        logger.info("Checking webhook status...")
        webhook_info = await bot.get_webhook_info()
        if webhook_info.url:
            logger.warning(f"⚠️ Webhook is active at: {webhook_info.url}")
            logger.info("Deleting webhook to enable polling...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Webhook deleted")
        else:
            logger.info("✅ No webhook found, using polling mode")
            # Clear pending updates
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("✅ Pending updates cleared")
    except Exception as e:
        logger.warning(f"Could not check/clear webhook: {e}")
        logger.warning("⚠️ If you see 409 Conflict errors, make sure no other bot instance is running")


def main():
    """Main function to run the bot"""
    # Validate configuration
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return
    
    # Create application with post_init hook
    application = Application.builder().token(Config.BOT_TOKEN).post_init(post_init).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_channel", add_channel))
    application.add_handler(CommandHandler("remove_channel", remove_channel))
    application.add_handler(CommandHandler("list_channels", list_channels))
    application.add_handler(CommandHandler("backfill", backfill_channel))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("library", library))
    application.add_handler(CommandHandler("channel_index", channel_index))
    application.add_handler(CommandHandler("lists", list_lists))
    application.add_handler(CommandHandler("create_list", create_list))
    application.add_handler(CommandHandler("delete_list", delete_list))
    application.add_handler(CommandHandler("pending", pending))
    application.add_handler(CommandHandler("confirm", confirm))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("test_tmdb", test_tmdb))
    application.add_handler(CommandHandler("test_channel_detection", test_channel_detection))
    application.add_handler(CallbackQueryHandler(callback_handler))
    
    # Handle channel messages
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_message))
    
    # Handle text messages (for custom name input)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text_message
    ))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("=" * 60)
    logger.info("🚀 Bot starting...")
    logger.info("=" * 60)
    logger.info("⚠️  IMPORTANT: Make sure no other bot instance is running!")
    logger.info("   If you see 409 Conflict errors, stop other instances first.")
    logger.info("   Use: ./stop_all_bots.sh or: pkill -f 'python.*bot.py'")
    logger.info("=" * 60)
    
    try:
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,  # Clear pending updates on startup
            close_loop=False
        )
    except KeyboardInterrupt:
        logger.info("✅ Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Error running bot: {e}")
        if "Conflict" in str(e) or "409" in str(e):
            logger.error("\n" + "=" * 60)
            logger.error("🚨 409 CONFLICT ERROR DETECTED!")
            logger.error("=" * 60)
            logger.error("Another bot instance is running. Please:")
            logger.error("1. Stop all other bot instances: ./stop_all_bots.sh")
            logger.error("2. Wait a few seconds")
            logger.error("3. Try starting again")
            logger.error("=" * 60)
        raise


if __name__ == '__main__':
    main()
