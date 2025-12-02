# Name Bot

A Telegram bot that automatically adds the filename as caption when files are uploaded to channels or groups.

## Features

- **Single upload** - Files upload once, bot automatically adds caption
- **No re-uploading** - Bot edits the message to add caption (no duplicate uploads)
- **Automatic** - Works in any channel/group where bot is added as admin
- **Fast** - Caption added instantly after upload
- **Reliable** - Improved error handling and retry logic
- Supports all file types: videos, documents, photos, audio, etc.
- Works in both channels and groups
- Simple setup - just add bot to channel/group as admin

## Improvements Over Caption Bot

This bot includes several improvements:

1. ✅ **Better file detection** - Fixed photo handling (photos don't have document attribute)
2. ✅ **Retry logic** - Automatically retries failed caption edits
3. ✅ **Better error handling** - More informative error messages
4. ✅ **Groups support** - Works in both channels and groups
5. ✅ **Status command** - `/status` command to check bot permissions
6. ✅ **Delay handling** - Waits for message to be fully processed before editing
7. ✅ **Better logging** - More detailed logs for debugging

## Setup

### 1. Install Dependencies

```bash
cd name-bot
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the `name-bot` directory:

```bash
# Copy the template
cp env_template.txt .env

# Edit .env and add your bot token
```

Or create `.env` manually:

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Optional - User Access Control
ENABLE_USER_VERIFICATION=false
ALLOWED_USER_IDS=123456789,987654321

# Optional - Retry Configuration
RETRY_DELAY=1.0
MAX_RETRIES=3

# Optional - Filename Handling
# If true, skip adding caption when original filename is not available (mobile uploads)
# If false, use generated filename (file_id based) as caption
SKIP_IF_NO_FILENAME=false

# Optional - Rate Limiting (Optimized for 100 files)
# Delay between processing files (in seconds) to avoid hitting Telegram rate limits
# Recommended values:
#   - 1.0 second: For <50 files
#   - 2.0 seconds: For 50-100 files (default, optimized for 100 files)
#   - 3.0 seconds: For 100+ files
PROCESSING_DELAY=2.0

# Optional - Retry Configuration (Optimized for large batches)
# Delay between retries when errors occur
RETRY_DELAY=2.0

# Maximum retry attempts (increased for flood control handling)
MAX_RETRIES=5

# Flood control retry delay multiplier
# When flood control is hit, wait this multiplier × requested time
# 1.5 = wait 50% longer than Telegram requests (safer, prevents re-rate-limiting)
FLOOD_RETRY_DELAY_MULTIPLIER=1.5
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

### How It Works

1. **Add bot to your channel/group as admin**

   - Go to your channel/group settings
   - Add administrators
   - Add this bot
   - **Enable "Edit messages" permission** (required!)

2. **Upload files directly to your channel/group**

   - Upload any file (video, document, photo, audio, etc.) to the channel/group
   - The bot automatically detects the file
   - Bot extracts the filename and adds it as caption
   - **Upload happens only once** - bot just edits the message

3. **That's it!** The caption is added automatically

### Forwarded Files

✅ **Forwarded files are automatically processed!**

- When you forward a file to a channel/group, bot treats it as a new message
- Bot automatically adds filename as caption (if filename is available)
- Works the same as direct uploads
- **Best solution for adding captions to old files:** Forward them to the channel/group

### Adding Captions to Old Files

⚠️ **Files uploaded before bot was added won't get captions automatically.**

**Solutions:**

1. **Forward the files** (Recommended):

   - Forward old files to the channel/group
   - Bot will automatically add captions
   - Works if original file had filename

2. **Use `/process_recent` command**:

   - Processes recent messages (limited by Telegram API)
   - May not work for very old messages
   - Requires bot to be admin

3. **Re-upload files**:
   - Download and re-upload with proper names
   - Bot will add captions automatically

**Note:** Telegram API has limitations on accessing old messages. Forwarding is the most reliable solution.

### Commands

- `/start` - Show welcome message and setup instructions
- `/help` - Show detailed help information
- `/status` - Check bot status and permissions in current chat
- `/process_recent [N]` - Process recent messages to add captions (see below)
- `/add_caption <msg_id>` - Add caption to specific message by ID (see below)

### Important Notes

- Bot must be **admin** in the channel/group
- Bot needs **"Edit messages"** permission (critical!)
- In **groups**, bot also needs **"Delete messages"** permission (for reposting workaround)
- Works automatically in any channel/group where bot is admin
- If file already has a caption, it won't be overwritten
- Video notes and stickers don't support captions (will be skipped)

### How It Works in Groups vs Channels

**Channels:**

- Bot can directly edit messages to add captions
- Single upload, just caption added

**Groups:**

- If message is from bot → Directly edit (like channels)
- If message is from another user → Delete original and repost with caption
  - This requires "Delete messages" permission
  - Uses file_id (no download/reupload needed)
  - Original message is replaced with new one containing caption
- Works in both channels and groups (not just channels)

### Mobile Upload Limitations

⚠️ **When uploading from mobile devices:**

- Files uploaded directly from gallery/camera may not preserve original filenames
- Telegram doesn't always provide the `file_name` attribute for mobile uploads
- This is a **Telegram API limitation** - the bot cannot retrieve filenames that Telegram doesn't provide

**Options:**

1. **Skip caption when filename unavailable** (Recommended):

   ```env
   SKIP_IF_NO_FILENAME=true
   ```

   - Bot won't add caption for files without original filename
   - Prevents ugly file_id-based captions

2. **Use generated filename** (Default):
   ```env
   SKIP_IF_NO_FILENAME=false
   ```
   - Bot will use file_id-based filename as caption
   - Example: `video_BAACAgUAAx0CZWS2yQACBBbBpLwb7Ut0Rz2zgVm8f6_Lt288IegACvx0AAjDEeVWnudslJ7q98jYE.mp4`

**Workarounds:**

- Rename files before uploading from mobile
- Use "Send as File" option in Telegram mobile app (instead of "Send as Photo/Video")
- Upload from desktop (typically preserves filenames correctly)

## Supported File Types

- Videos (MP4, AVI, MOV, etc.)
- Documents (PDF, DOCX, etc.)
- Photos (JPG, PNG, etc.)
- Audio files (MP3, WAV, etc.)
- Voice messages
- Video notes (skipped - don't support captions)
- Stickers (skipped - don't support captions)

## Configuration

### User Verification

By default, the bot allows all users. To restrict access:

1. Set `ENABLE_USER_VERIFICATION=true` in `.env`
2. Add user IDs to `ALLOWED_USER_IDS` (comma-separated)

To get your user ID, you can use [@userinfobot](https://t.me/userinfobot) on Telegram.

### Retry Configuration

If you experience issues with caption editing, you can adjust retry settings:

- `RETRY_DELAY`: Delay between retries in seconds (default: 1.0)
- `MAX_RETRIES`: Maximum number of retry attempts (default: 3)

## Troubleshooting

### Captions Not Being Added

1. **Check bot permissions:**

   - Use `/status` command in your channel/group
   - Make sure bot is admin
   - Make sure bot has "Edit messages" permission

2. **Check bot logs:**

   - Look for error messages in the console
   - Common errors:
     - "Permission denied" - Bot doesn't have edit permission
     - "Message not found" - Message was deleted before bot could edit
     - "Message can't be edited" - Message type doesn't support captions

3. **Verify file type:**
   - Video notes and stickers don't support captions
   - Some file types may have restrictions

### Bot Not Responding

1. Check if bot is running (look for "Bot is ready!" message)
2. Verify bot token is correct in `.env` file
3. Check internet connection
4. Look for error messages in logs

### Permission Errors

If you see "Permission denied" errors:

1. Remove bot from channel/group
2. Re-add bot as admin
3. Make sure "Edit messages" permission is enabled
4. Try `/status` command to verify permissions

## Technical Details

### How It Works

1. Bot listens for file uploads in channels/groups
2. When a file is detected, bot extracts the filename
3. Bot waits `PROCESSING_DELAY` seconds (default: 2.0s) for message processing and rate limit spacing
4. Bot edits the message to add filename as caption
5. If editing fails, bot retries up to `MAX_RETRIES` times (default: 5) with `RETRY_DELAY` delay (default: 2.0s)
6. If flood control is hit, bot waits for specified time (with multiplier) and retries automatically

### Error Handling

- Network errors: Automatic retry with exponential backoff
- Permission errors: Logged and skipped (no retry)
- Invalid messages: Logged and skipped
- **Flood control (rate limiting)**: Automatically waits for specified time and retries
  - Bot detects "Flood control exceeded" errors
  - Parses retry time from error message (e.g., "Retry in 30 seconds")
  - Waits for the specified time before retrying
  - Prevents hitting rate limits with configurable `PROCESSING_DELAY`

### Rate Limiting & Flood Control

**Problem:** When forwarding/uploading many files at once, Telegram may rate limit the bot.

**Solution:** Bot now handles flood control automatically:
- Detects rate limit errors
- Waits for the time specified by Telegram
- Retries automatically after waiting
- Configurable delay between files (`PROCESSING_DELAY`)

**Configuration:**
```env
# Increase delay if processing many files at once
PROCESSING_DELAY=2.0  # 2 seconds between files (default: 1.0)
```

**For large batches (50+ files):**
- Set `PROCESSING_DELAY=2.0` or `3.0` in `.env`
- This spaces out requests to avoid rate limits
- Bot will still process all files, just slower

## Notes

- **No re-uploading**: The bot edits existing messages to add captions - files upload only once
- **Instant captions**: Caption is added immediately after upload completes
- **Works in multiple channels/groups**: Add bot to as many channels/groups as you want
- **Preserves existing captions**: If a file already has a caption, it won't be overwritten
- **Efficient**: No file downloads or re-uploads - just message editing
- **Video notes and stickers**: These file types don't support captions in Telegram, so they're skipped

## Differences from Caption Bot

| Feature        | Caption Bot      | Name Bot             |
| -------------- | ---------------- | -------------------- |
| Photo handling | ❌ Buggy         | ✅ Fixed             |
| Groups support | ❌ Channels only | ✅ Channels & Groups |
| Retry logic    | ❌ No retries    | ✅ Automatic retries |
| Status command | ❌ No            | ✅ Yes               |
| Error messages | ⚠️ Basic         | ✅ Detailed          |
| Delay handling | ❌ None          | ✅ 0.5s delay        |

## License

This project is part of the Telegram Bot Library collection.
