"""
Configuration management for the Telegram File Upload Bot
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

# Upload Settings
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
UPLOAD_DIR.mkdir(exist_ok=True)

# Temporary staging directory
STAGING_DIR = Path(os.getenv("STAGING_DIR", "./staging"))
STAGING_DIR.mkdir(exist_ok=True)

# Default Upload Settings
DEFAULT_UPLOAD_AS = os.getenv("DEFAULT_UPLOAD_AS", "auto")  # auto, document, photo, video, audio
DEFAULT_VIDEO_QUALITY = os.getenv("DEFAULT_VIDEO_QUALITY", "HD")  # HD, high, standard, low
DEFAULT_GROUP_STYLE = os.getenv("DEFAULT_GROUP_STYLE", "media_group")  # media_group, sequential

# File Size Limits (in bytes)
MAX_FILE_SIZE_FREE = 50 * 1024 * 1024  # 50MB for free accounts
MAX_FILE_SIZE_PREMIUM = 4 * 1024 * 1024 * 1024  # 4GB for premium

# Upload Rate Limiting
UPLOAD_DELAY = float(os.getenv("UPLOAD_DELAY", "1.0"))  # Delay between uploads (seconds)
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "10"))  # Files per batch

# Google Sheets Configuration
GOOGLE_SHEETS_CREDENTIALS_PATH = os.getenv("GOOGLE_SHEETS_CREDENTIALS_PATH", "")
GOOGLE_SHEETS_SERVICE_ACCOUNT = os.getenv("GOOGLE_SHEETS_SERVICE_ACCOUNT", "false").lower() == "true"

# Metadata Settings
METADATA_MATCH_STRATEGY = os.getenv("METADATA_MATCH_STRATEGY", "exact")  # exact, path, fuzzy
ENABLE_FUZZY_MATCHING = os.getenv("ENABLE_FUZZY_MATCHING", "false").lower() == "true"

# Tree Display Settings
SHOW_TREE_IN_CAPTION = os.getenv("SHOW_TREE_IN_CAPTION", "true").lower() == "true"
SHOW_TREE_SEPARATOR = os.getenv("SHOW_TREE_SEPARATOR", "false").lower() == "true"
TREE_SEPARATOR_FORMAT = os.getenv("TREE_SEPARATOR_FORMAT", "📁 {path}")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

