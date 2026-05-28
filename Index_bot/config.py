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

    # Telethon: one queued client in bot (avoids forward_ingest.session lock).
    TELETHON_GATEWAY_ENABLED = os.getenv('TELETHON_GATEWAY_ENABLED', 'true').strip().lower() in (
        '1',
        'true',
        'yes',
    )
    # Portal uses its own session file so stream + bot upload never share one SQLite session.
    TELETHON_PORTAL_SESSION = os.getenv('TELETHON_PORTAL_SESSION', 'forward_ingest_portal.session').strip()

    # Public watch/delivery channel (bot must be admin). Comma-separated id or @username.
    WATCH_CHANNEL_ID = os.getenv('WATCH_CHANNEL_ID', '').strip()
    # Optional per-lane public catalog/delivery channels (fallback: WATCH_CHANNEL_ID).
    WATCH_CHANNEL_COURSE_ID = os.getenv('WATCH_CHANNEL_COURSE_ID', '').strip()
    WATCH_CHANNEL_SHORTFORM_ID = os.getenv('WATCH_CHANNEL_SHORTFORM_ID', '').strip()
    WATCH_CHANNEL_ARCHIVE_ID = os.getenv('WATCH_CHANNEL_ARCHIVE_ID', '').strip()
    # Optional @username for down_oad_bot (external URL download helper button on delivery).
    DOWN_OAD_BOT_USERNAME = os.getenv('DOWN_OAD_BOT_USERNAME', '').strip()
    # Use SHA-256 when planning uploads from local disk (upload_planner.py).
    UPLOAD_PLANNER_USE_SHA256 = os.getenv('UPLOAD_PLANNER_USE_SHA256', '').lower() in (
        '1',
        'true',
        'yes',
    )
    # Copy library files into the watch channel when they become library-visible.
    AUTO_PUBLISH_WATCH = os.getenv('AUTO_PUBLISH_WATCH', '').lower() in (
        '1',
        'true',
        'yes',
    )
    # Classify lane from filename on mixed ingest sink (not channel staging default).
    PIPELINE_CLASSIFY_INGEST = os.getenv('PIPELINE_CLASSIFY_INGEST', 'true').lower() in (
        '1',
        'true',
        'yes',
    )
    # Forward indexed ingest posts to pipeline source channel for detected lane.
    PIPELINE_AUTO_ROUTE = os.getenv('PIPELINE_AUTO_ROUTE', '').lower() in (
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

    # Watch portal (web UI) — run: python run_portal.py
    PORTAL_HOST = os.getenv('PORTAL_HOST', '127.0.0.1')
    PORTAL_PORT = int(os.getenv('PORTAL_PORT', '8765'))
    PORTAL_PUBLIC_URL = os.getenv('PORTAL_PUBLIC_URL', '').strip()

    CHANNEL_PICKER_PAGE_SIZE = int(os.getenv('CHANNEL_PICKER_PAGE_SIZE', '15'))
    PENDING_SCAN_LIMIT = int(os.getenv('PENDING_SCAN_LIMIT', '25000'))
    PENDING_BATCH_PAGE_SIZE = int(os.getenv('PENDING_BATCH_PAGE_SIZE', '12'))
    TMDB_INGEST_RETRY_ATTEMPTS = int(os.getenv('TMDB_INGEST_RETRY_ATTEMPTS', '4'))
    # Background TMDB retry queue (pending files after API/network errors).
    TMDB_RETRY_BATCH_SIZE = int(os.getenv('TMDB_RETRY_BATCH_SIZE', '8'))
    TMDB_RETRY_INTERVAL_S = float(os.getenv('TMDB_RETRY_INTERVAL_S', '2.5'))
    TMDB_RETRY_TICK_S = float(os.getenv('TMDB_RETRY_TICK_S', '45'))
    TMDB_RETRY_STAGGER_S = float(os.getenv('TMDB_RETRY_STAGGER_S', '2'))
    TMDB_RETRY_MAX_ATTEMPTS = int(os.getenv('TMDB_RETRY_MAX_ATTEMPTS', '8'))
    # Multi-cycle bulk retry campaign (live progress + several passes).
    TMDB_RETRY_CAMPAIGN_MAX_CYCLES = int(os.getenv('TMDB_RETRY_CAMPAIGN_MAX_CYCLES', '5'))
    TMDB_RETRY_CAMPAIGN_CYCLE_PAUSE_S = float(
        os.getenv('TMDB_RETRY_CAMPAIGN_CYCLE_PAUSE_S', '90')
    )
    TMDB_RETRY_CAMPAIGN_PROGRESS_S = float(
        os.getenv('TMDB_RETRY_CAMPAIGN_PROGRESS_S', '30')
    )
    TMDB_RETRY_CAMPAIGN_WAVE_SIZE = int(os.getenv('TMDB_RETRY_CAMPAIGN_WAVE_SIZE', '128'))
    # Faster worker while a bulk campaign is active (see .env.example for tradeoffs).
    TMDB_CAMPAIGN_TICK_S = float(os.getenv('TMDB_CAMPAIGN_TICK_S', '15'))
    TMDB_CAMPAIGN_BATCH_SIZE = int(os.getenv('TMDB_CAMPAIGN_BATCH_SIZE', '16'))
    TMDB_CAMPAIGN_INTERVAL_S = float(os.getenv('TMDB_CAMPAIGN_INTERVAL_S', '1.2'))
    TMDB_CAMPAIGN_BURST_TICKS = int(os.getenv('TMDB_CAMPAIGN_BURST_TICKS', '5'))
    # TMDB pick UI (pending / portal): more results; includes TV + movie when ambiguous.
    TMDB_PICK_SUGGESTION_LIMIT = int(os.getenv('TMDB_PICK_SUGGESTION_LIMIT', '12'))
    TMDB_PICK_PAGE_SIZE = int(os.getenv('TMDB_PICK_PAGE_SIZE', '8'))
    TMDB_PICK_TELEGRAM_CARDS = int(os.getenv('TMDB_PICK_TELEGRAM_CARDS', '10'))

    # Telethon poll for new posts in registered channels where the bot is not admin.
    TELETHON_MEMBER_WATCH_ENABLED = os.getenv(
        'TELETHON_MEMBER_WATCH_ENABLED', 'true'
    ).lower() in ('1', 'true', 'yes')
    TELETHON_MEMBER_WATCH_INTERVAL_S = float(
        os.getenv('TELETHON_MEMBER_WATCH_INTERVAL_S', '300')
    )
    TELETHON_MEMBER_WATCH_BATCH = int(os.getenv('TELETHON_MEMBER_WATCH_BATCH', '40'))
    
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
