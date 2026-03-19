# Update Queue Feature

## 🎯 Overview

The bot now includes an **update queue system** that automatically fetches and processes missed messages when the bot restarts. This ensures **zero failed attempts** - no files are missed even when the bot was offline.

## ✅ How It Works

### When Bot Starts:

1. **Check for Missed Updates**
   - Bot queries Telegram API for pending updates
   - Telegram stores updates for up to **24 hours**

2. **Filter File Uploads**
   - Only processes file-related updates (videos, documents, photos, etc.)
   - Ignores old commands and non-file messages

3. **Process Queue**
   - Processes missed file uploads in order
   - Adds captions to files that arrived while bot was offline
   - Limits processing to prevent slow startup (configurable)

4. **Resume Normal Operation**
   - After queue processing, bot resumes normal polling
   - Future updates processed in real-time

## 📋 Configuration

### Enable/Disable Queue

```env
# Enable update queue (default: true)
ENABLE_UPDATE_QUEUE=true

# Maximum updates to process on startup (default: 100)
MAX_QUEUE_UPDATES=100
```

### Settings Explained

- **ENABLE_UPDATE_QUEUE**: Set to `false` to disable queue processing
- **MAX_QUEUE_UPDATES**: Maximum number of updates to process on startup
  - Higher = process more missed files, but slower startup
  - Lower = faster startup, but may skip some old files
  - Recommended: 100 for normal use

## 🔄 Workflow Example

### Scenario: Bot Was Offline

1. **User uploads file** → Telegram stores update
2. **Bot is offline** → Update remains in Telegram queue
3. **Bot restarts** → Queue processing begins
4. **Bot fetches missed updates** → Finds file upload
5. **Bot processes file** → Adds caption automatically
6. **User sees caption** → No failed attempt!

### Timeline:

```
10:00 AM - User uploads file (bot offline)
10:05 AM - Bot restarts
10:05 AM - Bot processes queue → Finds file
10:05 AM - Bot adds caption → Success!
```

## 🚀 Benefits

### ✅ Zero Failed Attempts
- Files uploaded while bot was offline are processed
- No manual intervention needed
- Automatic recovery

### ✅ Reliable Processing
- Telegram stores updates for 24 hours
- Bot processes them on restart
- Ensures no files are missed

### ✅ Smart Filtering
- Only processes file uploads
- Ignores old commands
- Efficient queue processing

## 📊 Logs

When queue processing runs, you'll see:

```
📥 Checking for missed updates in queue...
📦 Found 5 missed file uploads in queue
   Processing missed files...
✅ Processed 5/5 missed file uploads
```

## ⚙️ Technical Details

### How Telegram Stores Updates

- Telegram keeps updates for **up to 24 hours**
- Updates are stored server-side
- Available via `getUpdates` API
- Cleared after acknowledgment

### Queue Processing Flow

1. Bot calls `getUpdates()` on startup
2. Filters for file-related updates
3. Processes each update using application handlers
4. Acknowledges updates to clear queue
5. Resumes normal polling

### Rate Limiting

- Small delay (0.5s) between each queued update
- Prevents hitting Telegram rate limits
- Configurable via `MAX_QUEUE_UPDATES`

## 🔧 Troubleshooting

### Queue Not Processing

**Check:**
1. `ENABLE_UPDATE_QUEUE=true` in `.env`
2. Bot logs show "Checking for missed updates"
3. Updates are within 24-hour window

### Too Many Updates

**Solution:**
- Reduce `MAX_QUEUE_UPDATES` for faster startup
- Or increase for more thorough processing

### Slow Startup

**Solution:**
- Reduce `MAX_QUEUE_UPDATES` (e.g., 50 instead of 100)
- Or disable queue: `ENABLE_UPDATE_QUEUE=false`

## 💡 Best Practices

1. **Keep queue enabled** - Ensures no missed files
2. **Set reasonable limit** - 100 updates is usually sufficient
3. **Monitor logs** - Check queue processing on startup
4. **24-hour window** - Telegram only stores updates for 24 hours

## 🎯 Summary

The update queue feature ensures:
- ✅ **No failed attempts** - All files processed
- ✅ **Automatic recovery** - No manual intervention
- ✅ **Reliable operation** - Works even after downtime
- ✅ **Smart processing** - Only processes relevant updates

**Your bot will never miss a file upload, even after being offline! 🎉**
