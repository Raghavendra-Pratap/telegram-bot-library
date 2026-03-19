# Codebase Map: down_oad_bot (Telegram Video Downloader Bot)

## Folder Structure

```
down_oad_bot/
├── bot.py                    # Main application: handlers, callbacks, upload queue
├── config.py                 # Env loading, constants, paths (single source of config)
├── requirements.txt         # Python dependencies
├── env_template.txt         # Template for .env (copy to .env)
├── .env                     # Local env (not committed); bot token, optional credentials
├── README.md                # User-facing setup and usage
├── downloaders/             # Platform-specific download implementations
│   ├── __init__.py          # Exports all downloaders + BaseDownloader
│   ├── base_downloader.py   # Abstract base: download(), get_video_info(), find_downloaded_file()
│   ├── youtube_downloader.py   # YouTube/Shorts/playlists via yt-dlp
│   ├── reddit_downloader.py    # Reddit via yt-dlp
│   ├── twitter_downloader.py   # Twitter/X via yt-dlp
│   ├── instagram_downloader.py # Instagram Reels via instaloader + yt-dlp
│   ├── threads_downloader.py   # Threads (enabled in bot)
│   └── gif_downloader.py       # Giphy/Tenor via requests
├── utils/                   # Shared utilities
│   ├── __init__.py          # Re-exports URLDetector, Platform
│   └── url_detector.py      # URL validation, platform detection (regex patterns)
├── downloads/                # Default output dir for downloaded files (created at runtime)
├── docs/                    # Recovery/development documentation
│   ├── PROJECT_CONTEXT.md   # What the app does, features, flows
│   ├── CODEBASE_MAP.md     # This file
│   ├── plans/
│   ├── decisions/
│   │   └── DECISIONS.md
│   ├── sessions/
│   └── modules/
├── test_bot_init.py         # Quick check: config loads, token present
└── test_setup.py            # Checks Python, deps, FFmpeg
```

---

## Feature-to-Code Map

| Feature | Bot / orchestration | Downloaders / utils | Key files |
|---------|---------------------|---------------------|-----------|
| Commands /start, /help | `bot.py` (start, help_command) | — | `bot.py` |
| Authorization check | `bot.py` (is_user_authorized, check_authorization) | — | `bot.py`, `config.py` |
| URL extraction from message | `bot.py` (extract_url_from_message) | `utils/url_detector.py` (is_valid_url) | `bot.py`, `utils/url_detector.py` |
| Platform detection | `bot.py` (handle_url) | `utils/url_detector.py` (detect_platform, Platform) | `utils/url_detector.py`, `bot.py` |
| Video info + format selection UI | `bot.py` (handle_url) | Each downloader `get_video_info()` | `bot.py`, `downloaders/*.py` |
| Single-video download | `bot.py` (handle_callback) | Each downloader `download()` | `bot.py`, `downloaders/*.py` |
| YouTube playlist download | `bot.py` (handle_url, handle_callback) | `downloaders/youtube_downloader.py` (download_playlist) | `bot.py`, `youtube_downloader.py` |
| Upload to Telegram / Keep local | `bot.py` (handle_upload_choice, upload_playlist_queue) | — | `bot.py` |
| Callback data (hash → URL) | `bot.py` (context.user_data['urls']) | — | `bot.py` |
| YouTube quality/cookies | — | `youtube_downloader.py`, config QUALITY_FORMAT, YOUTUBE_COOKIES_PATH | `config.py`, `youtube_downloader.py` |
| Instagram auth | — | `instagram_downloader.py`, config INSTAGRAM_* | `config.py`, `instagram_downloader.py` |
| Error handling (Conflict, network) | `bot.py` (error_handler, main try/except) | — | `bot.py` |

---

## Entry Points

**Application entry**
- **Main:** `bot.py` — `python bot.py` runs `main()`: builds `Application`, adds handlers, runs polling. No CLI args.

**No separate frontend/backend:** Telegram is the “frontend”; bot + downloaders are the backend.

**Test / sanity**
- `test_bot_init.py` — Imports config, checks `TELEGRAM_BOT_TOKEN` set.
- `test_setup.py` — Checks Python version, key packages, FFmpeg in PATH.

---

## Component Communication

**Telegram ↔ Bot**
- **Method:** Long polling (python-telegram-bot `Application.run_polling()`).
- **Handlers:** CommandHandler (/start, /help), MessageHandler (text/caption → handle_url), CallbackQueryHandler (buttons → handle_callback, handle_upload_choice).
- **State:** Per-user state in `context.user_data`; key structure `context.user_data['urls']` = dict of url_hash → {url, platform, title, file_path?, …}.

**Bot ↔ Downloaders**
- **Interface:** `BaseDownloader`: `get_video_info(url)`, `download(url, quality, audio_only)`; YouTube also `download_playlist(url, quality, audio_only)`.
- **Lookup:** `bot.py` holds a `downloaders` dict: `Platform` enum → downloader instance. Platform from `URLDetector.detect_platform(url)`.

