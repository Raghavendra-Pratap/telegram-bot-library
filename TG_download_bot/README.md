# Telegram Download Accelerator Bot

A Telegram bot that uses a **premium account with MTProto** to download files at premium speeds and provide fast download links for non-premium users.

> **Branch status:** Under development. Available on `development` branch only.

## Features

- ⚡ **Premium download speeds** - Uses MTProto with premium account (5-10x faster)
- 📦 **Large file support** - Files up to 4GB (vs 20MB Bot API limit)
- 🔗 **Direct download links** - Fast HTTP downloads without Telegram throttling
- ⏱️ **Auto-expiration** - Links expire after 24 hours, files auto-deleted
- 🔒 **Secure** - Token-based access control

## How It Works

1. User forwards/shares a file to the bot
2. Bot downloads file using **MTProto with premium account** (fast!)
3. Bot stores file on server
4. Bot provides direct HTTP download link
5. User downloads from server (no Telegram throttling)

## Requirements

- Python 3.8+
- Telegram Premium account
- Telegram Bot Token (from @BotFather)
- MTProto API credentials (from https://my.telegram.org)
- Server/VPS for hosting (optional, can run locally)

## Setup

### 1. Install Dependencies (Shared)

```bash
# From repo root
./scripts/setup_env.sh
./scripts/install_deps.sh tg-download
source .venv/bin/activate
```

### 2. Get API Credentials

#### Bot Token
1. Talk to [@BotFather](https://t.me/BotFather) on Telegram
2. Create a new bot with `/newbot`
3. Copy the bot token

#### MTProto API Credentials
1. Go to https://my.telegram.org
2. Log in with your **premium Telegram account**
3. Go to "API development tools"
4. Create an application (any name/description)
5. Copy `api_id` and `api_hash`

### 3. Configure Environment

```bash
cp env_template.txt .env
```

Edit `.env` and fill in:
- `TELEGRAM_BOT_TOKEN` - Your bot token
- `TELEGRAM_API_ID` - Your API ID
- `TELEGRAM_API_HASH` - Your API hash
- `TELEGRAM_SESSION_NAME` - Just leave as `premium_account` (it's just a filename for the session)
- `FILE_SERVER_BASE_URL` - See below for local vs production setup

**For Local Development:**
- Use `http://localhost:8080` if testing on same computer
- Use `http://YOUR_LOCAL_IP:8080` if accessing from phone/other devices
- See [LOCAL_SETUP.md](LOCAL_SETUP.md) for detailed local setup guide

**For Production:**
- Use your server's public IP or domain name

### 4. Run the Bot

```bash
python bot.py
```

On first run, Pyrogram will ask you to:
1. Enter your phone number
2. Enter the verification code sent to Telegram
3. Enter your 2FA password (if enabled)

After that, the session is saved and you won't need to authenticate again.

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | Required |
| `TELEGRAM_API_ID` | API ID from my.telegram.org | Required |
| `TELEGRAM_API_HASH` | API hash from my.telegram.org | Required |
| `TELEGRAM_SESSION_NAME` | Pyrogram session filename (just leave as default) | `premium_account` |
| `ENABLE_USER_VERIFICATION` | Enable user access control | `false` |
| `ALLOWED_USER_IDS` | Comma-separated user IDs | Empty |
| `DOWNLOAD_DIR` | Directory for downloads | `./downloads` |
| `ENABLE_FILE_SERVER` | Enable HTTP file server | `true` |
| `FILE_SERVER_HOST` | File server host | `0.0.0.0` |
| `FILE_SERVER_PORT` | File server port | `8080` |
| `FILE_SERVER_BASE_URL` | Base URL for download links (see LOCAL_SETUP.md for local options) | `http://localhost:8080` |
| `FILE_RETENTION_HOURS` | File retention time | `24` |

### User Access Control

To restrict bot access to specific users:

```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=123456789,987654321
```

Get user IDs by forwarding a message from the user to [@userinfobot](https://t.me/userinfobot).

## Usage

1. Start the bot
2. Forward or share a file to the bot
3. Bot downloads it using premium speeds
4. Get a fast download link
5. Download from the link (no throttling!)

### Commands

- `/start` - Show welcome message
- `/help` - Show help
- `/status` - Check bot status

## File Server

The bot includes a simple HTTP file server for serving downloaded files. 

### Local Development

For local testing, use:
```env
FILE_SERVER_BASE_URL=http://localhost:8080
```

### Production

For production, you need:
1. Public IP or domain name
2. Port forwarding (if behind NAT)
3. Update `FILE_SERVER_BASE_URL` to your public URL

Example:
```env
FILE_SERVER_BASE_URL=https://yourdomain.com
```

### Disable File Server

If you don't want to use the file server, set:
```env
ENABLE_FILE_SERVER=false
```

Files will still be downloaded, but you'll only get the local file path.

## Performance

### Speed Comparison

| Method | Speed | File Size Limit |
|--------|-------|-----------------|
| Bot API (Non-Premium) | ~2-5 MB/s | 20 MB |
| Bot API (Premium) | ~2-5 MB/s | 20 MB |
| MTProto (Non-Premium) | ~5-10 MB/s | 2 GB |
| **MTProto (Premium)** | **~20-50+ MB/s** | **4 GB** |

### Example

**100MB file:**
- Non-premium user: 20-50 seconds
- With this bot: 2-5 seconds (bot download) + 2-5 seconds (user download) = **4-10 seconds total**

**5-10x faster!**

## Security Considerations

- Files are stored temporarily (24 hours default)
- Token-based access (secure random tokens)
- Auto-expiration of links
- Files auto-deleted after expiration

## Troubleshooting

### "MTProto client not started"
- Check that `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` are set correctly
- Make sure you've authenticated with Pyrogram (check for session file)

### "Download failed"
- Check if file is accessible
- Verify premium account is active
- Check file size (should be < 4GB)

### "File server not accessible"
- Check `FILE_SERVER_BASE_URL` is correct
- Verify port is open and accessible
- Check firewall settings

### "Rate limit errors"
- Premium accounts have higher limits
- If you hit limits, wait a few minutes
- Consider adding delays between downloads

## Legal & Compliance

- Files are stored temporarily (24 hours)
- Auto-deleted after expiration
- Use responsibly
- Respect copyright and content policies

## License

This project is for personal/educational use. Use responsibly and in accordance with Telegram's Terms of Service.

## Support

For issues or questions, check the code comments or create an issue in the repository.
