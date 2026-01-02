# Quick Start Guide

## Prerequisites

1. **Telegram Premium Account** - You need an active premium subscription
2. **Python 3.8+** - Check with `python3 --version`
3. **Server/VPS** - For hosting (or run locally for testing)

## Step-by-Step Setup

### 1. Install Dependencies

```bash
cd TG_download_bot
pip install -r requirements.txt
```

### 2. Get Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Follow instructions to create a bot
4. Copy the bot token (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 3. Get MTProto API Credentials

1. Go to https://my.telegram.org
2. Log in with your **premium Telegram account** phone number
3. Enter verification code sent to Telegram
4. Go to "API development tools"
5. Click "Create application"
6. Fill in any name/description (e.g., "Download Bot")
7. Copy `api_id` (a number like `12345678`)
8. Copy `api_hash` (a string like `abcdef1234567890abcdef1234567890`)

### 4. Configure Environment

```bash
cp env_template.txt .env
```

Edit `.env` file:

```env
# Required
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_API_ID=your_api_id_from_my_telegram_org
TELEGRAM_API_HASH=your_api_hash_from_my_telegram_org

# Optional - for local testing
FILE_SERVER_BASE_URL=http://localhost:8080

# Optional - for production (use your server's IP/domain)
# FILE_SERVER_BASE_URL=https://yourdomain.com
```

### 5. Run the Bot

```bash
python bot.py
```

**First Run:**
- Pyrogram will ask for your phone number
- Enter the verification code sent to Telegram
- If you have 2FA enabled, enter your password
- Session will be saved (you won't need to authenticate again)

**You should see:**
```
✅ Premium MTProto client started successfully!
✅ Premium account detected - fast downloads enabled!
File server started on http://0.0.0.0:8080
Bot starting...
```

### 6. Test the Bot

1. Open Telegram
2. Find your bot (search for the username you gave it)
3. Send `/start`
4. Forward a file to the bot
5. Wait for download (should be fast!)
6. Get download link

## Production Setup

### For Production Server

1. **Update FILE_SERVER_BASE_URL** in `.env`:
   ```env
   FILE_SERVER_BASE_URL=https://yourdomain.com
   # or
   FILE_SERVER_BASE_URL=http://your.server.ip:8080
   ```

2. **Open Port 8080** (or your chosen port):
   ```bash
   # Ubuntu/Debian
   sudo ufw allow 8080
   
   # Or configure your firewall
   ```

3. **Run as Service** (optional):
   ```bash
   # Using systemd
   sudo nano /etc/systemd/system/tg-download-bot.service
   ```
   
   Add:
   ```ini
   [Unit]
   Description=Telegram Download Bot
   After=network.target
   
   [Service]
   Type=simple
   User=your_user
   WorkingDirectory=/path/to/TG_download_bot
   ExecStart=/usr/bin/python3 /path/to/TG_download_bot/bot.py
   Restart=always
   
   [Install]
   WantedBy=multi-user.target
   ```
   
   Then:
   ```bash
   sudo systemctl enable tg-download-bot
   sudo systemctl start tg-download-bot
   sudo systemctl status tg-download-bot
   ```

## Troubleshooting

### "TELEGRAM_BOT_TOKEN not set"
- Check `.env` file exists and has correct token

### "Failed to start MTProto client"
- Verify API credentials are correct
- Make sure you're using a premium account
- Check session file permissions

### "File server not accessible"
- Check `FILE_SERVER_BASE_URL` matches your server's address
- Verify port is open: `netstat -tuln | grep 8080`
- Check firewall settings

### "Download failed"
- Verify file is accessible
- Check file size (< 4GB)
- Look at logs for error details

## Next Steps

- Read [README.md](README.md) for full documentation
- Check [PREMIUM_MTProto_DOWNLOAD_FEASIBILITY.md](../PREMIUM_MTProto_DOWNLOAD_FEASIBILITY.md) for technical details
- Customize settings in `.env`
- Set up user access control if needed

## Support

If you encounter issues:
1. Check the logs
2. Verify all credentials are correct
3. Make sure premium account is active
4. Check file server is accessible
