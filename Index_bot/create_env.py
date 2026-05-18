"""
Helper script to create .env file interactively
"""
import argparse
import os
import sys


def _prompt_overwrite(env_path: str, yes_overwrite: bool) -> bool:
    if not os.path.exists(env_path):
        return True
    if yes_overwrite:
        return True
    try:
        response = input(f"{env_path} already exists. Overwrite? (y/n): ")
    except EOFError:
        print(
            "\nNo input (non-interactive). Existing .env was not changed.\n"
            "Run in a real terminal:  python create_env.py\n"
            "Or overwrite without asking:  python create_env.py -y"
        )
        return False
    return response.lower() == "y"


def create_env_file(*, yes_overwrite: bool = False) -> None:
    """Create .env file with user input"""
    env_path = ".env"

    if not _prompt_overwrite(env_path, yes_overwrite):
        print("Cancelled.")
        return

    print("\n" + "=" * 60)
    print("Index Bot - Environment Setup")
    print("=" * 60)
    if os.path.exists(".env.example"):
        print("\nTip: you can skip this wizard and copy the template:  cp .env.example .env")
    print("\nYou'll need:")
    print("1. Bot Token from @BotFather on Telegram")
    print("2. Your Telegram User ID from @userinfobot")
    print("3. (Optional) TMDB API Key from https://www.themoviedb.org/settings/api")
    print("4. API ID and Hash from https://my.telegram.org/apps (needed for forward_ingest.py history import)")
    print("\n" + "-" * 60 + "\n")

    def _ask(label: str) -> str:
        try:
            return input(label).strip()
        except EOFError:
            print("\n❌ EOF: run this script in an interactive terminal (Cursor/Terminal tab).")
            sys.exit(1)

    bot_token = _ask("Enter your BOT_TOKEN (required): ")
    if not bot_token:
        print("❌ Bot token is required!")
        return

    admin_ids = _ask("Enter ADMIN_USER_IDS (comma-separated, e.g., 123456789): ")

    api_id = _ask(
        "Enter API_ID (for forward_ingest.py — get from my.telegram.org, optional but recommended): "
    )
    api_hash = _ask("Enter API_HASH (optional but recommended): ")
    tmdb_key = _ask("Enter TMDB_API_KEY (optional, press Enter to skip): ")

    db_path = _ask("Enter DB_PATH (default: index_bot.db, press Enter for default): ")
    if not db_path:
        db_path = "index_bot.db"

    env_content = f"""# Telegram Bot Configuration
BOT_TOKEN={bot_token}

# Telegram API (needed for forward_ingest.py / Telethon user session)
API_ID={api_id if api_id else 'your_telegram_api_id'}
API_HASH={api_hash if api_hash else 'your_telegram_api_hash'}

# Optional: Telethon session path for forward_ingest.py (default: forward_ingest.session)
# FORWARD_INGEST_SESSION=forward_ingest.session

# TMDB API Key (optional)
TMDB_API_KEY={tmdb_key if tmdb_key else 'your_tmdb_api_key'}

# Admin User IDs (comma-separated)
ADMIN_USER_IDS={admin_ids if admin_ids else ''}

# Database: SQLite path when DATABASE_URL is not set
DB_PATH={db_path}

# PostgreSQL (optional — if set, DB_PATH is ignored). URL-encode special chars in password.
# DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/index_bot
"""

    try:
        with open(env_path, "w") as f:
            f.write(env_content)
        print(f"\n✅ {env_path} file created successfully!")
        print("\nNext steps:")
        print("1. Add your bot as admin to the channels you want to monitor")
        print("2. Run: source venv/bin/activate && python bot.py")
        print("3. To import old uploads: configure API_ID/API_HASH and run python forward_ingest.py (see HOW_TO_RUN.md)")
    except Exception as e:
        print(f"❌ Error creating .env file: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Index_bot .env interactively.")
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Overwrite existing .env without asking (still requires interactive prompts for secrets)",
    )
    args = parser.parse_args()

    if not sys.stdin.isatty():
        print(
            "create_env.py must run in an interactive terminal (stdin is not a TTY).\n\n"
            "In Cursor: Terminal → New Terminal, then:\n"
            "  cd Index_bot && source venv/bin/activate && python create_env.py\n\n"
            "Or copy the template:\n"
            "  cp .env.example .env\n"
        )
        sys.exit(1)

    create_env_file(yes_overwrite=args.yes)


if __name__ == "__main__":
    main()
