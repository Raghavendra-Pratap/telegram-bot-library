"""
Main Telegram Bot for File Upload with Metadata and Grouping
"""
import logging
import asyncio
from pathlib import Path
from typing import List, Dict, Optional, Union
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

from config import (
    TELEGRAM_BOT_TOKEN,
    ENABLE_USER_VERIFICATION,
    ALLOWED_USER_IDS,
    DEFAULT_GROUP_STYLE,
    SHOW_TREE_SEPARATOR,
    TREE_SEPARATOR_FORMAT
)
from utils.file_scanner import FileScanner, FileInfo
from utils.tree_builder import TreeBuilder
from metadata.csv_reader import CSVMetadataReader
from metadata.sheets_reader import GoogleSheetsReader
from metadata.matcher import MetadataMatcher
from uploaders.file_uploader import FileUploader

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def is_user_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot"""
    if not ENABLE_USER_VERIFICATION:
        return True
    
    if not ALLOWED_USER_IDS:
        logger.warning("User verification enabled but no allowed users specified!")
        return False
    
    return user_id in ALLOWED_USER_IDS


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
📤 *File Upload Bot with Metadata & Grouping*

Upload files to Telegram with:
• 📁 Folder structure metadata
• 📊 CSV/Google Sheets metadata support
• 🔗 Flexible grouping options
• 📺 Channel selection per file/group
• 🎬 Telegram quality options (HD, as document, etc.)

*Commands:*
/start - Show this message
/help - Get detailed help
/upload - Upload files with options

*Usage:*
1. Use `/upload` to start uploading files
2. Provide directory path or send files
3. Optionally provide CSV/Google Sheets metadata
4. Choose grouping and upload options
"""
    await update.message.reply_text(welcome_message, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    if not await check_authorization(update, context):
        return
    
    help_text = """
*File Upload Bot - Help*

*Basic Usage:*
`/upload <directory_path>`

*With Metadata:*
`/upload <directory_path> --csv <csv_file_path>`
`/upload <directory_path> --sheet <google_sheet_url>`

*Options:*
• `--group-by <column>` - Group files by metadata column
• `--group-style <style>` - Grouping style: `media_group` or `sequential`
• `--channel <channel>` - Default channel for uploads
• `--no-tree` - Don't include tree structure in captions

*Grouping Styles:*
• `media_group` - Files appear together (max 10 files)
• `sequential` - Files uploaded one by one with shared captions

*Metadata Format:*
See `METADATA_FORMAT.md` for CSV/Sheet column specifications.

*Examples:*
`/upload ./my_files`
`/upload ./photos --csv metadata.csv --group-by category`
`/upload ./docs --sheet https://docs.google.com/... --channel @my_channel`
"""
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


def parse_upload_command(text: str) -> Dict[str, Union[str, bool]]:
    """Parse upload command arguments"""
    args = {
        'path': None,
        'csv_path': None,
        'sheet_url': None,
        'group_by': None,
        'group_style': DEFAULT_GROUP_STYLE,
        'channel': None,
        'include_tree': True,
        'sheet_name': None
    }
    
    parts = text.split()
    if len(parts) < 2:
        return args
    
    # First argument is the path
    args['path'] = parts[1]
    
    # Parse options
    i = 2
    while i < len(parts):
        if parts[i] == '--csv' and i + 1 < len(parts):
            args['csv_path'] = parts[i + 1]
            i += 2
        elif parts[i] == '--sheet' and i + 1 < len(parts):
            args['sheet_url'] = parts[i + 1]
            i += 2
        elif parts[i] == '--sheet-name' and i + 1 < len(parts):
            args['sheet_name'] = parts[i + 1]
            i += 2
        elif parts[i] == '--group-by' and i + 1 < len(parts):
            args['group_by'] = parts[i + 1]
            i += 2
        elif parts[i] == '--group-style' and i + 1 < len(parts):
            args['group_style'] = parts[i + 1]
            i += 2
        elif parts[i] == '--channel' and i + 1 < len(parts):
            args['channel'] = parts[i + 1]
            i += 2
        elif parts[i] == '--no-tree':
            args['include_tree'] = False
            i += 1
        else:
            i += 1
    
    return args


async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /upload command"""
    if not await check_authorization(update, context):
        return
    
    message = update.message
    
    if not message.text or len(message.text.split()) < 2:
        await message.reply_text(
            "❌ *Usage:* `/upload <directory_path> [options]`\n\n"
            "Use `/help` for detailed usage information.",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Parse command
    args = parse_upload_command(message.text)
    directory_path = args['path']
    
    if not directory_path:
        await message.reply_text("❌ Please provide a directory path.")
        return
    
    # Check if path exists
    upload_path = Path(directory_path)
    if not upload_path.exists():
        await message.reply_text(f"❌ Directory not found: `{directory_path}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    if not upload_path.is_dir():
        await message.reply_text(f"❌ Path is not a directory: `{directory_path}`", parse_mode=ParseMode.MARKDOWN)
        return
    
    # Show processing message
    status_msg = await message.reply_text("⏳ Scanning directory...")
    
    try:
        # Scan directory
        scanner = FileScanner(upload_path)
        files = scanner.scan(recursive=True)
        
        if not files:
            await status_msg.edit_text("❌ No files found in directory.")
            return
        
        # Load metadata if provided
        metadata_entries = []
        matcher = None
        
        if args['csv_path']:
            try:
                csv_path = Path(args['csv_path'])
                if not csv_path.is_absolute():
                    # Try relative to upload directory
                    csv_path = upload_path.parent / csv_path
                
                reader = CSVMetadataReader(csv_path)
                metadata_entries = reader.read()
                matcher = MetadataMatcher(match_strategy="exact")
                await status_msg.edit_text(f"✅ Loaded {len(metadata_entries)} metadata entries from CSV")
            except Exception as e:
                logger.error(f"Error reading CSV: {e}")
                await status_msg.edit_text(f"❌ Error reading CSV: {str(e)}")
                return
        
        elif args['sheet_url']:
            try:
                from config import GOOGLE_SHEETS_CREDENTIALS_PATH
                creds_path = Path(GOOGLE_SHEETS_CREDENTIALS_PATH) if GOOGLE_SHEETS_CREDENTIALS_PATH else None
                
                reader = GoogleSheetsReader(
                    args['sheet_url'],
                    credentials_path=creds_path,
                    sheet_name=args.get('sheet_name')
                )
                metadata_entries = reader.read()
                matcher = MetadataMatcher(match_strategy="exact")
                await status_msg.edit_text(f"✅ Loaded {len(metadata_entries)} metadata entries from Google Sheet")
            except Exception as e:
                logger.error(f"Error reading Google Sheet: {e}")
                await status_msg.edit_text(f"❌ Error reading Google Sheet: {str(e)}")
                return
        
        # Match files to metadata
        file_metadata_map = {}
        if matcher and metadata_entries:
            matches = matcher.match_all(files, metadata_entries)
            # Use file paths as keys for serialization
            file_metadata_map = {str(f.relative_path): m for f, m in matches.items() if m is not None}
            await status_msg.edit_text(f"✅ Matched {len(file_metadata_map)}/{len(files)} files to metadata")
        
        # Group files if requested
        groups = {}
        if args['group_by']:
            group_column = args['group_by']
            for file_info in files:
                file_key = str(file_info.relative_path)
                metadata = file_metadata_map.get(file_key)
                if metadata and group_column in metadata:
                    group_key = metadata[group_column].strip()
                    if group_key:
                        if group_key not in groups:
                            groups[group_key] = []
                        groups[group_key].append(str(file_info.relative_path))
                else:
                    # Files without metadata go to "ungrouped"
                    if "ungrouped" not in groups:
                        groups["ungrouped"] = []
                    groups["ungrouped"].append(str(file_info.relative_path))
        else:
            # No grouping - all files in one group
            groups["all"] = [str(f.relative_path) for f in files]
        
        # Prepare upload summary
        total_files = len(files)
        total_groups = len(groups)
        metadata_count = len(file_metadata_map)
        
        summary = (
            f"📊 *Upload Summary*\n\n"
            f"📁 Directory: `{upload_path}`\n"
            f"📄 Files: {total_files}\n"
            f"📊 Groups: {total_groups}\n"
        )
        
        if metadata_count > 0:
            summary += f"✅ Metadata matched: {metadata_count}/{total_files}\n"
        
        if args['group_by']:
            summary += f"🔗 Grouped by: `{args['group_by']}`\n"
        
        summary += f"\n📤 Ready to upload!"
        
        # Store upload context (using paths for serialization)
        context.user_data['upload_context'] = {
            'file_paths': [str(f.relative_path) for f in files],
            'root_path': str(upload_path),
            'file_metadata_map': file_metadata_map,
            'groups': groups,
            'args': args,
            'chat_id': update.effective_chat.id
        }
        
        # Show confirmation with options
        keyboard = [
            [InlineKeyboardButton("✅ Start Upload", callback_data="upload_start")],
            [InlineKeyboardButton("⚙️ Change Options", callback_data="upload_options")],
            [InlineKeyboardButton("❌ Cancel", callback_data="upload_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await status_msg.edit_text(summary, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    except Exception as e:
        logger.error(f"Error in upload command: {e}")
        await status_msg.edit_text(f"❌ Error: {str(e)}")


async def handle_upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle upload callback buttons"""
    if not await check_authorization(update, context):
        return
    
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "upload_cancel":
        await query.edit_message_text("❌ Upload cancelled.")
        if 'upload_context' in context.user_data:
            del context.user_data['upload_context']
        return
    
    if data == "upload_start":
        await start_upload(update, context)
        return
    
    if data == "upload_options":
        await query.edit_message_text(
            "⚙️ Options can be changed by running the upload command again with different parameters.\n\n"
            "Use `/help` for available options.",
            parse_mode=ParseMode.MARKDOWN
        )


async def start_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the actual upload process"""
    query = update.callback_query
    
    if 'upload_context' not in context.user_data:
        await query.edit_message_text("❌ Upload context not found. Please start over.")
        return
    
    upload_ctx = context.user_data['upload_context']
    file_paths = upload_ctx['file_paths']
    root_path = Path(upload_ctx['root_path'])
    file_metadata_map = upload_ctx['file_metadata_map']
    groups = upload_ctx['groups']
    args = upload_ctx['args']
    chat_id = upload_ctx.get('chat_id', update.effective_chat.id)
    
    # Reconstruct FileInfo objects from paths
    files_dict = {}
    for rel_path in file_paths:
        file_path = root_path / rel_path
        if file_path.exists():
            try:
                file_info = FileInfo(file_path, root_path)
                files_dict[rel_path] = file_info
            except Exception as e:
                logger.warning(f"Could not create FileInfo for {rel_path}: {e}")
    
    # Initialize uploader
    bot = context.bot
    uploader = FileUploader(bot, delay=1.0)
    
    await query.edit_message_text("⏳ Starting upload...")
    
    total_uploaded = 0
    total_failed = 0
    
    try:
        # Process each group
        for group_key, group_file_paths in groups.items():
            # Convert paths to FileInfo objects
            group_files = [files_dict[p] for p in group_file_paths if p in files_dict]
            
            if not group_files:
                continue
            
            # Get metadata for this group
            group_metadata = [file_metadata_map.get(str(f.relative_path)) for f in group_files]
            
            # Determine channel for this group
            group_channel = args.get('channel')
            if group_metadata and group_metadata[0]:
                # Check if metadata specifies channel
                channel_from_meta = group_metadata[0].get('channel')
                if channel_from_meta:
                    group_channel = channel_from_meta
            
            target_chat = uploader.get_chat_id(group_channel, chat_id)
            
            # Send tree separator if enabled
            if SHOW_TREE_SEPARATOR and group_files:
                tree_path = TreeBuilder.build_tree_path(group_files[0])
                if tree_path:
                    separator_text = TREE_SEPARATOR_FORMAT.format(path=tree_path)
                    try:
                        await bot.send_message(
                            chat_id=target_chat,
                            text=separator_text,
                            parse_mode=ParseMode.MARKDOWN
                        )
                    except Exception as e:
                        logger.warning(f"Could not send separator: {e}")
            
            # Upload based on group style
            group_style = args.get('group_style', DEFAULT_GROUP_STYLE)
            
            if group_style == 'media_group':
                # Try media group (only for photos/videos)
                success = await uploader.upload_media_group(
                    files=group_files,
                    chat_id=target_chat,
                    metadata_list=group_metadata,
                    include_tree=args.get('include_tree', True)
                )
                if success:
                    total_uploaded += len(group_files)
                else:
                    total_failed += len(group_files)
            else:
                # Sequential upload
                shared_caption = None
                if group_key != "all" and group_key != "ungrouped":
                    shared_caption = f"📁 Group: {group_key}"
                
                results = await uploader.upload_sequential(
                    files=group_files,
                    chat_id=target_chat,
                    metadata_list=group_metadata,
                    shared_caption_prefix=shared_caption,
                    include_tree=args.get('include_tree', True)
                )
                
                for file_info, success in results.items():
                    if success:
                        total_uploaded += 1
                    else:
                        total_failed += 1
            
            # Delay between groups
            await asyncio.sleep(1.0)
        
        # Final summary
        summary = (
            f"✅ *Upload Complete!*\n\n"
            f"✅ Uploaded: {total_uploaded}\n"
            f"❌ Failed: {total_failed}\n"
            f"📊 Total: {len(file_paths)}"
        )
        
        await query.edit_message_text(summary, parse_mode=ParseMode.MARKDOWN)
        
        # Clean up
        if 'upload_context' in context.user_data:
            del context.user_data['upload_context']
    
    except Exception as e:
        logger.error(f"Error during upload: {e}")
        await query.edit_message_text(f"❌ Upload error: {str(e)}")


def main():
    """Start the bot"""
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in environment variables!")
        return
    
    # Create application
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CallbackQueryHandler(handle_upload_callback, pattern="^upload_"))
    
    # Start bot
    logger.info("Upload bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

