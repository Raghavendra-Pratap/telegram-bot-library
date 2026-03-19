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
    
    # Database path
    DB_PATH = os.getenv('DB_PATH', 'index_bot.db')
    
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
