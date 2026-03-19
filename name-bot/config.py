"""
Configuration management for the Upload with Caption Bot
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

# Parallel processing configuration
# Maximum number of concurrent file processing tasks
# Telegram allows ~20-30 messages/second, so 10-15 concurrent tasks is safe
# Higher values = faster processing but higher risk of rate limits
MAX_CONCURRENT_TASKS = int(os.getenv("MAX_CONCURRENT_TASKS", "10"))  # Default: 10 concurrent tasks

# Enable concurrent updates (allows processing multiple updates simultaneously)
# Set to True for parallel processing, False for sequential processing
ENABLE_CONCURRENT_UPDATES = os.getenv("ENABLE_CONCURRENT_UPDATES", "true").lower() == "true"

# Minimum delay between API calls within the same task (in seconds)
# This prevents too many rapid API calls from a single task
# Lower values = faster but may hit rate limits, higher = safer but slower
MIN_API_CALL_DELAY = float(os.getenv("MIN_API_CALL_DELAY", "0.1"))  # Default: 100ms between API calls

# Auto-shutdown configuration (for resource-saving hosting)
# Idle timeout in minutes - bot will shut down after this period of inactivity
# Set to 0 to disable auto-shutdown (bot runs continuously)
# Recommended: 10-15 minutes for free hosting platforms
IDLE_TIMEOUT_MINUTES = float(os.getenv("IDLE_TIMEOUT_MINUTES", "12"))  # Default: 12 minutes

# Enable auto-shutdown feature
# Set to true to enable idle timeout and auto-shutdown
# Set to false to run bot continuously (traditional mode)
ENABLE_AUTO_SHUTDOWN = os.getenv("ENABLE_AUTO_SHUTDOWN", "true").lower() == "true"

# HTTP server configuration (local health checks and wake-up)
# Port for HTTP health check server (useful for LAN monitoring)
# If PORT is set by a process manager, use it; otherwise use HTTP_SERVER_PORT
HTTP_SERVER_PORT = int(os.getenv("PORT", os.getenv("HTTP_SERVER_PORT", "8080")))  # Default: 8080

# Enable HTTP server for health checks and wake-up
# This allows local monitors to ping the bot and reset the idle timer
ENABLE_HTTP_SERVER = os.getenv("ENABLE_HTTP_SERVER", "true").lower() == "true"

# Update queue configuration
# Enable processing of missed updates when bot restarts
# When enabled, bot will fetch and process updates that arrived while bot was offline
ENABLE_UPDATE_QUEUE = os.getenv("ENABLE_UPDATE_QUEUE", "true").lower() == "true"

# Maximum number of updates to process from queue on startup
# Telegram stores updates for up to 24 hours
# Higher values = process more missed updates, but slower startup
MAX_QUEUE_UPDATES = int(os.getenv("MAX_QUEUE_UPDATES", "100"))  # Default: 100 updates
