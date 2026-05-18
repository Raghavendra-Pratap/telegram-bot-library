# Quick Start Guide

## 1. Get Your Bot Token

1. Open Telegram and search for [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy your bot token

## 2. Get Your Admin User ID

1. Open Telegram and search for [@userinfobot](https://t.me/userinfobot)
2. Send `/start` to get your user ID
3. Copy your user ID (it's a number)

## 3. Setup Environment

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and add your credentials:
   ```
   BOT_TOKEN=your_bot_token_here
   ADMIN_USER_IDS=your_user_id_here
   ```

## 4. Install Dependencies

```bash
pip install -r requirements.txt
```

## 5. Verify Setup

```bash
python setup.py
```

## 6. Add Bot to Channels

1. Go to your Telegram channel
2. Open channel settings → Administrators
3. Add your bot as an administrator
4. Give it **read messages** permission (minimum required)

## 7. Start the Bot

```bash
python bot.py
```

## 8. Add Channels to Monitor

Once the bot is running, send it a message:
```
/add_channel @your_channel_username
```

## 9. Import old uploads (optional)

Bots cannot read channel history. Use **Telethon** to forward old posts into an **ingest** channel (bot must be admin there):

```bash
source venv/bin/activate
python forward_ingest.py @source_channel @ingest_channel
```

See `HOW_TO_RUN.md` → *Historical ingest*. In Telegram, `/backfill` shows a short summary for admins.

## Testing the Name Parser

You can test the name parser with:
```bash
python test_parser.py
```

This will show how the parser extracts movie/series names from various file name formats.
