# How to Get Your Telegram User ID

To restrict the bot to specific users, you need their Telegram User IDs.

## Method 1: Using @userinfobot (Easiest)

1. Open Telegram
2. Search for **@userinfobot**
3. Start a chat with the bot
4. Send `/start` or any message
5. The bot will reply with your user information, including your **ID**
6. Copy the ID number (it's a long number like `123456789`)

## Method 2: Using @RawDataBot

1. Open Telegram
2. Search for **@RawDataBot**
3. Start a chat
4. Send `/start`
5. The bot will send you JSON data
6. Look for `"id"` field - that's your user ID

## Method 3: From Bot Logs

1. Start your bot
2. Send a message to your bot
3. Check the bot logs - user ID will be in the log messages
4. Look for lines like: `INFO - User 123456789 sent message`

## Adding User IDs to .env

Once you have the user IDs:

1. Open `.env` file
2. Set `ENABLE_USER_VERIFICATION=true`
3. Add user IDs to `ALLOWED_USER_IDS`:
   ```
   ALLOWED_USER_IDS=123456789,987654321,555666777
   ```
   (Separate multiple IDs with commas, no spaces)

4. Restart the bot

## Example Configuration

```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=123456789,987654321
```

This allows only users with IDs 123456789 and 987654321 to use the bot.

## Disabling Verification

To make the bot public (anyone can use it):
```env
ENABLE_USER_VERIFICATION=false
```

Or simply don't set `ENABLE_USER_VERIFICATION` (defaults to false).

## Security Note

⚠️ **Important:**
- User IDs are just numbers - they're not secret
- Anyone can get their own user ID
- This is a simple whitelist, not encryption
- For production use, consider more advanced authentication

