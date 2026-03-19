# Telegram File Upload Bot with Metadata & Grouping

A comprehensive Telegram bot for uploading files with folder structure metadata, CSV/Google Sheets integration, flexible grouping, and channel selection.

> **Branch status:** Under development. Available on `development` branch only.

## Features

- 📁 **Folder Structure Metadata**: Automatically includes directory tree paths in file captions
- 📊 **CSV/Google Sheets Support**: Load metadata from CSV files or Google Sheets
- 🔗 **Flexible Grouping**: Group files by any metadata column or upload without grouping
- 📺 **Channel Selection**: Specify different channels per file/group via metadata
- 🎬 **Upload Options**: Control upload format (document, photo, video, audio) and quality (HD, high, etc.)
- 📤 **Multiple Grouping Styles**: 
  - Media groups (files appear together, max 10)
  - Sequential uploads (with shared captions)

## Prerequisites

- Python 3.8 or higher
- Telegram Bot Token (get from [@BotFather](https://t.me/botfather))
- FFmpeg (optional, for video processing)
- Google Service Account credentials (optional, for Google Sheets)

## Installation

1. **Navigate to the upload bot directory:**
```bash
cd upload_bot
```

2. **Create a shared virtual environment (recommended):**
```bash
./scripts/setup_env.sh
```

3. **Install dependencies for this bot:**
```bash
./scripts/install_deps.sh upload
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

4. **Set up environment variables:**
```bash
cp .env.example .env
```

Edit `.env` and add your configuration:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
ENABLE_USER_VERIFICATION=false
ALLOWED_USER_IDS=
GOOGLE_SHEETS_CREDENTIALS_PATH=./credentials.json
```

## Google Sheets Setup (Optional)

If you want to use Google Sheets for metadata:

1. **Create a Google Cloud Project:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing one

2. **Enable Google Sheets API:**
   - Navigate to "APIs & Services" > "Library"
   - Search for "Google Sheets API" and enable it

3. **Create Service Account:**
   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "Service Account"
   - Create a service account and download the JSON key file

4. **Share Google Sheet:**
   - Open your Google Sheet
   - Click "Share" and add the service account email (from JSON file)
   - Give it "Viewer" or "Editor" permissions

5. **Save Credentials:**
   - Save the downloaded JSON file as `credentials.json` in the bot directory
   - Update `.env`: `GOOGLE_SHEETS_CREDENTIALS_PATH=./credentials.json`

## Usage

### Basic Upload

```
/upload /path/to/directory
```

### With CSV Metadata

```
/upload /path/to/directory --csv metadata.csv
```

### With Google Sheets

```
/upload /path/to/directory --sheet https://docs.google.com/spreadsheets/d/...
```

### With Grouping

```
/upload /path/to/directory --csv metadata.csv --group-by category
```

### With Channel Selection

```
/upload /path/to/directory --csv metadata.csv --channel @my_channel
```

### Options

- `--csv <path>`: Path to CSV metadata file
- `--sheet <url>`: Google Sheets URL or ID
- `--sheet-name <name>`: Specific sheet tab name (default: first sheet)
- `--group-by <column>`: Group files by metadata column
- `--group-style <style>`: `media_group` or `sequential` (default: `media_group`)
- `--channel <channel>`: Default channel (@channel or ID)
- `--no-tree`: Don't include tree structure in captions

## Metadata Format

See `METADATA_FORMAT.md` for detailed CSV/Google Sheets format specifications.

### Example CSV

```csv
filename,file_path,category,description,channel,upload_as,quality
photo1.jpg,photos/2024/photo1.jpg,photos,Family photo,@my_photos,photo,HD
doc1.pdf,documents/doc1.pdf,documents,Report,@my_docs,document,
```

### Required Columns

- `filename` or `file_path`: For file matching

### Optional Columns

- `category`: Grouping field
- `description`: File description
- `channel`: Target channel (@channel or ID)
- `upload_as`: `document`, `photo`, `video`, `audio`, or `auto`
- `quality`: `HD`, `high`, `standard`, or `low` (for videos)
- `tags`: Comma-separated tags
- `group_by`: Explicit grouping value
- `skip`: `true`/`false` to skip file
- `priority`: Upload priority (1-10)

## Commands

- `/start` - Show welcome message
- `/help` - Show detailed help
- `/upload <path> [options]` - Upload files

## Project Structure

```
upload_bot/
├── bot.py                 # Main bot file
├── config.py              # Configuration
├── requirements.txt       # Dependencies
├── metadata/
│   ├── csv_reader.py      # CSV metadata reader
│   ├── sheets_reader.py   # Google Sheets reader
│   └── matcher.py         # File-metadata matcher
├── uploaders/
│   └── file_uploader.py   # File upload handler
├── utils/
│   ├── file_scanner.py    # Directory scanner
│   └── tree_builder.py    # Tree metadata builder
└── metadata_template.csv  # Example CSV template
```

## Configuration

Edit `config.py` or set environment variables:

- `UPLOAD_DELAY`: Delay between uploads (seconds)
- `BATCH_SIZE`: Files per batch
- `DEFAULT_GROUP_STYLE`: Default grouping style
- `SHOW_TREE_SEPARATOR`: Show tree separator messages
- `MAX_FILE_SIZE_FREE`: Max file size for free accounts (50MB)
- `MAX_FILE_SIZE_PREMIUM`: Max file size for premium (4GB)

## Limitations

- **File Size**: 
  - Free Telegram: 50MB limit
  - Premium Telegram: 4GB limit
- **Media Groups**: Limited to 10 files per group
- **Rate Limiting**: Telegram has rate limits; bot includes delays
- **Google Sheets**: Requires service account setup

## Troubleshooting

### CSV Not Found
- Use absolute paths or paths relative to the upload directory
- Check file permissions

### Google Sheets Authentication Failed
- Verify service account credentials JSON file
- Ensure service account email has access to the sheet
- Check that Google Sheets API is enabled

### Files Not Matching Metadata
- Check filename/file_path columns match exactly
- Try different matching strategies (exact, path, fuzzy)
- Review unmatched files in logs

### Upload Failures
- Check file size limits
- Verify bot has access to target channel
- Check network connectivity
- Review error logs

## License

This project is for personal use. Use responsibly and respect platform Terms of Service.

