"""
Comprehensive readiness check for the bot
"""
import os
import sys

def check_files():
    """Check if all required files exist"""
    required_files = [
        'bot.py',
        'config.py',
        'database.py',
        'name_parser.py',
        'requirements.txt',
        'forward_ingest.py',
        '.env.example',
    ]
    
    missing = []
    for file in required_files:
        if not os.path.exists(file):
            missing.append(file)
        else:
            print(f"✅ {file}")
    
    if missing:
        print(f"\n❌ Missing files: {', '.join(missing)}")
        return False
    return True

def check_dependencies():
    """Check if all dependencies are installed"""
    try:
        import telegram
        print("✅ python-telegram-bot")
    except ImportError:
        print("❌ python-telegram-bot not installed")
        return False
    
    try:
        import sqlalchemy
        print(f"✅ sqlalchemy (version: {sqlalchemy.__version__})")
    except ImportError:
        print("❌ sqlalchemy not installed")
        return False
    
    try:
        from dotenv import load_dotenv
        print("✅ python-dotenv")
    except ImportError:
        print("❌ python-dotenv not installed")
        return False
    
    try:
        import telethon
        print(f"✅ telethon (version: {telethon.__version__})")
    except ImportError:
        print("❌ telethon not installed")
        return False

    try:
        import psycopg
        print(f"✅ psycopg (version: {psycopg.__version__})")
    except ImportError:
        print("❌ psycopg not installed")
        return False

    return True

def check_modules():
    """Check if all project modules can be imported"""
    try:
        from config import Config
        print("✅ config module")
    except Exception as e:
        print(f"❌ config module: {e}")
        return False
    
    try:
        from database import Database, Channel, FileUpload
        print("✅ database module")
    except Exception as e:
        print(f"❌ database module: {e}")
        return False
    
    try:
        from name_parser import NameParser
        print("✅ name_parser module")
    except Exception as e:
        print(f"❌ name_parser module: {e}")
        return False
    
    try:
        # Test database initialization
        from config import Config
        from database import Database
        db = Database()
        print("✅ database initialization")
    except Exception as e:
        print(f"❌ database initialization: {e}")
        return False
    
    return True

def check_env():
    """Check .env file"""
    if os.path.exists('.env'):
        print("✅ .env file exists")
        
        # Try to load and validate
        try:
            from config import Config
            try:
                Config.validate()
                print("✅ .env file is valid (BOT_TOKEN found)")
                
                if Config.ADMIN_USER_IDS:
                    print(f"✅ Admin user IDs configured ({len(Config.ADMIN_USER_IDS)} admin(s))")
                else:
                    print("⚠️  No admin user IDs configured (add ADMIN_USER_IDS to .env)")
                
                return True
            except ValueError as e:
                print(f"⚠️  .env file exists but: {e}")
                return False
        except Exception as e:
            print(f"⚠️  Error loading .env: {e}")
            return False
    else:
        print("⚠️  .env file not found")
        print("   Create it using: python create_env.py")
        print("   Or manually create .env with BOT_TOKEN and ADMIN_USER_IDS")
        return False

def check_syntax():
    """Check Python syntax"""
    import py_compile
    
    files_to_check = ['bot.py', 'config.py', 'database.py', 'name_parser.py', 'forward_ingest.py']
    for file in files_to_check:
        try:
            py_compile.compile(file, doraise=True)
            print(f"✅ {file} syntax valid")
        except py_compile.PyCompileError as e:
            print(f"❌ {file} syntax error: {e}")
            return False
    
    return True

def main():
    """Run all checks"""
    print("=" * 60)
    print("Index Bot - Readiness Check")
    print("=" * 60)
    print()
    
    checks = [
        ("Required Files", check_files),
        ("Dependencies", check_dependencies),
        ("Python Syntax", check_syntax),
        ("Project Modules", check_modules),
        ("Environment Configuration", check_env),
    ]
    
    results = {}
    for name, check_func in checks:
        print(f"\n[{name}]")
        print("-" * 60)
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"❌ Error during check: {e}")
            results[name] = False
    
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if not passed:
            all_passed = False
    
    print()
    if all_passed:
        print("🎉 All checks passed! Bot is ready to run.")
        print("\nTo start the bot:")
        print("  source venv/bin/activate")
        print("  python bot.py")
    else:
        print("⚠️  Some checks failed. Please fix the issues above.")
        if not results.get("Environment Configuration", False):
            print("\n💡 Tip: Create .env file using: python create_env.py")
    
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
