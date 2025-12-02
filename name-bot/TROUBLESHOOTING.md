# Troubleshooting Guide

## Common Issues and Solutions

### Issue: Bot adds file_id as caption instead of filename

**Symptoms:**
- Caption shows something like: `video_BAACAgUAAx0CZWS2yQACBBbBpLwb7Ut0Rz2zgVm8f6_Lt288IegACvx0AAjDEeVWnudslJ7q98jYE.mp4`
- This happens when uploading from mobile devices
- Works correctly when uploading from desktop/PC

**Cause:**
When files are uploaded from mobile devices (especially from gallery or camera), Telegram often doesn't include the original filename in the API response. The bot can't retrieve a filename that Telegram doesn't provide.

**Solutions:**

1. **Rename files before uploading:**
   - On mobile, rename the file before uploading
   - Use a file manager app to rename files
   - Then upload the renamed file

2. **Use "Send as File" option:**
   - In Telegram mobile app, when selecting a file
   - Choose "Send as File" instead of "Send as Photo/Video"
   - This often preserves the filename better

3. **Upload from desktop:**
   - Desktop Telegram client typically preserves filenames
   - Use desktop app for files where filename is important

4. **Use file manager apps:**
   - Some file manager apps allow you to share files with custom names
   - Use these apps to upload files with proper names

**Why this happens:**
- Telegram's mobile app doesn't always preserve original filenames
- When files are sent directly from gallery/camera, Telegram may not have the original filename
- The Telegram Bot API can only access information that Telegram provides
- If `file_name` attribute is missing, the bot uses a fallback (file_id-based name)

**Technical Details:**
- The bot checks `message.video.file_name`, `message.document.file_name`, etc.
- If these are `None` or empty, bot generates a filename using file_id
- This is a limitation of the Telegram API, not the bot

---

### Issue: Captions not being added

**Symptoms:**
- Files upload but no caption is added
- Bot doesn't respond to file uploads

**Solutions:**

1. **Check bot permissions:**
   - Use `/status` command in your channel/group
   - Verify bot is admin
   - Verify bot has "Edit messages" permission
   - In groups, also check "Delete messages" permission

2. **Check bot logs:**
   - Look for error messages
   - Common errors:
     - "Permission denied" → Bot doesn't have edit permission
     - "Message can't be edited" → Message type doesn't support captions
     - "Message not found" → Message was deleted before bot could edit

3. **Verify file type:**
   - Video notes and stickers don't support captions
   - Some file types may have restrictions

4. **Check if message already has caption:**
   - Bot won't overwrite existing captions
   - Remove caption manually if you want bot to add one

---

### Issue: Bot not responding at all

**Symptoms:**
- Bot doesn't respond to commands
- Bot doesn't process file uploads

**Solutions:**

1. **Check if bot is running:**
   - Look for "Bot is ready!" message in logs
   - Verify bot process is running
   - Check for error messages

2. **Verify bot token:**
   - Check `.env` file has correct `TELEGRAM_BOT_TOKEN`
   - Get new token from @BotFather if needed
   - Restart bot after changing token

3. **Check internet connection:**
   - Bot needs internet to connect to Telegram
   - Verify server has internet access

4. **Check for errors:**
   - Look at bot logs for error messages
   - Common issues:
     - Invalid bot token
     - Network connectivity issues
     - Python version compatibility

---

### Issue: "Message can't be edited" error

**Symptoms:**
- Bot logs show "Message can't be edited"
- Caption is not added

**Causes:**

1. **Bot doesn't have permission:**
   - Bot must be admin with "Edit messages" permission
   - Fix: Add bot as admin and enable permission

2. **Message is too old:**
   - Telegram limits message editing to 48 hours
   - Fix: Upload files within 48 hours

3. **Message type doesn't support captions:**
   - Video notes and stickers don't support captions
   - Fix: Use different file type

4. **In groups, message is from another user:**
   - Bots can't edit other users' messages in groups
   - Bot should use repost workaround automatically
   - If it doesn't, check bot has "Delete messages" permission

---

### Issue: Duplicate messages in groups

**Symptoms:**
- Original message and new message with caption both appear
- Two copies of the file

**Cause:**
- Bot couldn't delete original message before reposting
- Bot doesn't have "Delete messages" permission

**Solution:**
- Add "Delete messages" permission to bot in group settings
- Bot will then properly delete original before reposting

---

### Issue: Bot works in channels but not groups

**Symptoms:**
- Captions added in channels
- No captions in groups

**Cause:**
- Different permission requirements for groups
- Bot might not have "Delete messages" permission

**Solution:**
- Ensure bot has both "Edit messages" AND "Delete messages" permissions in groups
- Use `/status` command to verify permissions

---

## Debugging Tips

### Enable Debug Logging

To see more detailed logs, you can modify the logging level in `bot.py`:

```python
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Change from INFO to DEBUG
)
```

### Check Bot Status

Use the `/status` command in your channel/group to check:
- If bot is admin
- If bot has required permissions
- Current configuration

### Review Logs

Check bot logs for:
- Error messages
- Warning messages
- Info messages about file processing
- Network errors

### Test with Different File Types

Try uploading:
- Different file types (video, document, photo, audio)
- From different sources (mobile, desktop)
- With and without existing captions

---

## Getting Help

If you're still experiencing issues:

1. **Check logs:** Review bot logs for error messages
2. **Verify setup:** Ensure all requirements are met
3. **Test permissions:** Use `/status` command
4. **Check documentation:** Review README.md and other docs
5. **Report issues:** Include:
   - Error messages from logs
   - Steps to reproduce
   - File types that fail
   - Whether it's mobile or desktop upload

---

## Known Limitations

1. **Mobile filename preservation:**
   - Telegram doesn't always preserve filenames from mobile uploads
   - Bot can't retrieve filenames that Telegram doesn't provide
   - Workaround: Rename files before uploading

2. **Video notes and stickers:**
   - Don't support captions in Telegram
   - Bot will skip these file types

3. **Message age limit:**
   - Messages older than 48 hours can't be edited
   - Bot can't add captions to old messages

4. **Group message editing:**
   - Bots can't edit other users' messages in groups
   - Bot uses repost workaround (requires delete permission)

5. **File size limits:**
   - Telegram has file size limits (50MB free, 4GB premium)
   - Bot doesn't affect these limits

