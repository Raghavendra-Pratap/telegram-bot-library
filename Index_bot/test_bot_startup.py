"""
Test script to verify bot can initialize
"""
import sys
import os

# Suppress output for testing
import logging
logging.getLogger().setLevel(logging.ERROR)

try:
    from config import Config
    print("✅ Config imported")
    
    Config.validate()
    print("✅ Config validated")
    
    from telegram.ext import Application
    print("✅ Application imported")
    
    # Try to create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    print("✅ Application created successfully")
    
    print("\n🎉 Bot can initialize! All checks passed.")
    sys.exit(0)
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
