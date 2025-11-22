# Quick Start Guide

## 1. Setup

```bash
cd upload_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure

Create a `.env` file:
```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

## 3. Run Bot

```bash
python bot.py
```

## 4. Basic Usage

### Upload files without metadata:
```
/upload /path/to/your/files
```

### Upload with CSV metadata:
```
/upload /path/to/your/files --csv metadata.csv
```

### Upload with grouping:
```
/upload /path/to/your/files --csv metadata.csv --group-by category
```

## 5. Create Metadata CSV

Use the template: `metadata_template.csv`

Example:
```csv
filename,category,channel,description
photo1.jpg,photos,@my_channel,Family photo
doc1.pdf,documents,@my_docs,Report
```

## 6. Test

1. Create a test directory with some files
2. Create a simple CSV with metadata
3. Run `/upload` command
4. Check the bot's response and uploaded files

## Next Steps

- Read `README.md` for detailed documentation
- Check `METADATA_FORMAT.md` for metadata specifications
- Review `FEASIBILITY_ANALYSIS.md` for technical details

