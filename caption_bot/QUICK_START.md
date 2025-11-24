# Quick Start Guide

## Setup (5 minutes)

### 1. Install Dependencies

```bash
cd caption_bot
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the bot token

### 3. Configure

Create a `.env` file:

```bash
cp env_template.txt .env
```

Edit `.env` and add your bot token:

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### 4. Run

```bash
python bot.py
```

## Usage

1. Start a chat with your bot
2. Upload any file
3. The bot will send it back with the filename as caption

That's it! 🎉

