#!/usr/bin/env python3
"""
Detailed premium account check script
"""
import asyncio
import sys
from mtproto_downloader import PremiumDownloader

async def check_premium():
    """Check premium account status in detail"""
    print("🔍 Checking Premium Account Status...")
    print("=" * 60)
    
    try:
        downloader = PremiumDownloader()
        print("📡 Starting MTProto client...")
        await downloader.start()
        
        print("\n✅ MTProto client started successfully!")
        
        # Get user info
        me = await downloader.client.get_me()
        print(f"\n👤 Account Information:")
        print(f"   Name: {me.first_name} {me.last_name or ''}")
        if me.username:
            print(f"   Username: @{me.username}")
        print(f"   User ID: {me.id}")
        
        # Detailed premium check
        print(f"\n🔍 Premium Status Check:")
        print(f"   hasattr(me, 'is_premium'): {hasattr(me, 'is_premium')}")
        
        if hasattr(me, 'is_premium'):
            print(f"   me.is_premium value: {me.is_premium}")
            print(f"   me.is_premium type: {type(me.is_premium)}")
            
            if me.is_premium:
                print("\n✅ PREMIUM ACCOUNT DETECTED!")
                print("   Fast downloads enabled!")
            else:
                print("\n❌ Account is NOT premium")
                print("   Downloads will be slower (5-10 MB/s instead of 20-50+ MB/s)")
                print("\n   To fix:")
                print("   1. Subscribe to Telegram Premium in the Telegram app")
                print("   2. Wait a few minutes for subscription to activate")
                print("   3. Re-authenticate: rm premium_account.session && python bot.py")
        else:
            print("\n⚠️  'is_premium' attribute not found in user object")
            print("   This might mean:")
            print("   - Account is not premium")
            print("   - Pyrogram version doesn't support this attribute")
            print("   - Need to re-authenticate")
            print("\n   Try re-authenticating:")
            print("   rm premium_account.session && python bot.py")
        
        # Check all user attributes
        print(f"\n📋 All User Attributes:")
        attrs = [attr for attr in dir(me) if not attr.startswith('_')]
        for attr in sorted(attrs)[:20]:  # Show first 20
            try:
                value = getattr(me, attr)
                if not callable(value):
                    print(f"   {attr}: {value}")
            except:
                pass
        
        await downloader.stop()
        print("\n" + "=" * 60)
        return True
        
    except EOFError:
        print("\n❌ MTProto needs interactive authentication")
        print("   Session file exists but needs to be re-authenticated")
        print("\n   To fix:")
        print("   1. Stop the bot")
        print("   2. Run: python bot.py (interactively)")
        print("   3. Enter your phone number and verification code")
        print("   4. Restart the bot")
        return False
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    try:
        result = asyncio.run(check_premium())
        sys.exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Check interrupted")
        sys.exit(1)
