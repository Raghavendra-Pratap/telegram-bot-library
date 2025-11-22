# How to Get Your Telegram Bot Token

## Step-by-Step Instructions

### 1. Open Telegram
- Open the Telegram app on your phone or desktop

### 2. Find BotFather
- Search for **@BotFather** in Telegram
- It's the official bot for creating Telegram bots
- Make sure it has the blue verified checkmark ✓

### 3. Start a Chat
- Click on @BotFather
- Press "Start" or send `/start`

### 4. Create a New Bot
- Send the command: `/newbot`
- BotFather will ask for a name for your bot
  - Example: "My Video Downloader Bot"
  - This is the display name (can be changed later)

### 5. Choose a Username
- BotFather will ask for a username
  - Must end with `bot` (e.g., `my_video_downloader_bot`)
  - Must be unique (if taken, try another)
  - Example: `my_video_downloader_bot` or `video_dl_bot`

### 6. Get Your Token
- BotFather will give you a token that looks like:
  ```
  123456789:ABCdefGHIjklMNOpqrsTUVwxyz
  ```
- **IMPORTANT:** Copy this token immediately!
- Keep it secret - don't share it publicly

### 7. Add Token to .env File

Open the `.env` file and replace `your_bot_token_here` with your actual token:

```bash
# Option 1: Using nano (terminal editor)
nano .env

# Option 2: Using TextEdit (macOS)
open -e .env

# Option 3: Using VS Code
code .env
```

Change this line:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

To:
```
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
```
(Replace with your actual token)

### 8. Save and Close
- Save the file
- Close the editor

### 9. Test Your Bot
- Run the test script:
  ```bash
  source venv/bin/activate
  python test_setup.py
  ```
- If all checks pass, start the bot:
  ```bash
  python bot.py
  ```

## Quick Commands for BotFather

- `/newbot` - Create a new bot
- `/token` - Get your bot's token (if you lost it)
- `/setname` - Change bot's display name
- `/setdescription` - Set bot description
- `/setabouttext` - Set about text
- `/setuserpic` - Set bot profile picture
- `/deletebot` - Delete your bot

## Troubleshooting

**Token not working?**
- Make sure there are no extra spaces
- Make sure the token is on one line
- Try getting a new token with `/token` command

**Bot not responding?**
- Check if bot is running (`python bot.py`)
- Verify token in .env is correct
- Make sure you're messaging the correct bot username

## Security Note

⚠️ **Never share your bot token publicly!**
- Don't commit .env to git (it's already in .gitignore)
- Don't share screenshots with the token visible
- If token is leaked, use `/revoke` in BotFather to get a new one

