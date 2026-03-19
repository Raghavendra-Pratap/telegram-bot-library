# Quick Restart Guide

## The Problem

Your `.env` file has been updated to use `http://192.168.1.10:8082`, but the bot is still running with the old `localhost` configuration.

## Solution: Restart the Bot

The bot reads configuration from `.env` only when it starts. You **must restart** it for changes to take effect.

### Quick Restart

```bash
cd TG_download_bot
./restart_bot.sh
```

Or manually:

```bash
# 1. Stop the bot
pkill -f "TG_download_bot.*bot.py"

# 2. Wait a moment
sleep 2

# 3. Start the bot
cd TG_download_bot
source venv/bin/activate
python bot.py &
```

## What Happens After Restart

✅ Bot will use `http://192.168.1.10:8082` for download links
✅ No more localhost errors
✅ Download links will work (as text, copyable)
✅ Works on your local WiFi network

## Note About Inline Buttons

**Important:** Telegram's servers cannot access private IPs (192.168.x.x), so:
- ✅ Download links will work (as text you can copy)
- ✅ "Copy Link" button will work
- ❌ "Open Download Link" button won't appear (Telegram restriction)

This is normal and expected for local network setups!

## For Clickable Buttons

If you want clickable "Open Download Link" buttons, you need a **public URL**:
- Public IP with port forwarding
- Domain name
- Tunneling service (ngrok, Cloudflare Tunnel)

For local network use, text links work perfectly fine!
