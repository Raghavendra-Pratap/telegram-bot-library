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

# Parse allowed user IDs (comma-separated)
if ALLOWED_USER_IDS:
    ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS.split(",") if uid.strip().isdigit()]
else:
    ALLOWED_USER_IDS = []

# Instagram Credentials (optional)
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME", "")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD", "")

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

# Quality mapping for yt-dlp
QUALITY_FORMAT = {
    "2160p": "bestvideo[height<=2160]+bestaudio/best[height<=2160]",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "best": "bestvideo+bestaudio/best",
    "audio": "bestaudio/best"
}

