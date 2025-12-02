"""
Configuration management for the Telegram Name Bot
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

# Retry configuration
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2.0"))  # Delay between retries in seconds (increased for large batches)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))  # Maximum number of retry attempts (increased for flood control)

# Filename handling
# If True, skip adding caption when original filename is not available (mobile uploads)
# If False, use generated filename (file_id based) as caption
SKIP_IF_NO_FILENAME = os.getenv("SKIP_IF_NO_FILENAME", "false").lower() == "true"

# Rate limiting
# Delay between processing files to avoid hitting rate limits (in seconds)
# Increase this if you're processing many files at once
# Recommended: 1.0 for <50 files, 2.0 for 50-100 files, 3.0 for 100+ files
PROCESSING_DELAY = float(os.getenv("PROCESSING_DELAY", "2.0"))  # Default: 2 seconds between files (optimized for 100 files)

# Flood control retry configuration
# When flood control is hit, wait longer before retrying
FLOOD_RETRY_DELAY_MULTIPLIER = float(os.getenv("FLOOD_RETRY_DELAY_MULTIPLIER", "1.5"))  # Multiply wait time by this factor

