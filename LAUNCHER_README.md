# 🤖 Telegram Bot Launcher

A unified launcher system to manage and monitor all your Telegram bots from a single interface.

## Features

- ✅ **Interactive Menu**: Easy-to-use command-line interface
- ✅ **Selective Launch**: Choose which bots to run
- ✅ **Process Monitoring**: Auto-restart crashed bots
- ✅ **Web Dashboard**: Beautiful web interface for monitoring (optional)
- ✅ **Statistics Tracking**: Track uptime, restarts, and errors
- ✅ **Port Management**: Handle bots with HTTP servers on different ports
- ✅ **Automatic Dependency Checking**: Checks and installs missing dependencies automatically
- ✅ **Smart Dependency Management**: Verifies dependencies for launcher and each bot before starting

## Quick Start

### 1. Install Dependencies (Optional)

The launcher will automatically check and install dependencies when you run it. However, you can manually install them first:

```bash
pip install -r launcher_requirements.txt
```

**Note**: The launcher will automatically:
- Check if Flask is installed (for dashboard)
- Check each bot's dependencies from their `requirements.txt`
- Prompt to install missing dependencies (or auto-install if configured)

### 2. Configure Bots

Edit `bots_config.json` to customize bot settings. The default configuration includes all bots in the repository.

### 3. Run the Launcher

```bash
python bot_launcher.py
```

Or make it executable:

```bash
chmod +x bot_launcher.py
./bot_launcher.py
```

## Usage

### Interactive Menu

When you run the launcher, you'll see an interactive menu:

```
🤖 Telegram Bot Launcher
================================================================================

Available Bots:
  1. Caption Bot           - Automatically sets filename as caption... [🔴 Stopped]
  2. Download Bot          - Video downloader bot for YouTube...      [🔴 Stopped]
  3. Index Bot             - Search for movies and series...           [🔴 Stopped]
  4. Name Bot              - Automatically sets filename as caption... [🔴 Stopped]
  5. TG Download Bot       - Fast file downloads using Premium...      [🔴 Stopped]
  6. Upload Bot            - File upload with metadata...              [🔴 Stopped]

Actions:
  1. Start bot(s)
  2. Stop bot(s)
  3. Restart bot(s)
  4. Show status
  5. Show statistics
  6. Start monitoring (auto-restart)
  7. Stop monitoring
  8. Start dashboard (web interface)
  9. Exit
```

### Starting Bots

1. Select option `1` to start bots
2. Enter bot numbers (comma-separated) or `all` to start all bots
   - Example: `1,3,5` to start bots 1, 3, and 5
   - Example: `all` to start all bots
3. The launcher will automatically:
   - Check if all dependencies are installed
   - Install missing dependencies (with your confirmation or automatically)
   - Start the selected bots

### Web Dashboard

1. Select option `8` to start the web dashboard
2. Open your browser to `http://localhost:5000`
3. Monitor and control bots from the web interface

The dashboard provides:
- Real-time status updates (auto-refreshes every 3 seconds)
- Start/Stop/Restart buttons for each bot
- Uptime tracking
- Error messages
- Statistics overview

### Monitoring

Enable auto-restart monitoring:
1. Select option `6` to start monitoring
2. If a bot crashes, it will automatically restart
3. Select option `7` to stop monitoring

### Viewing logs of active bots

When you start bots via the launcher, each bot’s stdout and stderr are written to a **log file** in the `logs/` folder at the project root.

| What you want | Command |
|---------------|--------|
| **Live log for one bot** | `tail -f logs/<bot_id>.log` |
| **Last 50 lines** | `tail -50 logs/<bot_id>.log` |
| **Search for errors** | `grep -i error logs/<bot_id>.log` |

**Bot IDs** (same as in the menu): `caption_bot`, `download_bot`, `index_bot`, `name_bot`, `tg_download_bot`, `upload_bot`.

**Examples:**
```bash
# Follow TG Download Bot logs live
tail -f logs/tg_download_bot.log

# Last 100 lines of Name Bot
tail -100 logs/name_bot.log

# Errors in Caption Bot
grep -i error logs/caption_bot.log
```

The launcher also prints the log path when a bot starts, e.g. `Logs: tail -f logs/tg_download_bot.log`.

## Configuration

### `bots_config.json`

Edit this file to customize bot settings:

```json
{
  "bots": [
    {
      "id": "caption_bot",
      "name": "Caption Bot",
      "description": "Automatically sets filename as caption...",
      "directory": "caption_bot",
      "script": "bot.py",
      "venv_path": "venv",
      "port": null,
      "enabled": true
    }
  ],
  "dashboard": {
    "port": 5000,
    "host": "0.0.0.0"
  }
}
```

