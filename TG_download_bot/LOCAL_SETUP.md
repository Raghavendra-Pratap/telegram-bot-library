# Local Development Setup Guide

This guide helps you set up the bot for local development on your computer.

## Understanding the Settings

### 1. TELEGRAM_SESSION_NAME

**What it is:**
- This is just a **filename** for storing your Telegram login session
- Pyrogram uses this to save your authentication so you don't have to log in every time
- It creates a file like `premium_account.session` in the bot directory

**What to set:**
- You can leave it as `premium_account` (default)
- Or change it to any name you like (e.g., `my_account`, `bot_session`)
- **No special configuration needed** - just leave it as default!

**Example:**
```env
TELEGRAM_SESSION_NAME=premium_account
```

### 2. FILE_SERVER_BASE_URL

**What it is:**
- This is the URL that users will use to download files
- The bot generates download links using this base URL

**Options for local development:**

#### Option A: Localhost Only (Testing on Same Computer)
If you're only testing on the same computer where the bot runs:

```env
FILE_SERVER_BASE_URL=http://localhost:8080
```

**Pros:**
- Simple, works immediately
- No network configuration needed

**Cons:**
- Download links only work on the same computer
- Can't test from your phone or other devices

#### Option B: Local Network Access (Recommended)
If you want to access download links from your phone or other devices on the same WiFi:

**Step 1: Find Your Local IP Address**

**On Mac:**
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```
Look for something like `192.168.1.100` or `10.0.0.5`

**On Linux:**
```bash
ip addr show | grep "inet " | grep -v 127.0.0.1
```

**On Windows:**
```bash
ipconfig
```
Look for "IPv4 Address" under your WiFi adapter (usually `192.168.x.x`)

**Step 2: Update .env**
```env
FILE_SERVER_BASE_URL=http://192.168.1.100:8080
```
(Replace `192.168.1.100` with your actual IP)

**Step 3: Allow Port 8080 in Firewall**

**On Mac:**
```bash
# Allow incoming connections on port 8080
sudo pfctl -f /etc/pf.conf
# Or use System Preferences > Security & Privacy > Firewall > Firewall Options
```

**On Linux:**
```bash
sudo ufw allow 8080
```

**On Windows:**
1. Open Windows Defender Firewall
2. Advanced Settings
3. Inbound Rules > New Rule
4. Port > TCP > 8080 > Allow

**Pros:**
- Download links work from your phone
- Can test from multiple devices
- Better for real-world testing

**Cons:**
- Need to configure firewall
- IP might change if you switch networks

#### Option C: Disable File Server (Alternative)
If you don't want to use the file server at all:

```env
ENABLE_FILE_SERVER=false
```

Files will still be downloaded, but you'll only get the local file path (not a download link).

## Quick Setup for Local Development

### Step 1: Create .env file
```bash
cd TG_download_bot
cp env_template.txt .env
```

### Step 2: Edit .env

**For localhost only:**
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_NAME=premium_account
FILE_SERVER_BASE_URL=http://localhost:8080
```

**For local network access:**
```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_SESSION_NAME=premium_account
FILE_SERVER_BASE_URL=http://192.168.1.100:8080  # Your local IP
```

### Step 3: Run the bot
```bash
python bot.py
```

## Testing Download Links

### If using localhost:
- Download links will only work if you open them on the same computer
- Example: `http://localhost:8080/download/abc123...`
- Copy the link and paste in browser on same computer

### If using local IP:
- Download links will work from any device on the same WiFi
- Example: `http://192.168.1.100:8080/download/abc123...`
- You can open this link on your phone, tablet, or other computer
- Make sure all devices are on the same WiFi network

## Troubleshooting

### "Can't access download link from phone"
- Make sure you're using your local IP (not localhost)
- Check that phone is on the same WiFi network
- Verify firewall allows port 8080
- Try accessing `http://YOUR_IP:8080/health` from phone browser

### "Connection refused"
- Make sure bot is running
- Check that port 8080 is not already in use
- Verify `FILE_SERVER_HOST=0.0.0.0` (not `127.0.0.1`)

### "IP address changed"
- Your local IP might change when you reconnect to WiFi
- Update `FILE_SERVER_BASE_URL` in .env with new IP
- Or set a static IP on your router

## Example .env for Local Development

```env
# Bot credentials
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890

# Session name (just leave as default)
TELEGRAM_SESSION_NAME=premium_account

# File server for local network
ENABLE_FILE_SERVER=true
FILE_SERVER_HOST=0.0.0.0
FILE_SERVER_PORT=8080
FILE_SERVER_BASE_URL=http://192.168.1.100:8080

# Other settings
DOWNLOAD_DIR=./downloads
FILE_RETENTION_HOURS=24
ENABLE_USER_VERIFICATION=false
```

## Summary

1. **TELEGRAM_SESSION_NAME**: Just leave as `premium_account` (it's just a filename)
2. **FILE_SERVER_BASE_URL**: 
   - Use `http://localhost:8080` for same-computer testing
   - Use `http://YOUR_LOCAL_IP:8080` for phone/network access
   - Find your IP with `ifconfig` (Mac/Linux) or `ipconfig` (Windows)

That's it! You're ready to test locally.
