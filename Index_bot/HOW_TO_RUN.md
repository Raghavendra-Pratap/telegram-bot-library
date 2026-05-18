# How to Run the Index Bot

## Quick Start

### Option 1: Simple Run (Recommended for testing)
```bash
./run_bot.sh
```

This will:
- Activate the virtual environment
- Start the bot in the foreground (you'll see all output)
- Press `Ctrl+C` to stop

### Option 2: Using Python directly
```bash
source venv/bin/activate
python bot.py
```

### Option 3: Background Run (for production)
```bash
nohup python bot.py > bot.log 2>&1 &
```

Then check logs with:
```bash
tail -f bot.log
```

## Environment variables

All variables are documented in **`.env.example`** (safe to commit; no secrets).

Create your real config from the sample:

```bash
cd /path/to/Index_bot
cp .env.example .env
```

Then edit `.env`:

| Variable | Required for | Notes |
|----------|----------------|-------|
| `BOT_TOKEN` | `bot.py` | From @BotFather |
| `ADMIN_USER_IDS` | Admin commands | Comma-separated numeric user IDs |
| `API_ID` | `forward_ingest.py` | From [my.telegram.org/apps](https://my.telegram.org/apps) |
| `API_HASH` | `forward_ingest.py` | Same |
| `TMDB_API_KEY` | — | Optional; title validation |
| `DATABASE_URL` | — | Optional; **PostgreSQL** SQLAlchemy URL (if set, `DB_PATH` is ignored). Example: `postgresql+psycopg://user:pass@host:5432/dbname` |
| `DB_PATH` | — | SQLite file when `DATABASE_URL` is unset; default `index_bot.db` |
| `FORWARD_INGEST_SESSION` | — | Optional; Telethon session path |

### PostgreSQL on a server

1. Create a database and user (e.g. `index_bot`).
2. Set **`DATABASE_URL`** in `.env` using the **psycopg3** driver name so SQLAlchemy picks the installed package:

   `postgresql+psycopg://USER:PASSWORD@HOST:5432/index_bot`

   If the password has special characters (`@`, `#`, etc.), URL-encode them or use a [RFC connection string](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING) via your hoster’s docs.

3. Install dependencies (`psycopg` is listed in `requirements/bot-index.txt`). Restart the bot; SQLAlchemy will **`create_all`** tables on first start (sufficient for Index_bot’s schema).

4. **Migrating from SQLite:** export/import is not automated here — for a fresh server, start with Postgres empty; or use generic SQL tools to move data if you must keep old rows.

SQLite remains the default when **`DATABASE_URL`** is empty.

`python create_env.py` is an interactive alternative to copying `.env.example`.

## Before Running

### 1. Check for Running Instances
```bash
./check_bot_processes.sh
```

If you see other instances running, stop them first:
```bash
./stop_all_bots.sh
```

### 2. Verify Configuration
```bash
source venv/bin/activate
python check_readiness.py
```

All checks should pass before running.

## Discover all channels where the bot is admin

The Bot API **cannot** return a full list of chats the bot is in. The bot only knew channels after a **post** or **add** event.

Use **discovery** to scan your Telegram user account (Telethon) and register every channel/group where **Index Bot** appears in the **admin list**:

**In Telegram (admin):** `/discover_channels` or `/channels` → **Discover bot channels**

**On the server:**

```bash
source venv/bin/activate
python discover_bot_channels.py
```

Requires the same `API_ID`, `API_HASH`, and Telethon session as `forward_ingest.py`. Only chats **your user can access** are scanned.

## Historical ingest (`forward_ingest.py`)

The Bot API cannot read old messages. To build the library from **existing** uploads, forward posts into a dedicated **ingest channel** using a **user** session (Telethon). Index_bot indexes those forwards like normal new posts.

### Prerequisites

- `API_ID` and `API_HASH` in `.env` from [my.telegram.org/apps](https://my.telegram.org/apps)
- Dependencies installed (includes **Telethon**): `pip install -r requirements.txt` from this folder, or your monorepo `./scripts/install_deps.sh index`
- A Telegram **user** account that can read the **source** channel and forward from it
- An **ingest** channel where **Index_bot is admin** (can post)
- **`bot.py` should be running** so forwards are indexed as they arrive

### Registering the **ingest** channel (backdated uploads)

The second argument to `forward_ingest.py` is the **destination** channel where forwards land. The bot must be allowed to **see** those posts.

1. **Create** a channel (e.g. “Library ingest”) or use an existing one dedicated to imports.
2. **Add Index_bot as administrator** (at minimum: read messages so it receives updates; the bot does not need to post).
3. **Register the channel** in the bot’s database (either is fine):
   - **Option A:** Message the bot: `/add_channel @YourIngestChannel` (admin).
   - **Option B:** Do nothing extra — when the **first** forwarded post arrives, the bot **auto-registers** the channel (same as other monitored channels).
4. Confirm with `/list_channels` that the ingest channel appears **before or after** you start forwarding.
5. Run: `python forward_ingest.py @SourceArchive @YourIngestChannel`

The **source** is where history lives; your **Telethon user** must be able to open that chat and forward from it. The **ingest** channel is only the sink so the bot receives normal `channel_post` updates.

### First-time login

From the `Index_bot` directory:

```bash
source venv/bin/activate
python forward_ingest.py @SourceChannel @IngestChannel --dry-run
```

The first real run (without `--dry-run`) will create `forward_ingest.session` and prompt for phone / code. That file is secret — do not commit it (it is gitignored).

Optional: set `FORWARD_INGEST_SESSION` in `.env` to change the session file path/name.

### Run (forward oldest → newest)

```bash
python forward_ingest.py @SourceChannel @IngestChannel
```

Useful flags:

| Flag | Meaning |
|------|--------|
| `--dry-run` | Scan and count document-type media only; no forwards |
| `--limit N` | Scan at most `N` messages in the source |
| `--batch-size 15` | Messages per `forward_messages` call |
| `--delay 2.0` | Seconds to sleep after each batch (rate limiting) |

### Limitations

- **Protected content** / forwarding disabled in the source → forwards may fail or be incomplete
- Only **document-type** media are considered (aligned with the bot’s document/video/audio indexing)
- Telegram **FloodWait** is handled once per batch; if you hit limits often, raise `--delay`

In Telegram, admins can use **`/backfill`** for a short reminder of these steps.

## What to Expect

When the bot starts successfully, you should see:
```
============================================================
🚀 Bot starting...
============================================================
⚠️  IMPORTANT: Make sure no other bot instance is running!
   If you see 409 Conflict errors, stop other instances first.
   Use: ./stop_all_bots.sh or: pkill -f 'python.*bot.py'
============================================================
INFO:tmdb_helper:TMDB API initialized successfully
INFO:__main__:Checking webhook status...
INFO:__main__:✅ No webhook found, using polling mode
INFO:__main__:✅ Pending updates cleared
INFO:telegram.ext.Application:Application started
```

## Troubleshooting

### Bot won't start
1. Check if another instance is running: `./check_bot_processes.sh`
2. Stop all instances: `./stop_all_bots.sh`
3. Wait 10 seconds
4. Try again

### 409 Conflict Error
- Another bot instance is running
- Run: `./stop_all_bots.sh`
- Wait 10-15 seconds
- Start again

### Configuration Errors
- Run: `python check_readiness.py`
- Fix any issues shown
- Make sure `.env` file has `BOT_TOKEN` and `ADMIN_USER_IDS`

## Stopping the Bot

### If running in foreground:
- Press `Ctrl+C`

### If running in background:
```bash
pkill -f "Index_bot.*bot.py"
```

Or use:
```bash
./stop_all_bots.sh
```

## Next Steps After Starting

1. **Add channels to monitor:**
   - Add your bot as admin to channels
   - Use: `/add_channel @channel_username`

2. **Test the bot:**
   - Send `/start` to your bot
   - Try `/list_channels`
   - Try `/stats`

3. **Monitor activity:**
   - Watch the console output
   - Check for any errors
   - Files will be automatically indexed as they're uploaded

## Production Deployment

For running 24/7, consider:
- Using `systemd` service (Linux)
- Using `screen` or `tmux` for session management
- Setting up log rotation
- Monitoring with tools like `supervisor`

Example systemd service:
```ini
[Unit]
Description=Index Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Index_bot
ExecStart=/path/to/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
