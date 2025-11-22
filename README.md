# Telegram Bot Library

This repository contains a collection of Telegram bots organized as a library structure.

## Structure

```
Telegram_Bot_Library/
├── down_oad_bot/          # Video Download Bot
│   ├── bot.py            # Main bot file
│   ├── config.py         # Configuration
│   ├── downloaders/      # Platform downloaders
│   ├── utils/            # Utility modules
│   ├── requirements.txt  # Dependencies
│   └── ...
├── upload_bot/            # File Upload Bot
│   ├── bot.py            # Main bot file
│   ├── config.py         # Configuration
│   ├── uploaders/        # Upload handlers
│   ├── metadata/         # CSV/Sheets integration
│   ├── utils/            # Utility modules
│   ├── requirements.txt  # Dependencies
│   └── ...
└── [future bots]/        # Additional bots will be added here
```

## Available Bots

### 📥 Download Bot (`down_oad_bot/`)

A comprehensive video downloader bot that supports:
- YouTube & YouTube Shorts
- Reddit videos
- Twitter/X videos
- Instagram Reels
- GIF platforms
- High quality downloads (up to 4K)
- Audio extraction (MP3)

**Quick Start:**
```bash
cd down_oad_bot
./START_BOT.sh
```

See `down_oad_bot/README.md` for full documentation.

### 📤 Upload Bot (`upload_bot/`)

A comprehensive file upload bot with advanced features:
- Folder structure metadata in captions
- CSV/Google Sheets integration for metadata
- Flexible file grouping by metadata columns
- Channel selection per file/group
- Multiple upload formats (document, photo, video, audio)
- Media groups and sequential uploads

**Quick Start:**
```bash
cd upload_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
# Configure .env file with your bot token
python bot.py
```

See `upload_bot/README.md` for full documentation.

## Adding New Bots

To add a new bot to this library:

1. Create a new folder for your bot (e.g., `my_bot/`)
2. Place all bot-specific files in that folder
3. Update this README with your bot's information
4. Follow the same structure as `down_oad_bot/` for consistency

## Library Structure

Each bot folder should be self-contained with:
- Bot implementation files
- Configuration files
- Dependencies (`requirements.txt`)
- Documentation
- Virtual environment (optional, can be shared)

## License

This library is for personal use. Respect platform Terms of Service.

