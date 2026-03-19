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
        
        # Check if get_chat_history exists (it might be async)
        if hasattr(bot, 'get_chat_history'):
            print("✅ get_chat_history method exists")
        else:
            print("⚠️  get_chat_history method not found (might need to update backfill function)")
        
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
