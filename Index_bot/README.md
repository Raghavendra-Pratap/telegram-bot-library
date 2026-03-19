# Telegram Bot Library - Index Bot

A Telegram bot that indexes files from channels, extracts movie/series names, and provides search functionality.

> **Branch status:** Under development. Available on `development` branch only.

## Features

- **Channel Monitoring**: Automatically fetches and indexes all file names from specified Telegram channels
- **Smart Name Extraction**: Parses file names to extract correct movie/series titles using advanced pattern matching
- **Auto-Confirmation**: Files with high-confidence parsed names are automatically confirmed
- **Search Functionality**: Search for movies/series across all monitored channels
- **Admin Confirmation**: For files that can't be automatically identified, admins can confirm the correct name
- **Upload Tracking**: Shows how many times a file/movie/series was uploaded across different channels
- **Library View**: Display all uploads of the same movie/series with locations and timestamps
- **Backfill Support**: Index existing messages from channels

## Setup

1. Install dependencies (shared):
```bash
./scripts/setup_env.sh
./scripts/install_deps.sh index
source .venv/bin/activate
```

2. Create a `.env` file with your bot credentials:
```
BOT_TOKEN=your_bot_token_here
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
TMDB_API_KEY=your_tmdb_api_key_optional
ADMIN_USER_IDS=123456789,987654321
```

3. Add your bot to the channels you want to monitor (as admin with read permissions)

4. Run the bot:
```bash
python bot.py
```

## Usage

### User Commands
- `/start` - Start the bot and see available commands
- `/search <movie_name>` - Search for a movie/series across all channels
- `/library <movie_name>` - View detailed library information for a movie/series (shows all uploads with timestamps)
- `/list_channels` - List all monitored channels
- `/stats` - View indexing statistics

### Admin Commands
- `/add_channel <channel_username>` - Add a channel to monitor
- `/remove_channel <channel_username>` - Remove a channel from monitoring
- `/backfill <channel_username> [limit]` - Backfill existing messages from a channel (default: 100)
- `/pending` - View files pending admin confirmation
- `/confirm <file_id> <correct_name>` - Confirm the correct name for a file

## How It Works

1. **Adding Channels**: Add your bot as an admin to the channels you want to monitor, then use `/add_channel` to register them
2. **Automatic Indexing**: The bot automatically indexes all new file uploads in monitored channels
3. **Name Parsing**: File names are parsed to extract movie/series titles, removing codecs, resolutions, release groups, etc.
4. **Auto-Confirmation**: Files with high-confidence parsed names are automatically confirmed
5. **Admin Review**: Files with low-confidence or unparseable names are flagged for admin confirmation
6. **Search & Library**: Users can search for content and view detailed library information showing all uploads across channels

## Database

The bot uses SQLite database (`index_bot.db`) to store:
- Channel information
- File uploads with metadata
- Movie/series names (confirmed and pending)
- Upload history
