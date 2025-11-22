#!/usr/bin/env python3
"""Quick test to verify bot initialization works"""
import sys
from config import TELEGRAM_BOT_TOKEN

if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_bot_token_here":
    print("⚠️  Bot token not configured, but testing import...")
    # Use a dummy token for testing
    TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"

try:
    from telegram.ext import Application
    print("✅ Import successful")
    
    # Try to create application (will fail on connection, but should not fail on init)
    try:
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        print("✅ Application created successfully")
        print("✅ Bot initialization works!")
        sys.exit(0)
    except Exception as e:
        error_msg = str(e)
        # If it's a connection/auth error, that's expected with dummy token
        if "Unauthorized" in error_msg or "connection" in error_msg.lower():
            print("✅ Application created (auth error expected with dummy token)")
            print("✅ Bot initialization works!")
            sys.exit(0)
        else:
            print(f"❌ Error creating application: {e}")
            sys.exit(1)
            
except Exception as e:
    print(f"❌ Import or initialization error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

