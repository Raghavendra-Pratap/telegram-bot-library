# bots_config.json updates

Use the appropriate block for each branch.

## Development branch (all bots enabled)

```json
{
  "bots": [
    {
      "id": "caption_bot",
      "name": "Caption Bot",
      "description": "Automatically sets filename as caption when files are uploaded",
      "directory": "caption_bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": null,
      "enabled": true
    },
    {
      "id": "download_bot",
      "name": "Download Bot",
      "description": "Video downloader bot for YouTube, Reddit, Twitter, Instagram, etc.",
      "directory": "down_oad_bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": null,
      "enabled": true
    },
    {
      "id": "index_bot",
      "name": "Index Bot",
      "description": "Indexes channel uploads, TMDB metadata, search/library, watch catalog",
      "directory": "Index_bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": null,
      "enabled": true,
      "env_required": ["BOT_TOKEN", "ADMIN_USER_IDS"],
      "pid_file": ".bot.pid"
    },
    {
      "id": "name_bot",
      "name": "Name Bot",
      "description": "Automatically sets filename as caption with HTTP server",
      "directory": "name-bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": 8080,
      "enabled": true
    },
    {
      "id": "tg_download_bot",
      "name": "TG Download Bot",
      "description": "Fast file downloads using Premium Account with file server",
      "directory": "TG_download_bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": 8081,
      "enabled": true
    },
    {
      "id": "upload_bot",
      "name": "Upload Bot",
      "description": "File upload with metadata and grouping",
      "directory": "upload_bot",
      "script": "bot.py",
      "venv_path": "../.venv",
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

## Main branch (name-bot only)

```json
{
  "bots": [
    {
      "id": "name_bot",
      "name": "Name Bot",
      "description": "Automatically sets filename as caption with HTTP server",
      "directory": "name-bot",
      "script": "bot.py",
      "venv_path": "../.venv",
      "port": 8080,
      "enabled": true
    }
  ],
  "dashboard": {
    "port": 5000,
    "host": "0.0.0.0"
  }
}
```
