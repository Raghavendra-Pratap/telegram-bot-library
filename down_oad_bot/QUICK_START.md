# Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Step 1: Get Telegram Bot Token
1. Open Telegram
2. Search for [@BotFather](https://t.me/botfather)
3. Send `/newbot` and follow instructions
4. Copy your bot token (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Setup Project
```bash
# Run setup script
./setup.sh

# Or manually:
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 3: Configure
```bash
# Create .env file
cp env_template.txt .env

# Edit .env and add your token:
# TELEGRAM_BOT_TOKEN=your_token_here
```

### Step 4: Install FFmpeg (if not installed)
```bash
# macOS
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

### Step 5: Run Bot
```bash
# Activate virtual environment (if not already)
source venv/bin/activate

# Start bot
python bot.py
```

### Step 6: Test It!
1. Open Telegram
2. Find your bot (search for the name you gave it)
3. Send `/start`
4. Send a YouTube URL: `https://www.youtube.com/watch?v=dQw4w9WgXcQ`
5. Click "📹 Video" or "🎵 Audio"
6. Wait for download!

## 📱 Supported URLs

Just send any of these:
- YouTube: `https://www.youtube.com/watch?v=...`
- YouTube Shorts: `https://www.youtube.com/shorts/...`
- Reddit: `https://www.reddit.com/r/.../comments/...`
- Twitter: `https://twitter.com/.../status/...`
- Instagram: `https://www.instagram.com/reel/...`
- GIF: Any Giphy or Tenor URL

## ⚙️ Optional: Instagram Setup

If you want to download Instagram Reels:
1. Edit `.env`
2. Add:
   ```
   INSTAGRAM_USERNAME=your_instagram_username
   INSTAGRAM_PASSWORD=your_instagram_password
   ```
3. Restart bot

## ⚙️ Optional: YouTube Private Videos

To download private/unlisted YouTube videos you have access to:
1. Export cookies from your browser (use extension like "Get cookies.txt LOCALLY")
2. Save as `cookies.txt` in project root
3. Edit `.env`:
   ```
   YOUTUBE_COOKIES_PATH=./cookies.txt
   ```
4. Restart bot

## 🎯 That's It!

Your bot is ready to download videos! Just send URLs and enjoy.

## ❓ Troubleshooting

**Bot not responding?**
- Check if bot is running (should see "Bot starting..." in terminal)
- Verify token in .env is correct
- Make sure you started the bot with the correct token

**Downloads failing?**
- Check internet connection
- Some videos may be private/restricted
- Instagram may require authentication

**FFmpeg errors?**
- Make sure FFmpeg is installed: `ffmpeg -version`
- Add FFmpeg to your PATH if needed

**Need help?**
- Check README.md for detailed documentation
- Check IMPLEMENTATION_SUMMARY.md for feature details

