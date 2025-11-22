#!/usr/bin/env python3
"""
Quick setup test script
Checks if all dependencies are installed correctly
"""
import sys
import subprocess
from pathlib import Path

def check_python():
    """Check Python version"""
    print("✅ Python version:", sys.version.split()[0])
    return True

def check_module(module_name):
    """Check if a Python module is installed"""
    try:
        __import__(module_name)
        print(f"✅ {module_name} installed")
        return True
    except ImportError:
        print(f"❌ {module_name} NOT installed")
        return False

def check_ffmpeg():
    """Check if FFmpeg is installed"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            version = result.stdout.split('\n')[0]
            print(f"✅ FFmpeg installed: {version}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ FFmpeg NOT found")
        return False
    return False

def check_env_file():
    """Check if .env file exists and has token"""
    env_path = Path('.env')
    if not env_path.exists():
        print("❌ .env file NOT found")
        print("   Run: cp env_template.txt .env")
        return False
    
    content = env_path.read_text()
    if 'your_bot_token_here' in content or 'TELEGRAM_BOT_TOKEN=' not in content:
        print("⚠️  .env file exists but token not configured")
        print("   Edit .env and add your TELEGRAM_BOT_TOKEN")
        return False
    
    print("✅ .env file configured")
    return True

def main():
    print("=" * 50)
    print("Telegram Bot Setup Test")
    print("=" * 50)
    print()
    
    all_ok = True
    
    # Check Python
    check_python()
    print()
    
    # Check Python modules
    print("Checking Python modules...")
    modules = [
        'telegram',
        'yt_dlp',
        'instaloader',
        'requests',
        'aiohttp',
        'dotenv'
    ]
    
    for module in modules:
        if not check_module(module):
            all_ok = False
    print()
    
    # Check FFmpeg
    print("Checking FFmpeg...")
    if not check_ffmpeg():
        all_ok = False
    print()
    
    # Check .env
    print("Checking configuration...")
    if not check_env_file():
        all_ok = False
    print()
    
    # Summary
    print("=" * 50)
    if all_ok:
        print("✅ All checks passed! You're ready to run the bot.")
        print()
        print("Next steps:")
        print("1. Make sure .env has your TELEGRAM_BOT_TOKEN")
        print("2. Run: python bot.py")
    else:
        print("❌ Some checks failed. Please fix the issues above.")
    print("=" * 50)

if __name__ == "__main__":
    main()

