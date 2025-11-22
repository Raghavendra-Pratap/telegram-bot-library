# Step-by-Step Setup Guide for Testing

## Prerequisites Check ✅

- ✅ Python 3.13.3 installed
- ⚠️ FFmpeg needs to be installed

## Step 1: Install FFmpeg

Since you're on macOS, install FFmpeg using Homebrew:

```bash
brew install ffmpeg
```

If you don't have Homebrew, install it first:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

## Step 2: Create Virtual Environment

```bash
cd /Users/raghavendra_pratap/Developer/Telegram_Bot_Library
python3 -m venv venv
source venv/bin/activate
```

## Step 3: Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Step 4: Get Telegram Bot Token

1. Open Telegram app
2. Search for **@BotFather**
3. Send `/newbot` command
4. Follow instructions:
   - Choose a name for your bot (e.g., "My Video Downloader")
   - Choose a username (must end with 'bot', e.g., "my_video_downloader_bot")
5. Copy the token BotFather gives you (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Step 5: Configure Environment

```bash
# Create .env file from template
cp env_template.txt .env

# Edit .env file and add your token
# You can use: nano .env  or  open -e .env
```

Add your token:
```
TELEGRAM_BOT_TOKEN=your_actual_token_here
```

## Step 6: Test the Bot

```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Run the bot
python bot.py
```

You should see:
```
INFO - Bot starting...
```

## Step 7: Test in Telegram

1. Open Telegram
2. Search for your bot (the username you chose)
3. Send `/start`
4. Send a test URL, for example:
   - YouTube: `https://www.youtube.com/watch?v=dQw4w9WgXcQ`
   - Reddit: Any Reddit video post URL
   - Twitter: Any Twitter video URL

## Troubleshooting

### FFmpeg not found
```bash
brew install ffmpeg
# Verify: ffmpeg -version
```

### Module not found errors
```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Bot not responding
- Check if bot is running (terminal should show "Bot starting...")
- Verify token in .env is correct
- Make sure no other instance is running

### Import errors
- Make sure you're in the project directory
- Activate virtual environment: `source venv/bin/activate`

