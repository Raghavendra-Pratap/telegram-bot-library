# 🔐 MTProto Authentication Required

## Current Status
- ✅ Bot is running
- ✅ Session file exists (`premium_account.session`)
- ❌ **MTProto is NOT authenticated** - This is why large files fail!

## Quick Fix (3 Steps)

### Step 1: Stop the Bot
```bash
cd TG_download_bot
pkill -f "python.*bot.py"
```

Or if you know the PID:
```bash
kill 70931  # Replace with your actual PID
```

### Step 2: Run Bot Interactively
```bash
cd TG_download_bot
source venv/bin/activate
python bot.py
```

### Step 3: Complete Authentication

When prompted, you'll see:
```
Enter phone number or bot token:
```

**Enter:**
1. **Phone number** (with country code): `+1234567890`
2. **Verification code** (sent to your Telegram app): `12345`
3. **2FA password** (if enabled): `your_password`

After authentication, you'll see:
```
✅ Premium MTProto client started successfully!
✅ Premium account detected - fast downloads enabled!
```

**Press `Ctrl+C` to stop the bot** (session is now saved)

### Step 4: Restart Bot in Background
```bash
# Run in background
python bot.py &
```

Or use the start script:
```bash
./start_bot.sh &
```

## Verify It Works

After restarting, send `/status` to your bot. You should see:
```
MTProto Client: ✅ Running
```

Now try downloading a large file (>20MB) - it should work! 🎉

## Alternative: Use Authentication Script

I've created a helper script:
```bash
./authenticate_mtproto.sh
```

This will:
- Stop any running bots
- Start bot interactively
- Guide you through authentication

## Troubleshooting

### "Session file exists but is not authenticated"
- The session file is corrupted or incomplete
- Solution: Run bot interactively to re-authenticate

### "Enter phone number or bot token"
- This is normal - enter your phone number
- Make sure to include country code (+1, +91, etc.)

### Authentication fails
- Check your `.env` file has correct `TELEGRAM_API_ID` and `TELEGRAM_API_HASH`
- Make sure you're using the correct phone number
- Try deleting the session file and starting fresh:
  ```bash
  rm premium_account.session
  python bot.py
  ```
