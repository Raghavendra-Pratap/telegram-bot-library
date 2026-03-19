# Technical Reference: down_oad_bot (Telegram Video Downloader Bot)

## Tech Stack

| Layer | Technology | Version (min) | Purpose |
|-------|------------|----------------|---------|
| Runtime | Python | 3.8+ | Application and downloaders |
| Bot framework | python-telegram-bot | ≥22.5 | Telegram long polling, handlers, Application |
| Download (YouTube, Reddit, Twitter) | yt-dlp | ≥2023.12.30 | Extract info and download video/audio |
| Download (Instagram) | instaloader | ≥4.10 | Instagram Reels (plus yt-dlp fallback) |
| HTTP | requests, aiohttp | ≥2.31.0, ≥3.9.0 | HTTP requests (downloaders; aiohttp used by ptb) |
| Config | python-dotenv | ≥1.0.0 | Load `.env` into `os.environ` |
| Media | ffmpeg-python | ≥0.2.0 | FFmpeg integration (used by yt-dlp for merge/convert) |

**External binary:** FFmpeg must be on PATH (used by yt-dlp for merging video+audio and converting to MP4/MP3).

### Dependencies (from requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| python-telegram-bot | ≥22.5 | Telegram Bot API, Application, handlers, polling |
| yt-dlp | ≥2023.12.30 | YouTube, Reddit, Twitter (and fallback for Instagram) |
| instaloader | ≥4.10 | Instagram Reels |
| requests | ≥2.31.0 | GIF/download HTTP |
| aiohttp | ≥3.9.0 | Async HTTP (dependency of python-telegram-bot) |
| python-dotenv | ≥1.0.0 | `.env` loading in `config.py` |
| ffmpeg-python | ≥0.2.0 | FFmpeg wrapper (yt-dlp uses FFmpeg directly; this may be optional) |

---

## Bot “API” (Commands & Callbacks)

There is no REST API. The bot is driven by Telegram updates: commands, text/caption messages, and inline callback queries.

### Commands

| Command | Handler | Purpose | Auth |
|---------|---------|---------|------|
| `/start` | `start` | Welcome message and usage summary | Yes (if ENABLE_USER_VERIFICATION) |
| `/help` | `help_command` | How to use, supported platforms | Yes (if ENABLE_USER_VERIFICATION) |

### Message Triggers

| Trigger | Handler | Purpose |
|---------|---------|---------|
| Text or caption containing a URL | `handle_url` | Extract URL → detect platform → get_video_info → show format buttons or error |

### Callback Data (Inline Buttons)

Telegram callback_data is a single string (max 64 bytes). The bot uses these formats:

| Prefix | Format | Example | Purpose |
|--------|--------|---------|---------|
| `cancel` | literal | `cancel` | Cancel current selection |
| `dl_` | `dl_{platform}_{format}_{format_id}_{url_hash}` | `dl_youtube_video_137_abc123def456` | Download: platform, format (video/audio/playlist), yt-dlp format_id (encoded), 12-char url_hash |
| (legacy) | `dl_{platform}_{format}_{url_hash}` | `dl_reddit_video_abc123def456` | Same with format_id implied "best" |
| `upload_` | `upload_{url_hash}` | `upload_xyz789abc012` | Upload to Telegram (single or playlist) |
| `local_` | `local_{url_hash}` | `local_xyz789abc012` | Keep local only (confirm path) |

**Encoding:** In callback_data, format_id characters `+` and `/` are replaced with `PLUS` and `SLASH` (and decoded when parsing) to avoid breaking on split by `_`.

**url_hash:** First 12 characters of `hashlib.md5(url.encode()).hexdigest()` (or of `url_hash + "_upload"` / `"_upload_playlist"` / `"_local"` / `"_local_playlist"` for upload/local keys).

---

## Key Types & Interfaces

### Platform (enum)

**Location:** `utils/url_detector.py`

```python
class Platform(Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    REDDIT = "reddit"
    TIKTOK = "tiktok"      # Detected but no downloader in bot map
    THREADS = "threads"    # Downloader exists but disabled in bot
    GIF = "gif"
    UNKNOWN = "unknown"
```

