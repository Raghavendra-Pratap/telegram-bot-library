# Production Deployment Guide

## Enterprise-Level Production Setup

This guide provides a production-ready deployment solution with proper process management, error handling, and reliability features.

## Features

✅ **Process Management** - Ensures only one instance runs at a time  
✅ **Database Lock Handling** - Automatic retry with cleanup  
✅ **Graceful Shutdown** - Proper cleanup on stop  
✅ **PID File Management** - Track running instances  
✅ **Session Cleanup** - Removes stale SQLite files  
✅ **Error Recovery** - Retry logic for transient failures  
✅ **Logging** - Centralized log file management  

## Quick Start

### Start the Bot

```bash
cd TG_download_bot
./start_production.sh start
```

### Stop the Bot

```bash
./start_production.sh stop
```

### Restart the Bot

```bash
./start_production.sh restart
```

### Check Status

```bash
./start_production.sh status
```

## Production Script Commands

| Command | Description |
|---------|-------------|
| `./start_production.sh start` | Start the bot (stops existing instances first) |
| `./start_production.sh stop` | Stop the bot gracefully |
| `./start_production.sh restart` | Restart the bot |
| `./start_production.sh status` | Check if bot is running |

## How It Works

### 1. Process Management

- **PID File**: Tracks the running bot process
- **Instance Check**: Prevents multiple instances from running
- **Clean Shutdown**: Stops existing instances before starting new one

### 2. Database Lock Handling

The bot automatically handles SQLite database locks:

- **Retry Logic**: 3 attempts with 5-second delays
- **Stale File Cleanup**: Removes `.journal`, `.wal`, and `.shm` files
- **Clear Error Messages**: Tells you exactly what to do

### 3. Session File Management

Automatically cleans up stale SQLite files:
- `premium_account.session-journal` (write-ahead log journal)
- `premium_account.session-wal` (write-ahead log)
- `premium_account.session-shm` (shared memory)

## Troubleshooting

### Database Lock Error

**Error**: `database is locked`

**Solution**:
```bash
./start_production.sh stop
sleep 5
./start_production.sh start
```

### Bot Won't Start

1. **Check if another instance is running**:
   ```bash
   ./start_production.sh status
   ```

2. **Force stop all instances**:
   ```bash
   ./start_production.sh stop
   pkill -9 -f "python.*bot.py"
   ```

3. **Clean up session files**:
   ```bash
   rm -f premium_account.session-journal
   rm -f premium_account.session-wal
   rm -f premium_account.session-shm
   ```

4. **Start again**:
   ```bash
   ./start_production.sh start
   ```

### View Logs

```bash
# View last 50 lines
tail -50 bot.log

# Follow logs in real-time
tail -f bot.log

# Search for errors
grep -i error bot.log | tail -20
```

## Manual Start (For Debugging)

If you need to run the bot manually to see logs:

```bash
cd TG_download_bot
source venv/bin/activate
python bot.py
```

Press `Ctrl+C` to stop.

## Production Deployment Checklist

- [ ] Virtual environment created and activated
- [ ] `.env` file configured with all required variables
- [ ] MTProto session authenticated (run bot interactively once)
- [ ] Tested `./start_production.sh start` successfully
- [ ] Verified bot responds to commands in Telegram
- [ ] Tested file download functionality
- [ ] Set up log rotation (optional, for long-running deployments)
- [ ] Configured system service (optional, for auto-start on boot)

## System Service (Optional)

For auto-start on system boot, create a systemd service:

```bash
sudo nano /etc/systemd/system/tg-download-bot.service
```

Add:
```ini
[Unit]
Description=TG Download Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/TG_download_bot
ExecStart=/path/to/TG_download_bot/start_production.sh start
ExecStop=/path/to/TG_download_bot/start_production.sh stop
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl enable tg-download-bot
sudo systemctl start tg-download-bot
```

## Monitoring

### Check Bot Health

```bash
# Check if running
./start_production.sh status

# Check logs for errors
tail -100 bot.log | grep -i error

# Check MTProto status
tail -100 bot.log | grep -i "premium\|mtproto"
```

### Performance Monitoring

Monitor download speeds and success rates in logs:
```bash
grep "Download complete" bot.log | tail -20
grep "Download progress" bot.log | tail -20
```

## Security Best Practices

1. **File Permissions**: Ensure `.env` and session files are not world-readable
   ```bash
   chmod 600 .env
   chmod 600 premium_account.session*
   ```

2. **Log Rotation**: Set up log rotation to prevent disk space issues
   ```bash
   # Add to /etc/logrotate.d/tg-download-bot
   /path/to/TG_download_bot/bot.log {
       daily
       rotate 7
       compress
       missingok
       notifempty
   }
   ```

3. **Firewall**: Only expose necessary ports (file server port if needed)

## Support

For issues:
1. Check logs: `tail -100 bot.log`
2. Check status: `./start_production.sh status`
3. Try restart: `./start_production.sh restart`
4. Review this guide's troubleshooting section
