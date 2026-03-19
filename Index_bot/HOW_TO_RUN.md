# How to Run the Index Bot

## Quick Start

### Option 1: Simple Run (Recommended for testing)
```bash
./run_bot.sh
```

This will:
- Activate the virtual environment
- Start the bot in the foreground (you'll see all output)
- Press `Ctrl+C` to stop

### Option 2: Using Python directly
```bash
source venv/bin/activate
python bot.py
```

### Option 3: Background Run (for production)
```bash
nohup python bot.py > bot.log 2>&1 &
```

Then check logs with:
```bash
tail -f bot.log
```

## Before Running

### 1. Check for Running Instances
```bash
./check_bot_processes.sh
```

If you see other instances running, stop them first:
```bash
./stop_all_bots.sh
```

### 2. Verify Configuration
```bash
source venv/bin/activate
python check_readiness.py
```

All checks should pass before running.

## What to Expect

When the bot starts successfully, you should see:
```
============================================================
🚀 Bot starting...
============================================================
⚠️  IMPORTANT: Make sure no other bot instance is running!
   If you see 409 Conflict errors, stop other instances first.
   Use: ./stop_all_bots.sh or: pkill -f 'python.*bot.py'
============================================================
INFO:tmdb_helper:TMDB API initialized successfully
INFO:__main__:Checking webhook status...
INFO:__main__:✅ No webhook found, using polling mode
INFO:__main__:✅ Pending updates cleared
INFO:telegram.ext.Application:Application started
```

## Troubleshooting

### Bot won't start
1. Check if another instance is running: `./check_bot_processes.sh`
2. Stop all instances: `./stop_all_bots.sh`
3. Wait 10 seconds
4. Try again

### 409 Conflict Error
- Another bot instance is running
- Run: `./stop_all_bots.sh`
- Wait 10-15 seconds
- Start again

### Configuration Errors
- Run: `python check_readiness.py`
- Fix any issues shown
- Make sure `.env` file has `BOT_TOKEN` and `ADMIN_USER_IDS`

## Stopping the Bot

### If running in foreground:
- Press `Ctrl+C`

### If running in background:
```bash
pkill -f "Index_bot.*bot.py"
```

Or use:
```bash
./stop_all_bots.sh
```

## Next Steps After Starting

1. **Add channels to monitor:**
   - Add your bot as admin to channels
   - Use: `/add_channel @channel_username`

2. **Test the bot:**
   - Send `/start` to your bot
   - Try `/list_channels`
   - Try `/stats`

3. **Monitor activity:**
   - Watch the console output
   - Check for any errors
   - Files will be automatically indexed as they're uploaded

## Production Deployment

For running 24/7, consider:
- Using `systemd` service (Linux)
- Using `screen` or `tmux` for session management
- Setting up log rotation
- Monitoring with tools like `supervisor`

Example systemd service:
```ini
[Unit]
Description=Index Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Index_bot
ExecStart=/path/to/venv/bin/python bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```
