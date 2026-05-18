"""
Setup verification script
"""
import os
import sys

def check_env_file():
    """Check if .env file exists"""
    if not os.path.exists('.env'):
        print("❌ .env file not found!")
        print("📝 Please create a .env file based on .env.example")
        return False
    print("✅ .env file exists")
    return True

def check_dependencies():
    """Check if required packages are installed"""
    required_packages = [
        'telegram',
        'sqlalchemy',
        'dotenv'
    ]
    
    missing = []
    for package in required_packages:
        try:
            if package == 'telegram':
                __import__('telegram')
            elif package == 'dotenv':
                __import__('dotenv')
            elif package == 'sqlalchemy':
                __import__('sqlalchemy')
            print(f"✅ {package} is installed")
        except ImportError:
            print(f"❌ {package} is not installed")
            missing.append(package)
    
    if missing:
        print(f"\n📦 Install missing packages with: pip install -r requirements.txt")
        return False
    
    return True

def check_config():
    """Check if configuration is valid"""
    try:
        from config import Config
        Config.validate()
        print("✅ Configuration is valid")
        
        if not Config.ADMIN_USER_IDS:
            print("⚠️  Warning: No admin user IDs configured")
            print("   Add ADMIN_USER_IDS to .env file")
        else:
            print(f"✅ {len(Config.ADMIN_USER_IDS)} admin user(s) configured")
        
        return True
    except Exception as e:
        print(f"❌ Configuration error: {e}")
        return False

def main():
    """Run all checks"""
    print("=" * 60)
    print("Index Bot Setup Verification")
    print("=" * 60)
    print()
    
    checks = [
        ("Environment File", check_env_file),
        ("Dependencies", check_dependencies),
        ("Configuration", check_config)
    ]
    
    all_passed = True
    for name, check_func in checks:
        print(f"\n[{name}]")
        if not check_func():
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All checks passed! You can run the bot with: python bot.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
    print("=" * 60)
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
