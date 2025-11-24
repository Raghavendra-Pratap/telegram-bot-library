# Caption Bot

A Telegram bot that automatically sets the filename as the caption when files are uploaded.

## Features

- Automatically extracts filename from uploaded files
- Sets filename as caption when uploading the file
- **Upload files directly to your Telegram channels**
- Supports all file types: videos, documents, photos, audio, etc.
- Simple and straightforward operation
- Channel management commands

## Setup

### 1. Install Dependencies

```bash
cd caption_bot
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the `caption_bot` directory:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Optional - User Access Control
ENABLE_USER_VERIFICATION=false
ALLOWED_USER_IDS=123456789,987654321
```

### 3. Get Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the bot token and add it to your `.env` file

### 4. Run the Bot

```bash
python bot.py
```

## Usage

### Basic Usage (Send files back to you)

1. Start a chat with your bot
2. Upload any file (video, document, photo, audio, etc.)
3. The bot will automatically:
   - Extract the filename
   - Send the file back with the filename as the caption

### Upload to Channel

1. Set a channel using `/setchannel @your_channel` or `/setchannel -1001234567890`
2. Make sure the bot is an admin in the channel
3. Upload any file
4. The bot will automatically:
   - Extract the filename
   - Upload to your channel with the filename as the caption

## Commands

- `/start` - Show welcome message
- `/help` - Show help information
- `/setchannel @channel_name` - Set channel by username (e.g., `/setchannel @my_channel`)
- `/setchannel -1001234567890` - Set channel by ID
- `/channel` - Show current channel setting
- `/removechannel` - Remove channel (files will be sent back to you)

## Supported File Types

- Videos (MP4, AVI, MOV, etc.)
- Documents (PDF, DOCX, etc.)
- Photos (JPG, PNG, etc.)
- Audio files (MP3, WAV, etc.)
- Voice messages
- Video notes
- Stickers (sent as documents with caption)

## Configuration

### User Verification

By default, the bot allows all users. To restrict access:

1. Set `ENABLE_USER_VERIFICATION=true` in `.env`
2. Add user IDs to `ALLOWED_USER_IDS` (comma-separated)

To get your user ID, you can use [@userinfobot](https://t.me/userinfobot) on Telegram.

## Notes

- **Efficient file handling**: The bot uses Telegram's `file_id` system - no downloading or re-uploading needed!
- Files are sent instantly using references to files already on Telegram's servers
- Large files process much faster since there's no download/upload overhead
- The bot preserves the original file format and quality
- For video notes and stickers, the bot may download temporarily if needed (these file types have limitations)

