# Telegram Video Downloader Bot

A comprehensive Telegram bot that allows you to download videos from multiple platforms including YouTube, Reddit, Twitter/X, Instagram, and GIF platforms.

> **Branch status:** Under development. Available on `development` branch only.

## Features

- 🎬 **Multi-Platform Support**
  - YouTube & YouTube Shorts
  - Reddit videos
  - Twitter/X videos
  - Instagram Reels
  - GIFs (Giphy, Tenor, etc.)

- 🎥 **High Quality Downloads**
  - Up to 2160p (4K) quality
  - Automatic best quality selection
  - Audio extraction (MP3)

- 📱 **Easy to Use**
  - Just send a URL to the bot
  - Choose video or audio format
  - Get download link or file directly

## Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (get from [@BotFather](https://t.me/botfather))
- FFmpeg (for audio extraction and video processing)
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt-get install ffmpeg`
  - Windows: Download from [ffmpeg.org](https://ffmpeg.org/download.html)

## Installation

1. **Clone or navigate to the project directory:**
```bash
cd Telegram_Bot_Library
```

2. **Create a shared virtual environment (recommended):**
```bash
./scripts/setup_env.sh
```

3. **Install dependencies for this bot:**
```bash
./scripts/install_deps.sh down_oad
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

4. **Install FFmpeg** (if not already installed):
```bash
# macOS
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt-get update && sudo apt-get install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

5. **Set up environment variables:**
```bash
cp env_template.txt .env
```

Edit `.env` and add your Telegram Bot Token:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

## Optional Configuration

### Instagram Authentication (for Reels)
If you want to download Instagram Reels, add your credentials to `.env`:
```
INSTAGRAM_USERNAME=your_username
INSTAGRAM_PASSWORD=your_password
```

**Note:** Instagram authentication is optional. Public Reels can sometimes be downloaded without it, but private content requires authentication.

### YouTube Cookies (for Private Videos)
To download private/unlisted YouTube videos you have access to:

1. Export cookies from your browser (use a browser extension like "Get cookies.txt LOCALLY")
2. Save as `cookies.txt` in the project root
3. Add to `.env`:
```
YOUTUBE_COOKIES_PATH=./cookies.txt
```

## Usage

1. **Start the bot:**
```bash
python bot.py
```

2. **Open Telegram and find your bot**

3. **Send a video URL** to the bot:
   - YouTube: `https://www.youtube.com/watch?v=VIDEO_ID`
   - Reddit: `https://www.reddit.com/r/...`
   - Twitter: `https://twitter.com/.../status/...`
   - Instagram: `https://www.instagram.com/reel/...`
   - GIF: Any Giphy/Tenor URL

4. **Choose format:**
   - Click "📹 Video" for video download
   - Click "🎵 Audio" for MP3 extraction

5. **Get your file:**
   - The bot will send the file directly to Telegram
   - You'll also receive the local file path

## Project Structure

```
Telegram_Bot_Library/
├── bot.py                 # Main bot file
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── env_template.txt       # Environment variables template (copy to .env)
├── .gitignore            # Git ignore file
├── downloaders/          # Platform-specific downloaders
│   ├── __init__.py
│   ├── base_downloader.py
│   ├── youtube_downloader.py
│   ├── reddit_downloader.py
│   ├── twitter_downloader.py
│   ├── instagram_downloader.py
│   └── gif_downloader.py
├── utils/                # Utility modules
│   ├── __init__.py
│   └── url_detector.py
└── downloads/            # Downloaded files (created automatically)
```

## Troubleshooting

### Instagram Downloads Not Working
- Instagram has strict anti-scraping measures
- Try adding Instagram credentials to `.env`
- Some Reels may require authentication
- Rate limiting may occur with frequent requests

### YouTube Private Videos
- Export cookies from your browser
- Save as `cookies.txt` in project root
- Add path to `.env`: `YOUTUBE_COOKIES_PATH=./cookies.txt`

### File Size Limits
- Telegram Premium: 4GB limit
- Free Telegram: 50MB limit
- Large files will be saved locally with path provided

### FFmpeg Not Found
- Make sure FFmpeg is installed and in your PATH
- Test with: `ffmpeg -version`

## Limitations

- **Instagram:** May require authentication and has strict rate limiting
- **Private Content:** Requires user authentication (cookies/credentials)
- **File Size:** Telegram has file size limits (4GB for premium)
- **Rate Limiting:** Platforms may rate limit frequent requests
- **Maintenance:** Platforms change frequently, may require updates

## Legal Notice

This bot is for **personal use only**. Respect content creators' rights and platform Terms of Service. Do not redistribute downloaded content without permission.

## Contributing

Feel free to submit issues or pull requests for improvements!

## License

This project is for personal use. Use responsibly and respect platform Terms of Service.

