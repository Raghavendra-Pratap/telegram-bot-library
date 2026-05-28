"""
Configuration management for the Telegram Video Downloader Bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# User Access Control
ENABLE_USER_VERIFICATION = os.getenv("ENABLE_USER_VERIFICATION", "false").lower() == "true"
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "").strip()

# Admin user ID — required for the approval flow when ENABLE_USER_VERIFICATION=true
_admin_raw = os.getenv("ADMIN_USER_ID", "").strip()
ADMIN_USER_ID: int | None = int(_admin_raw) if _admin_raw.isdigit() else None

# Parse allowed user IDs (comma-separated)
if ALLOWED_USER_IDS:
    ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS.split(",") if uid.strip().isdigit()]
else:
    ALLOWED_USER_IDS = []

# Instagram Credentials (optional)
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")
# Path where the instaloader session cookie is cached (avoids re-login on every restart)
INSTAGRAM_SESSION_FILE = Path(os.getenv("INSTAGRAM_SESSION_FILE", "./data/instagram_session"))

# YouTube Cookies (optional, for private videos)
YOUTUBE_COOKIES_PATH = os.getenv("YOUTUBE_COOKIES_PATH", "")

# Download Settings
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Quality Settings
MAX_VIDEO_QUALITY = os.getenv("MAX_VIDEO_QUALITY", "2160p")
PREFERRED_QUALITY = os.getenv("PREFERRED_QUALITY", "best")

# File Server Settings (for local download links)
ENABLE_FILE_SERVER = os.getenv("ENABLE_FILE_SERVER", "true").lower() == "true"
FILE_SERVER_PORT = int(os.getenv("FILE_SERVER_PORT", "8080"))
FILE_SERVER_HOST = os.getenv("FILE_SERVER_HOST", "localhost")

# Upload concurrency for playlist uploads (2 is safe under Telegram flood limits)
MAX_CONCURRENT_UPLOADS = int(os.getenv("MAX_CONCURRENT_UPLOADS", "2"))

# Cloud Bot API upload limit per file (MB). Premium user accounts do NOT raise this for bots.
# If you run a local Bot API server, you can increase this to match that server's limit.
# See https://core.telegram.org/bots/api#using-a-local-bot-api-server
MAX_BOT_UPLOAD_MB = int(os.getenv("MAX_BOT_UPLOAD_MB", "50"))
MAX_BOT_UPLOAD_BYTES = MAX_BOT_UPLOAD_MB * 1024 * 1024

# Worker pool sizes for the async queue manager
ANALYZE_WORKERS  = int(os.getenv("ANALYZE_WORKERS",  "3"))   # concurrent URL analyze (get_video_info) jobs
DOWNLOAD_WORKERS = int(os.getenv("DOWNLOAD_WORKERS", "3"))   # concurrent download jobs
UPLOAD_WORKERS   = int(os.getenv("UPLOAD_WORKERS",   "2"))   # concurrent upload jobs

# Auto-cleanup: delete downloaded files older than this many days (0 = disabled)
FILE_CLEANUP_DAYS = int(os.getenv("FILE_CLEANUP_DAYS", "7"))

# Quality mapping for yt-dlp
# "60" suffix = high-frame-rate variant (fps > 50).
# Standard variants cap fps at <=55 so they don't accidentally grab the 60fps DASH stream.
QUALITY_FORMAT = {
    "best":    "bestvideo+bestaudio/best",
    "2160p60": "bestvideo[height<=2160][fps>50]+bestaudio/bestvideo[height<=2160]+bestaudio",
    "2160p":   "bestvideo[height<=2160][fps<=55]+bestaudio/bestvideo[height<=2160]+bestaudio",
    "1440p60": "bestvideo[height<=1440][fps>50]+bestaudio/bestvideo[height<=1440]+bestaudio",
    "1440p":   "bestvideo[height<=1440][fps<=55]+bestaudio/bestvideo[height<=1440]+bestaudio",
    "1080p60": "bestvideo[height<=1080][fps>50]+bestaudio/bestvideo[height<=1080]+bestaudio",
    "1080p":   "bestvideo[height<=1080][fps<=55]+bestaudio/bestvideo[height<=1080]+bestaudio",
    "720p60":  "bestvideo[height<=720][fps>50]+bestaudio/bestvideo[height<=720]+bestaudio",
    "720p":    "bestvideo[height<=720][fps<=55]+bestaudio/bestvideo[height<=720]+bestaudio",
    "480p":    "bestvideo[height<=480]+bestaudio/bestvideo[height<=480]+bestaudio",
    "360p":    "bestvideo[height<=360]+bestaudio/bestvideo[height<=360]+bestaudio",
    "240p":    "bestvideo[height<=240]+bestaudio/bestvideo[height<=240]+bestaudio",
    "audio":   "bestaudio/best",
}