**Fields:**
- `id`: Unique identifier for the bot
- `name`: Display name
- `description`: Bot description
- `directory`: Relative path to bot directory
- `script`: Python script to run (usually `bot.py`)
- `venv_path`: Path to virtual environment (relative to bot directory)
- `port`: HTTP server port (if applicable, `null` otherwise)
- `enabled`: Whether this bot appears in the launcher

### Dashboard Port

To change the dashboard port, edit `bots_config.json`:

```json
{
  "dashboard": {
    "port": 8080,
    "host": "0.0.0.0"
  }
}
```

## Running Multiple Bots

The launcher can run multiple bots simultaneously. Each bot runs in its own process:

- **Telegram Bots**: Use polling (no port conflicts)
- **Bots with HTTP Servers**: Configure different ports in `bots_config.json`

### Port Configuration

If you have multiple bots with HTTP servers, make sure they use different ports. The default configuration uses:

- **name_bot**: Port 8080
- **tg_download_bot**: Port 8081
- **Dashboard**: Port 5000

To change ports, edit `bots_config.json`:

```json
{
  "id": "name_bot",
  "port": 8080
},
{
  "id": "tg_download_bot",
  "port": 8081
}
```

**Important**: If you change ports in `bots_config.json`, also update the bot's `.env` file to match:
- For `name_bot`: Set `HTTP_SERVER_PORT=8080` in `name-bot/.env`
- For `tg_download_bot`: Set `FILE_SERVER_PORT=8081` in `TG_download_bot/.env`

## Statistics

The launcher tracks:
- **Start Count**: How many times each bot was started
- **Stop Count**: How many times each bot was stopped
- **Restart Count**: How many times each bot was restarted
- **Total Uptime**: Cumulative uptime in hours
- **Errors**: List of recent errors

View statistics from the menu (option 5) or the web dashboard.

## Dependency Management

The launcher automatically manages dependencies:

### Automatic Checks

- **On Startup**: Checks launcher dependencies (Flask for dashboard)
- **Before Starting Bots**: Checks each bot's dependencies from `requirements.txt`
- **Auto-Installation**: Automatically installs missing dependencies when starting bots

### How It Works

1. Reads each bot's `requirements.txt` file
2. Checks if packages are installed in the bot's virtual environment
3. Installs missing packages using `pip install -r requirements.txt`
4. Verifies installation before starting the bot

### Manual Dependency Check

You can manually check dependencies by:
1. Starting a bot (option 1)
2. The launcher will show which dependencies are missing
3. Choose to install them automatically or manually

### Troubleshooting Dependencies

If dependency installation fails:
1. Check that the bot's virtual environment exists
2. Verify Python is accessible in the venv
3. Check internet connection (for pip downloads)
4. Review error messages in the launcher output

## Troubleshooting

### Bot Won't Start

1. Check if the bot directory exists
2. Verify the virtual environment is set up
3. Check if `.env` file exists in the bot directory
4. Review error messages in the launcher output
5. Check if dependencies were installed correctly

### Port Conflicts

If you see port conflicts:
1. Check which ports are in use: `lsof -i :PORT`
2. Update `bots_config.json` to use different ports
3. Update bot's `.env` file to match the new port

### Process Already Running

If a bot says it's already running:
1. Check running processes: `ps aux | grep bot.py`
2. Stop the process manually: `pkill -f "bot.py"`
3. Or use the launcher's stop function

## Keyboard Shortcuts

- `Ctrl+C`: Gracefully shutdown all bots and exit
- The launcher handles SIGTERM for clean shutdowns

## Examples

### Start 3 Specific Bots

```
Select action (1-9): 1
Select bots to start (comma-separated numbers, or 'all'): 1,3,5
```

### Monitor All Bots

```
Select action (1-9): 1
Select bots to start (comma-separated numbers, or 'all'): all
Select action (1-9): 6  # Start monitoring
Select action (1-9): 8  # Start dashboard
```

### View Status

```
Select action (1-9): 4
```

Output:
```
📊 Bot Status
================================================================================

🟢 Caption Bot          | PID: 12345 | Uptime: 0:15:32
🟢 Download Bot         | PID: 12346 | Uptime: 0:10:15 | Port: 8080
🔴 Index Bot            | Stopped
```

## Architecture

- **bot_launcher.py**: Main launcher script with interactive menu
- **dashboard.py**: Flask web server for web interface
- **bots_config.json**: Configuration file for all bots

Each bot runs as a separate subprocess, allowing:
- Independent lifecycle management
- Isolated crashes (one bot crashing doesn't affect others)
- Resource monitoring per bot
- Easy scaling

## Notes

- Each bot must have its own virtual environment
- Each bot should have its own `.env` file with configuration
- The launcher doesn't modify bot configurations
- All bots run in the background when started
- Use the web dashboard for remote monitoring
