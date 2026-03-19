# Project Context: down_oad_bot (Telegram Video Downloader Bot)

## Overview

**What it is:** A Telegram bot that lets users download videos and audio from multiple platforms by sending a URL. The bot analyzes the link, shows format/quality options, downloads the file, and optionally uploads it to the chat or keeps it local only.

**Apparent purpose:** Enable personal, multi-platform video/audio downloads via Telegram without leaving the app.

**Target users:** End users who want to save videos from YouTube, Reddit, Twitter/X, Instagram Reels, and GIF platforms; optionally restricted to a whitelist of Telegram user IDs.

**Tech stack:** Python 3.8+, python-telegram-bot 22.x, yt-dlp, instaloader, requests, aiohttp, ffmpeg-python, python-dotenv.

---

## Features Inventory

| Feature | Description | Status | Location |
|---------|-------------|--------|----------|
| Multi-platform URL handling | Detect platform from URL (YouTube, Reddit, Twitter, Instagram, Threads, GIF) | Complete | `utils/url_detector.py`, `bot.py` |
| YouTube single video | Download single video with quality selection (up to 2160p) | Complete | `downloaders/youtube_downloader.py`, `bot.py` |
| YouTube playlist | Download entire playlist with quality choice or first video only | Complete | `bot.py` (handle_url, handle_callback) |
| Reddit video | Download Reddit video | Complete | `downloaders/reddit_downloader.py` |
| Twitter/X video | Download Twitter/X video | Complete | `downloaders/twitter_downloader.py` |
| Instagram Reels | Download Instagram Reels (optional auth) | Complete | `downloaders/instagram_downloader.py` |
| Threads | Download Threads posts | Complete | `downloaders/threads_downloader.py`, `bot.py` |
| GIF (Giphy, Tenor) | Download GIFs | Complete | `downloaders/gif_downloader.py` |
| Audio extraction (MP3) | Extract audio from video | Complete | All downloaders via base/yt-dlp |
| Format/quality selection | Inline buttons for resolution and video/audio | Complete | `bot.py` handle_url, handle_callback |
| Upload to Telegram | Send file to chat after download | Complete | `bot.py` handle_upload_choice |
| Keep local only | Skip Telegram upload, show local path | Complete | `bot.py` handle_upload_choice |
| User access control | Optional whitelist by Telegram user ID | Complete | `config.py`, `bot.py` is_user_authorized, check_authorization |
| Playlist upload queue | Sequential upload of playlist videos with progress and retries | Complete | `bot.py` upload_playlist_queue |
| Optional Instagram auth | .env credentials for Reels | Complete | `config.py` |
| Optional YouTube cookies | cookies.txt path for private videos | Complete | `config.py` |
| File server config | ENABLE_FILE_SERVER, FILE_SERVER_* (config only; no file server in this repo) | Config only | `config.py` |

### Feature Groups

**Download:**
- URL extraction from message text, caption, or entities (including forwarded messages).
- Platform detection → get video info → show inline keyboard (video quality + audio + cancel).
- Callback stores URL by short hash in `context.user_data['urls']` (Telegram callback data limit).
- Download to `DOWNLOAD_DIR` with platform-specific downloader; then prompt “Upload to Telegram” or “Keep local only”.

**Access control:**
- If `ENABLE_USER_VERIFICATION=true`, only `ALLOWED_USER_IDS` (comma-separated) can use /start, /help, URL handling, and callbacks.

**Playlist:**
- YouTube playlists show quality options (from first video) and “Download entire playlist” or “Download first video only”.
- Playlist download writes multiple files; then same upload vs local choice; playlist upload uses background task with progress and retry/rate-limit handling.

---

## User Flows

### Flow: Single video download
```
User sends URL → Bot detects platform → “Analyzing…” → Video info + [Video quality buttons] [Audio] [Cancel]
→ User picks Video/Audio → “Downloading…” → File on disk
→ [Upload to Telegram] [Keep local only] → User picks → Done (file sent or path shown)
```
**Status:** Working

### Flow: Playlist download
```
User sends YouTube playlist URL → Bot shows playlist title + count + quality options + “First video only”
→ User picks playlist or first video → “Downloading…” → Files on disk
→ [Upload to Telegram] [Keep local only] → If upload: queue task, progress updates, final summary
```
**Status:** Working

