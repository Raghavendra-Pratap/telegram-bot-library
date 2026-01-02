"""
Configuration management for Telegram Download Accelerator Bot
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot API Token
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# MTProto API Credentials (for premium account)
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "premium_account")

# User Access Control
ENABLE_USER_VERIFICATION = os.getenv("ENABLE_USER_VERIFICATION", "false").lower() == "true"
ALLOWED_USER_IDS = os.getenv("ALLOWED_USER_IDS", "").strip()

# Parse allowed user IDs (comma-separated) - Legacy support
# Note: If using dynamic user management, this is ignored
if ALLOWED_USER_IDS:
    ALLOWED_USER_IDS = [int(uid.strip()) for uid in ALLOWED_USER_IDS.split(",") if uid.strip().isdigit()]
else:
    ALLOWED_USER_IDS = []

# Dynamic User Management (preferred over hardcoded IDs)
USE_DYNAMIC_USER_MANAGEMENT = os.getenv("USE_DYNAMIC_USER_MANAGEMENT", "true").lower() == "true"
USERS_FILE = Path(os.getenv("USERS_FILE", "allowed_users.json"))

# Download Settings
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "./downloads"))
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# File Server Settings (for direct downloads)
ENABLE_FILE_SERVER = os.getenv("ENABLE_FILE_SERVER", "true").lower() == "true"
FILE_SERVER_HOST = os.getenv("FILE_SERVER_HOST", "0.0.0.0")
FILE_SERVER_PORT = int(os.getenv("FILE_SERVER_PORT", "8080"))
FILE_SERVER_BASE_URL = os.getenv("FILE_SERVER_BASE_URL", f"http://localhost:{FILE_SERVER_PORT}")

# File Retention (in hours)
FILE_RETENTION_HOURS = int(os.getenv("FILE_RETENTION_HOURS", "24"))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