### URLDetector (static methods)

**Location:** `utils/url_detector.py`

| Method | Signature | Returns | Purpose |
|--------|------------|---------|---------|
| `is_valid_url` | `(url: str) -> bool` | bool | Regex validation of URL scheme/host/path |
| `detect_platform` | `(url: str) -> Tuple[Platform, Optional[str]]` | (Platform, extracted_id or None) | First matching platform and optional capture group |
| `is_playlist_url` | `(url: str) -> bool` | bool | True if YouTube playlist URL |

### BaseDownloader (abstract)

**Location:** `downloaders/base_downloader.py`

| Method | Signature | Returns | Purpose |
|--------|------------|---------|---------|
| `__init__` | `(download_dir: Path)` | — | Ensure download_dir exists |
| `download` | `(url, quality="best", audio_only=False)` | `Optional[Path]` | Download to disk; return path or None |
| `get_video_info` | `(url: str)` | `Optional[Dict[str, Any]]` | Metadata + optional format list (no download) |
| `find_downloaded_file` | `(before_time: float, video_id: str = None)` | `Optional[Path]` | Locate most recent file after `before_time` (by time or video_id) |
| `get_output_path` | `(filename: str)` | `Path` | `download_dir / filename` |

**YouTube-only:** `YouTubeDownloader.download_playlist(url, quality, audio_only)` returns `List[Path]`.

### video_info dict (get_video_info return)

**Location:** Returned by each downloader; shape used in `bot.py`. Not a single shared type; YouTube is the richest.

**Common fields (used in bot):**

| Field | Type | Description |
|-------|------|-------------|
| `title` | str | Display title (truncated to 60 in bot) |
| `duration` | int | Seconds (optional) |
| `uploader` | str | Optional |
| `view_count` | int | Optional |
| `url` | str | Original URL (optional) |
| `is_playlist` | bool | True for YouTube playlist |
| `video_count` | int | Playlist only |
| `entries` | list | Playlist only; list of entry dicts (url/webpage_url/id) |
| `available_formats` | list | YouTube (and optionally others); list of format dicts |

**available_formats item (YouTube _parse_formats):**

| Field | Type | Description |
|-------|------|-------------|
| `format_id` | str | yt-dlp format id (e.g. "137", "best") |
| `resolution` | str | e.g. "1080p", "Best" |
| `height` | int | Pixel height (for sorting) |
| `filesize` | int | Bytes (0 if unknown) |
| `ext` | str | e.g. "mp4" |
| `fps` | int/None | Optional |

---

## State Management

**Approach:** In-memory, per-user state in python-telegram-bot’s `context.user_data` (no persistence across restarts).

**Store location:** `context.user_data` (dict), key `'urls'`.

**URLs retention (trim to last 10 entries):** See `docs/URLS_RETENTION.md` for how entries are added, when they are trimmed, and how to change or remove the cap.

### State shape

| Key | Type | Purpose |
|-----|------|---------|
| `context.user_data['urls']` | `Dict[str, dict]` | Map url_hash (12-char) → url entry (see below). Trimmed to last 10 entries in `handle_url`. |

### url entry (single video)

| Field | Type | Purpose |
|-------|------|---------|
| `url` | str | Original URL |
| `platform` | str | Platform.value (e.g. "youtube") |
| `title` | str | Short title |
| `file_path` | str | Path to downloaded file (after download) |
| `format_type` | str | "video" or "audio" |

### url entry (playlist)

Same as above, plus:

| Field | Type | Purpose |
|-------|------|---------|
| `is_playlist` | bool | True |
| `all_files` | list[str] | Paths to downloaded files |
| `playlist_folder` | str | Folder containing playlist files |

**Mutation:** Filled in `handle_url` (after get_video_info); updated in `handle_callback` with file_path (and optionally all_files, playlist_folder); read in `handle_callback` and `handle_upload_choice`.

---

## Data Storage

**Primary storage:** Filesystem only. No database.

- **Downloaded files:** `DOWNLOAD_DIR` (default `./downloads`). Filenames from yt-dlp (e.g. `%(title)s.%(ext)s`) or platform logic.
- **Config:** `.env` (not in repo); `config.py` reads env at import time.

