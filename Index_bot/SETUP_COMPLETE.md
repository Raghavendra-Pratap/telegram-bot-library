# Setup Complete! 🎉

Your Telegram Index Bot is ready to use!

## ✅ What's Been Done

1. ✅ Virtual environment created (`venv/`)
2. ✅ All dependencies installed
3. ✅ Name parser tested and working
4. ✅ All bot components created

## 📝 Next Steps

### 1. Create Your .env File

You have two options:

**Option A: Use the interactive script**
```bash
source venv/bin/activate
python create_env.py
```

**Option B: Create manually**
Create a `.env` file in the project root with:
```
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_USER_IDS=your_telegram_user_id
```

### 2. Get Your Bot Token

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow instructions
3. Copy the bot token

### 3. Get Your User ID

1. Open Telegram and message [@userinfobot](https://t.me/userinfobot)
2. Send `/start`
3. Copy your user ID (it's a number)

### 4. Start the Bot

```bash
source venv/bin/activate
python bot.py
```

### 5. Add Channels to Monitor

1. Add your bot as an admin to the channels you want to monitor
2. Give it **read messages** permission
3. In Telegram, message your bot:
   ```
   /add_channel @your_channel_username
   ```

### 6. Backfill Existing Messages (Optional)

To index existing files in a channel:
```
/backfill @your_channel_username 500
```

## 🧪 Test the Name Parser

You can test how the parser extracts names from file names:
```bash
source venv/bin/activate
python test_parser.py
```

## 📚 Available Commands

### User Commands
- `/start` - Start the bot
- `/search <name>` - Search for movies/series
- `/library <name>` - View detailed library info
- `/list_channels` - List monitored channels
- `/stats` - View statistics

### Admin Commands
- `/add_channel <username>` - Add channel to monitor
- `/remove_channel <username>` - Remove channel
- `/backfill <username> [limit]` - Backfill existing messages
- `/pending` - View files needing confirmation
- `/confirm <file_id> <name>` - Confirm file name

## 🎯 How It Works

1. **Automatic Indexing**: The bot automatically indexes all new file uploads
2. **Smart Parsing**: File names are parsed to extract movie/series titles
3. **Auto-Confirmation**: High-confidence parsed names are auto-confirmed
4. **Admin Review**: Low-confidence names are flagged for admin confirmation
5. **Search & Library**: Users can search and view detailed library information

## 💡 Tips

- The name parser works best with standard file naming conventions
- Files with unusual names may need admin confirmation
- Use `/pending` regularly to review files that need confirmation
- The bot tracks uploads across multiple channels and shows aggregate statistics

## 🐛 Troubleshooting

**Bot not receiving messages?**
- Make sure the bot is added as admin to the channel
- Check that the bot has "read messages" permission

**Name parser not working well?**
- Some file names may need manual confirmation
- Use `/confirm` to set the correct name

**Database issues?**
- The database is created automatically on first run
- Located at `index_bot.db` (or as specified in .env)

## 🚀 Ready to Go!

Once you've created your `.env` file with the bot token and admin user ID, you're ready to start indexing!
