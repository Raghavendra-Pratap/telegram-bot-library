"""
Full startup test for the bot
"""
import sys
import asyncio
from config import Config
from telegram.ext import Application

async def test():
    try:
        print("Testing bot startup...")
        Config.validate()
        print("✅ Config validated")
        
        application = Application.builder().token(Config.BOT_TOKEN).build()
        print("✅ Application created")
        
        # Test if we can access bot methods
        bot = application.bot
        print(f"✅ Bot instance: {type(bot).__name__}")
        print("ℹ️  Historical ingest uses forward_ingest.py (Telethon); Bot API has no chat history.")
        
        print("\n🎉 Bot startup test passed!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == '__main__':
    result = asyncio.run(test())
    sys.exit(0 if result else 1)
