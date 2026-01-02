# First Run Guide

## Important: First-Time Authentication Required

On the first run, Pyrogram needs to authenticate with your Telegram account. This requires **interactive input** (phone number, verification code).

## Step-by-Step First Run

### 1. Make sure your `.env` file is configured:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
```

### 2. Run the bot interactively:

```bash
cd TG_download_bot
./start_bot.sh
```

Or manually:
```bash
cd TG_download_bot
source venv/bin/activate
python bot.py
```

### 3. When prompted, enter:

1. **Phone number**: Your Telegram phone number (with country code, e.g., +1234567890)
2. **Verification code**: Code sent to your Telegram app
3. **2FA password**: If you have 2FA enabled

### 4. After authentication:

- A session file will be created: `premium_account.session`
- You won't need to authenticate again
- The bot will start normally

### 5. For subsequent runs:

Once authenticated, you can run the bot in background:
```bash
./start_bot.sh &
```

## Troubleshooting

### "Enter phone number or bot token"

This is normal on first run. Enter your phone number.

### "Failed to start MTProto client: EOF when reading a line"

This happens when running in background on first run. Run it interactively first.

### "TgCrypto is missing"

This is just a warning. The bot will work, but slower. To fix:
```bash
source venv/bin/activate
pip install TgCrypto
```

### Session file created

After first authentication, you'll see `premium_account.session` file. This stores your login.

## Quick Start

1. **First time**: Run `./start_bot.sh` and complete authentication
2. **After that**: Bot will start automatically with saved session
