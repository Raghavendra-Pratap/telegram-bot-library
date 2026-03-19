"""
Helper script to create .env file interactively
"""
import os

def create_env_file():
    """Create .env file with user input"""
    env_path = '.env'
    
    if os.path.exists(env_path):
        response = input(f"{env_path} already exists. Overwrite? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return
    
    print("\n" + "="*60)
    print("Index Bot - Environment Setup")
    print("="*60)
    print("\nYou'll need:")
    print("1. Bot Token from @BotFather on Telegram")
    print("2. Your Telegram User ID from @userinfobot")
    print("3. (Optional) TMDB API Key from https://www.themoviedb.org/settings/api")
    print("4. (Optional) Telegram API ID and Hash from https://my.telegram.org/apps")
    print("\n" + "-"*60 + "\n")
    
    bot_token = input("Enter your BOT_TOKEN (required): ").strip()
    if not bot_token:
        print("❌ Bot token is required!")
        return
    
    admin_ids = input("Enter ADMIN_USER_IDS (comma-separated, e.g., 123456789): ").strip()
    
    api_id = input("Enter API_ID (optional, press Enter to skip): ").strip()
    api_hash = input("Enter API_HASH (optional, press Enter to skip): ").strip()
    tmdb_key = input("Enter TMDB_API_KEY (optional, press Enter to skip): ").strip()
    
    db_path = input("Enter DB_PATH (default: index_bot.db, press Enter for default): ").strip()
    if not db_path:
        db_path = "index_bot.db"
    
    # Create .env content
    env_content = f"""# Telegram Bot Configuration
BOT_TOKEN={bot_token}

# Telegram API (optional)
API_ID={api_id if api_id else 'your_telegram_api_id'}
API_HASH={api_hash if api_hash else 'your_telegram_api_hash'}

# TMDB API Key (optional)
TMDB_API_KEY={tmdb_key if tmdb_key else 'your_tmdb_api_key'}

# Admin User IDs (comma-separated)
ADMIN_USER_IDS={admin_ids if admin_ids else ''}

# Database path
DB_PATH={db_path}
"""
    
    try:
        with open(env_path, 'w') as f:
            f.write(env_content)
        print(f"\n✅ {env_path} file created successfully!")
        print("\nNext steps:")
        print("1. Add your bot as admin to the channels you want to monitor")
        print("2. Run: source venv/bin/activate && python bot.py")
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")

if __name__ == '__main__':
    create_env_file()