### Flow: Unauthorized user
```
User not in ALLOWED_USER_IDS (when verification on) → Any command/URL/callback
→ “Access Denied” message
```
**Status:** Working

### Flow: Cancel
```
User clicks “Cancel” on format selection → “Download cancelled”
```
**Status:** Working

---

## Data Flows

**Data in:**
- Telegram updates (messages with text/caption, callback queries).
- Environment: `TELEGRAM_BOT_TOKEN`, optional `ENABLE_USER_VERIFICATION`, `ALLOWED_USER_IDS`, `INSTAGRAM_*`, `YOUTUBE_COOKIES_PATH`, `DOWNLOAD_DIR`, `MAX_VIDEO_QUALITY`, `ENABLE_FILE_SERVER`, `FILE_SERVER_*`.

**Processing:**
- URL extracted → validated → platform detected → downloader chosen.
- Video info fetched → inline keyboard built; URL stored in `context.user_data['urls']` keyed by short hash.
- On callback: hash → URL → download → file path stored again under upload/local hashes → user choice → upload or confirm local.

**Data out:**
- Replies and edited messages (text, inline keyboards).
- Optional: video/audio file sent to chat.
- Files on disk under `DOWNLOAD_DIR` (and optional file server if enabled elsewhere).

```
[Telegram message with URL] → [URLDetector] → [Platform downloader]
→ [get_video_info] → [Inline keyboard] → [User callback]
→ [download] → [Upload or local confirmation] → [Optional send_video/reply_audio]
```

---

## Domain Model

| Entity | Description | Relationships |
|--------|-------------|---------------|
| Platform | Supported source (YouTube, Reddit, Twitter, Instagram, GIF; Threads defined but disabled) | Used by URLDetector and downloaders map |
| URLDetector | Validates URL and returns Platform (+ optional id) | Used by bot for every URL message |
| BaseDownloader | Abstract: download_dir, download(), get_video_info(), find_downloaded_file(), get_output_path() | Implemented per platform |
| YouTubeDownloader, RedditDownloader, etc. | Platform-specific download (yt-dlp, instaloader, etc.) | In `downloaders` dict in bot.py |
| context.user_data['urls'] | Map hash → {url, platform, title, file_path?, format_type?, is_playlist?, all_files?, playlist_folder?} | Used to resolve callbacks and upload/local choice |

---

## Glossary

| Term | Meaning |
|------|--------|
| url_hash | Short MD5 hash (12 chars) of URL (or URL+suffix) used as callback data key |
| format_type | `"video"`, `"audio"`, or `"playlist"` |
| quality / format_id | yt-dlp format selector (e.g. best, 1080p, or format id); encoded in callback (PLUS/SLASH for special chars) |
| DOWNLOAD_DIR | Directory where files are saved (default `./downloads`) |
| ENABLE_USER_VERIFICATION | If true, only ALLOWED_USER_IDS can use the bot |

---

## Current State Assessment

**What’s working:**
- Single-video and playlist flows for YouTube; Reddit, Twitter, Instagram, GIF.
- Authorization check on /start, /help, URL handler, and callbacks.
- Upload to Telegram and “Keep local only” for single file and playlist (with queue and retries).
- Error handling for conflict (multiple instances), network/timeout, and generic exceptions.

**What’s incomplete (WIP):**
- File server: config present (ENABLE_FILE_SERVER, FILE_SERVER_*); implementation planned and will be configured later; saving locally for now.
- PREFERRED_QUALITY: in config; planned for future use.

**What’s broken:**
- Nothing obvious from code review; platform APIs (Instagram, etc.) may change and cause runtime failures.

**Technical debt observed:**
- Large `bot.py` (single file for handlers, callbacks, upload queue).
- Callback data parsing is string-split and format-dependent (dl_platform_format_formatId_hash).
- Duplicate storage of same file info under two hashes (upload_ / local_) for each download.

---

## Resolved (from clarifications)

- **Env setup:** Canonical template is `env_template.txt`; copy to `.env` (README updated).
- **File server:** Planned; config kept; will be implemented and configured later; currently saving locally.
- **Threads:** Re-enabled in bot; plan to expand to more platforms over time.
- **URLs retention:** Current "last 10" entries in `context.user_data['urls']` kept for now; no strict file/URL count limit desired; bottlenecks can be discussed if needed.
- **TikTok:** Detection disabled (not supported in our region); support planned later.
- **PREFERRED_QUALITY:** Planned for future use.