**Bot ↔ Config**
- **Single import:** `from config import ...` in `bot.py` and in each downloader that needs env (e.g. QUALITY_FORMAT, YOUTUBE_COOKIES_PATH, INSTAGRAM_*).
- **No runtime reload:** Config is read at import time via `load_dotenv()` in `config.py`.

**Key integration points**

| Action | Initiator | Handler / component |
|--------|-----------|----------------------|
| User sends URL | MessageHandler | `bot.handle_url` → URLDetector → downloaders[platform].get_video_info |
| User taps Video/Audio/Playlist | CallbackQueryHandler | `bot.handle_callback` → downloaders[platform].download (or download_playlist) |
| User taps Upload / Keep local | CallbackQueryHandler | `bot.handle_upload_choice` → reply_video/reply_audio or edit_message_text |
| Playlist upload | handle_upload_choice | `upload_playlist_queue` (asyncio task) → context.bot.send_video in loop |

---

## Conventions Observed

### File naming
| Type | Pattern | Example |
|------|---------|---------|
| Main app | Single descriptive name | `bot.py`, `config.py` |
| Downloaders | `{platform}_downloader.py` | `youtube_downloader.py`, `gif_downloader.py` |
| Utils | Descriptive module name | `url_detector.py` |
| Tests | `test_*.py` | `test_bot_init.py`, `test_setup.py` |
| Config template | `env_template.*` | `env_template.txt` |

### Code patterns
- **Downloaders:** All extend `BaseDownloader`, live under `downloaders/`, and are imported from `downloaders` in `bot.py`.
- **Config:** One module `config.py`; env via `python-dotenv`; no config classes, only module-level constants.
- **Logging:** `logging.getLogger(__name__)` in each module; no central log config in app code (only `logging.basicConfig` in `bot.py`).
- **Async:** Bot handlers are async; downloaders are synchronous (blocking) and run in the same event loop.
- **Callbacks:** Data format `dl_{platform}_{format}_{format_id}_{url_hash}` or `upload_{hash}` / `local_{hash}`; url_hash is 12-char MD5 prefix.

### Error handling
- **Authorization:** `check_authorization()` at start of each user-facing handler; returns False and sends “Access Denied” if not allowed.
- **Global:** `error_handler` in bot catches `Conflict`, `NetworkError`, `TimedOut`; logs others with exc_info.
- **Download/upload:** try/except in handlers; user sees “Download failed” / “Upload failed” and often the local path.

### State management
- **User state:** Only `context.user_data['urls']` (dict). Entries trimmed to last 10 in `handle_url`. No persistence across restarts.

---

## Key Reusable Components

| Component | Location | Purpose | Used by |
|-----------|----------|---------|---------|
| URLDetector | `utils/url_detector.py` | is_valid_url, detect_platform(url) → (Platform, id), is_playlist_url | `bot.py` |
| Platform | `utils/url_detector.py` | Enum of supported platforms | `bot.py`, downloaders map |
| BaseDownloader | `downloaders/base_downloader.py` | Abstract download/get_video_info; find_downloaded_file; get_output_path | All platform downloaders |
| QUALITY_FORMAT | `config.py` | Map "2160p", "1080p", … to yt-dlp format strings | YouTube, Reddit, Twitter downloaders |
| extract_url_from_message | `bot.py` | Get first URL from message text, caption, or entities | handle_url |

---

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | Local secrets and overrides (token, ALLOWED_USER_IDS, INSTAGRAM_*, YOUTUBE_COOKIES_PATH, DOWNLOAD_DIR, etc.). Not committed. |
| `env_template.txt` | Template listing all env vars and short descriptions; copy to `.env`. |
| `config.py` | Loads .env; defines TELEGRAM_BOT_TOKEN, ENABLE_USER_VERIFICATION, ALLOWED_USER_IDS, DOWNLOAD_DIR, MAX_VIDEO_QUALITY, QUALITY_FORMAT, FILE_SERVER_*, Instagram/YouTube options. |
| `requirements.txt` | python-telegram-bot, yt-dlp, instaloader, requests, aiohttp, python-dotenv, ffmpeg-python. |

---

## Dependency Graph (high level)

```
bot.py
  → config
  → utils.url_detector (URLDetector, Platform)
  → downloaders (YouTubeDownloader, RedditDownloader, …)

config.py
  → os, pathlib, dotenv

downloaders/*.py
  → .base_downloader (BaseDownloader)
  → config (selected constants)
  → yt_dlp | instaloader | requests (platform-specific)

utils/url_detector.py
  → re, typing, enum
```

---

Status: Codebase map complete.  
Next: `/technical` for technical reference, or `/gaps` for clarifications.
