"""
Configuration management
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration"""
    
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    API_ID = os.getenv('API_ID')
    API_HASH = os.getenv('API_HASH')
    TMDB_API_KEY = os.getenv('TMDB_API_KEY', '')
    
    # Admin user IDs (comma-separated)
    admin_ids_str = os.getenv('ADMIN_USER_IDS', '')
    ADMIN_USER_IDS = [int(uid.strip()) for uid in admin_ids_str.split(',') if uid.strip()] if admin_ids_str else []
    
    # Database: use DATABASE_URL for PostgreSQL (takes precedence), else SQLite file.
    # Example: postgresql+psycopg://user:password@localhost:5432/index_bot
    DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
    DB_PATH = os.getenv('DB_PATH', 'index_bot.db')

    # Public watch/delivery channel (bot must be admin). Comma-separated id or @username.
    WATCH_CHANNEL_ID = os.getenv('WATCH_CHANNEL_ID', '').strip()
    # Copy library files into the watch channel when they become library-visible.
    AUTO_PUBLISH_WATCH = os.getenv('AUTO_PUBLISH_WATCH', '').lower() in (
        '1',
        'true',
        'yes',
    )

    # Bot API flood control (seconds between calls; publish batch gap; max retries).
    TELEGRAM_MIN_API_INTERVAL = float(os.getenv('TELEGRAM_MIN_API_INTERVAL', '0.45'))
    TELEGRAM_PUBLISH_DELAY = float(os.getenv('TELEGRAM_PUBLISH_DELAY', '3.0'))
    TELEGRAM_FLOOD_MAX_RETRIES = int(os.getenv('TELEGRAM_FLOOD_MAX_RETRIES', '12'))
    TELEGRAM_EDIT_MAX_RETRIES = int(os.getenv('TELEGRAM_EDIT_MAX_RETRIES', '4'))

    # Background job queue (retries apply to transient TMDB/network failures in workers).
    JOB_MAX_RETRIES = int(os.getenv('JOB_MAX_RETRIES', '12'))
    JOB_QUEUE_INTERACTIVE_WORKERS = int(os.getenv('JOB_QUEUE_INTERACTIVE_WORKERS', '2'))
    JOB_QUEUE_BACKGROUND_WORKERS = int(os.getenv('JOB_QUEUE_BACKGROUND_WORKERS', '2'))
    JOB_QUEUE_INGEST_WORKERS = int(os.getenv('JOB_QUEUE_INGEST_WORKERS', '1'))

    # Watch catalog publish: cards per Telegram API chunk; 0 max = drain full queue in one job.
    WATCH_CATALOG_PUBLISH_BATCH_SIZE = int(
        os.getenv('WATCH_CATALOG_PUBLISH_BATCH_SIZE', '50')
    )
    WATCH_CATALOG_PUBLISH_MAX_TOTAL = int(
        os.getenv('WATCH_CATALOG_PUBLISH_MAX_TOTAL', '0')
    )

    CHANNEL_PICKER_PAGE_SIZE = int(os.getenv('CHANNEL_PICKER_PAGE_SIZE', '15'))
    PENDING_SCAN_LIMIT = int(os.getenv('PENDING_SCAN_LIMIT', '25000'))
    PENDING_BATCH_PAGE_SIZE = int(os.getenv('PENDING_BATCH_PAGE_SIZE', '12'))
    TMDB_INGEST_RETRY_ATTEMPTS = int(os.getenv('TMDB_INGEST_RETRY_ATTEMPTS', '4'))
    
    @classmethod
    def is_admin(cls, user_id):
        """Check if user is admin"""
        return user_id in cls.ADMIN_USER_IDS
    
    @classmethod
    def validate(cls):
        """Validate configuration"""
        if not cls.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required in .env file")
        return True
