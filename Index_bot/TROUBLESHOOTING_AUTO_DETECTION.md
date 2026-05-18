# Troubleshooting Auto-Detection

## How Auto-Detection Works

The bot automatically detects channels when:
1. Bot is added as **admin** to a channel
2. Bot has **"Read Messages"** permission
3. A file is uploaded to that channel
4. Bot receives the channel message via `update.channel_post`

## Common Issues

### Issue 1: Bot Not Receiving Channel Messages

**Symptoms:**
- No logs showing "Received message from channel"
- Channels not appearing in `/list_channels`

**Possible Causes:**
1. **Bot is not admin** - Bot must be admin to receive channel posts
2. **Missing permissions** - Bot needs "Read Messages" permission
3. **Bot not in channel** - For private channels, bot must be added as member/admin
4. **No files uploaded** - Auto-detection triggers when a file is uploaded

**Solutions:**
1. Check bot is admin:
   - Channel Settings → Administrators
   - Verify bot is listed as admin
   - Check "Read Messages" permission is enabled

2. For private channels:
   - Add bot as admin (not just member)
   - Give bot "Read Messages" permission

3. Test by uploading a file:
   - Upload any file (video/document) to the channel
   - Check bot logs for "Received message from channel"
   - Run `/test_channel_detection` to verify

### Issue 2: Handler Not Triggering

**Symptoms:**
- Files uploaded but not indexed
- No "Auto-registered channel" logs

**Check:**
1. Run `/test_channel_detection` command
2. Check bot logs: `tail -f bot.log`
3. Look for errors in logs

**Solutions:**
1. Restart bot to ensure handler is registered
2. Check logs for errors
3. Verify `allowed_updates=Update.ALL_TYPES` in bot startup

### Issue 3: Channel Already Exists But Inactive

**Symptoms:**
- Channel was manually added but shows as inactive
- Files not being indexed

**Solution:**
- Use `/remove_channel @channel` then let auto-detection re-add it
- Or manually activate: Channel should auto-activate on first file

## Testing Auto-Detection

### Step 1: Check Current Status
```
/test_channel_detection
```

This shows:
- All registered channels
- Their status (active/inactive)
- Instructions if none found

### Step 2: Test with a Channel

1. **Add bot as admin:**
   - Go to channel settings
   - Add bot as administrator
   - Enable "Read Messages" permission

2. **Upload a test file:**
   - Upload any file to the channel
   - Wait a few seconds

3. **Check logs:**
   ```bash
   tail -f bot.log | grep -i channel
   ```

   You should see:
   ```
   INFO:__main__:Received message from channel: -1001234567890 (Channel Name)
   INFO:__main__:Auto-registering new channel: -1001234567890 - Channel Name
   INFO:__main__:✅ Auto-registered channel: Channel Name
   ```

4. **Verify:**
   ```
   /list_channels
   ```
   Channel should appear in the list

### Step 3: Check Logs

```bash
# View recent channel-related logs
tail -50 bot.log | grep -i "channel\|auto\|register"

# Follow logs in real-time
tail -f bot.log
```

## Manual Testing

If auto-detection isn't working, you can manually add channels:

### For Public Channels:
```
/add_channel @channel_name
```

### For Private Channels:
1. Get channel ID (use @RawDataBot or forward a message)
2. Use in custom lists:
   ```
   /create_list Test -1001234567890
   ```

## Debug Commands

- `/test_channel_detection` - Check detection status
- `/list_channels` - List all registered channels
- `/stats` - View indexing statistics

## Expected Behavior

When working correctly:

1. **File uploaded to channel:**
   ```
   INFO:__main__:Received message from channel: -1001234567890 (My Channel)
   INFO:__main__:Auto-registering new channel: -1001234567890 - My Channel
   INFO:__main__:✅ Auto-registered channel: My Channel
   INFO:__main__:Indexed file: movie.mp4 -> Movie Name
   ```

2. **Channel appears in list:**
   ```
   /list_channels
   📺 Monitored Channels (Auto-detected):
   • My Channel (@mychannel) - ✅ Active
   ```

3. **Files searchable:**
   ```
   /search Movie Name
   🔍 Search Results...
   ```

## Still Not Working?

1. **Check bot permissions:**
   - Must be admin
   - Must have "Read Messages"
   - For private channels: Must be added as member/admin

2. **Check bot logs:**
   ```bash
   tail -100 bot.log
   ```
   Look for errors or warnings

3. **Restart bot:**
   ```bash
   ./stop_all_bots.sh
   ./run_bot.sh
   ```

4. **Test with public channel first:**
   - Easier to debug
   - No permission issues
   - Can verify handler is working

5. **Check Telegram Bot API:**
   - Bot token is valid
   - Bot is not rate-limited
   - No API errors in logs

## Important Notes

- **Auto-detection only works when files are uploaded** - It doesn't scan existing messages
- **Bot must be admin** - Regular members don't receive channel_post updates
- **Private channels work** - But bot must be added as admin first
- **Handler triggers on file upload** - Text messages don't trigger auto-detection
