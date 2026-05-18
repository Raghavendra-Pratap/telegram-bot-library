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
- **Historical ingest**: `forward_ingest.py` (Telethon) batch-forwards old posts into an ingest channel so the bot can index them (bots cannot read chat history directly)

## Setup

1. Install dependencies (shared):
```bash
./scripts/setup_env.sh
./scripts/install_deps.sh index
source .venv/bin/activate
```

2. Create a `.env` file from the sample (or run `python create_env.py`):
```bash
cp .env.example .env
# Edit .env — see .env.example for every variable and placeholder format
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
- `/backfill` - How to import **historical** uploads via `forward_ingest.py` (bots cannot read old messages)
- `/pending` - View files pending admin confirmation
- `/confirm <file_id> <correct_name>` - Confirm the correct name for a file

## Historical ingest (old uploads)

1. Create an **ingest** channel and add Index_bot as **admin** (see **HOW_TO_RUN.md → Registering the ingest channel**).
2. Optionally run `/add_channel @IngestChannel` so it appears in `/list_channels` before the first forward.
2. Put **`API_ID`** and **`API_HASH`** in `.env` (same as for any Telethon client).
3. With the bot running, execute from the `Index_bot` folder:

   `python forward_ingest.py @SourceChannel @IngestChannel`

4. First run logs in your user account and creates a session file (see `HOW_TO_RUN.md`).

Forwards appear as new posts; the bot indexes **documents / video / audio** files the same way as live uploads.

## How It Works

1. **Adding Channels**: Add your bot as an admin to channels; they can auto-register when posts arrive, or use `/add_channel`
2. **Automatic Indexing**: The bot indexes new **document / video / audio** channel posts in monitored channels
3. **Name Parsing**: File names are parsed to extract movie/series titles, removing codecs, resolutions, release groups, etc.
4. **Auto-Confirmation**: Files with high-confidence parsed names are automatically confirmed
5. **Admin Review**: Files with low-confidence or unparseable names are flagged for admin confirmation
6. **Search & Library**: Users can search for content and view detailed library information showing all uploads across channels

## Database

Data is stored in **SQLite** (`DB_PATH`, default `index_bot.db`) or in **PostgreSQL** if you set **`DATABASE_URL`** in `.env` (see `.env.example` and `HOW_TO_RUN.md`). Tables are created automatically on first run.

Stored entities include:

- Channel information
- File uploads with metadata
- Movie/series names (confirmed and pending)
- Upload history
