#!/usr/bin/env python3
"""
Quick test script to check MTProto authentication status
"""
import asyncio
import sys
from mtproto_downloader import PremiumDownloader

async def test_mtproto():
    """Test if MTProto client can start and authenticate"""
    print("🔍 Testing MTProto authentication...")
    print("=" * 50)
    
    try:
        downloader = PremiumDownloader()
        print("📡 Starting MTProto client...")
        await downloader.start()
        
        print("✅ MTProto client started successfully!")
        
        # Get user info
        me = await downloader.client.get_me()
        print(f"✅ Authenticated as: {me.first_name} {me.last_name or ''}")
        if me.username:
            print(f"   Username: @{me.username}")
        print(f"   User ID: {me.id}")
        
        # Check premium status
        if hasattr(me, 'is_premium') and me.is_premium:
            print("✅ Premium account detected - fast downloads enabled!")
        else:
            print("⚠️  Account is not premium - downloads may be slower")
        
        await downloader.stop()
        print("\n✅ MTProto authentication is working correctly!")
        return True
        
    except EOFError:
        print("\n❌ MTProto needs interactive authentication")
        print("   The session file exists but needs to be re-authenticated")
        print("\n   To fix:")
        print("   1. Run: python bot.py (interactively)")
        print("   2. Enter your phone number and verification code")
        print("   3. Restart the bot")
        return False
        
    except Exception as e:
        print(f"\n❌ MTProto authentication failed: {e}")
        print("\n   To fix:")
        print("   1. Run: python bot.py (interactively)")
        print("   2. Complete authentication")
        print("   3. Restart the bot")
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(test_mtproto())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted")
        sys.exit(1)