**No schemas/tables.** File layout is defined by each downloader (e.g. YouTube playlists in a subfolder named from playlist title).

---

## Environment Configuration

| Variable | Purpose | Required |
|----------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | Yes |
| `ENABLE_USER_VERIFICATION` | "true" to restrict to allowed users | No (default: false) |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs | When verification enabled |
| `INSTAGRAM_USERNAME` | Instagram login for Reels | No |
| `INSTAGRAM_PASSWORD` | Instagram password | No |
| `YOUTUBE_COOKIES_PATH` | Path to cookies.txt for private YouTube | No |
| `DOWNLOAD_DIR` | Directory for downloads | No (default: ./downloads) |
| `MAX_VIDEO_QUALITY` | Default max quality label (e.g. 2160p) | No (default: 2160p) |
| `PREFERRED_QUALITY` | Preferred quality (e.g. best) | No (default: best) |
| `ENABLE_FILE_SERVER` | Enable local file server (unused in this repo) | No (default: true) |
| `FILE_SERVER_PORT` | Port for file server | No (default: 8080) |
| `FILE_SERVER_HOST` | Host for file server | No (default: localhost) |

---

## Config Module (config.py)

| Symbol | Type | Source |
|--------|------|--------|
| `TELEGRAM_BOT_TOKEN` | str | env |
| `ENABLE_USER_VERIFICATION` | bool | env (true/false) |
| `ALLOWED_USER_IDS` | list[int] | env (comma-separated) |
| `INSTAGRAM_USERNAME`, `INSTAGRAM_PASSWORD` | str | env |
| `YOUTUBE_COOKIES_PATH` | str | env |
| `DOWNLOAD_DIR` | Path | env; created with mkdir(exist_ok=True) |
| `MAX_VIDEO_QUALITY`, `PREFERRED_QUALITY` | str | env |
| `ENABLE_FILE_SERVER` | bool | env |
| `FILE_SERVER_PORT` | int | env |
| `FILE_SERVER_HOST` | str | env |
| `QUALITY_FORMAT` | dict[str, str] | Hardcoded; maps "2160p", "1080p", … to yt-dlp format strings |

---

## Build & Run

### Run

```bash
# From project root (down_oad_bot)
python bot.py
```

No CLI arguments. Requires `.env` with at least `TELEGRAM_BOT_TOKEN`; optional env vars as above.

### Tests (sanity only)

| Script | Purpose |
|--------|---------|
| `test_bot_init.py` | Import config, assert `TELEGRAM_BOT_TOKEN` is set |
| `test_setup.py` | Check Python version, key packages (e.g. yt_dlp, telegram), FFmpeg in PATH |

No test framework or coverage; no CI config in repo.

### Deployment

- **Target:** Any host with Python 3.8+, FFmpeg, and network access to Telegram and source platforms.
- **Process:** Not defined in repo (e.g. manual run, systemd, or external launcher).
- **Environments:** Single env; config via `.env` only.

---

## Implementation Notes

- **Blocking downloads:** Downloaders are synchronous; they block the event loop. For many concurrent users, consider offloading to a thread pool or worker process.
- **Telegram limits:** File uploads: 50 MB (free) / 4 GB (Premium). Bot checks 4 GB and skips or errors on larger files; playlist upload uses 4 GB per file.
- **Callback data length:** Telegram limit 64 bytes; hence url_hash (12 chars) and encoded format_id.
- **Threads:** `ThreadsDownloader` is imported in `bot.py` but not added to the `downloaders` dict (disabled).
- **TikTok:** `Platform.TIKTOK` exists in URLDetector but no downloader is mapped in `bot.py`.

---

## Resolved (from clarifications)

- **ffmpeg-python:** Not imported in this codebase; yt-dlp uses the FFmpeg binary for conversion (e.g. merge, webm→mp4). Package kept in requirements for now; can be removed if confirmed unused.
- **File server:** Planned; config (ENABLE_FILE_SERVER, FILE_SERVER_*) kept for later implementation and configuration.

---

Status: Technical reference complete.  
Next: `/gaps` to produce `CLARIFICATIONS.md`.
