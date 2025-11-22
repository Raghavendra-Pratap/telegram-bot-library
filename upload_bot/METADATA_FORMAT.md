# Metadata Format Specification

## CSV/Google Sheets Format

The metadata file should contain information about files to be uploaded. The format is flexible and supports various columns.

### Required Columns

| Column Name | Description | Example | Notes |
|------------|-------------|---------|-------|
| `filename` | Exact filename or relative path | `file1.jpg` or `folder1/file1.jpg` | Used for matching files |
| `file_path` | Full relative path from root | `photos/2024/file1.jpg` | Alternative to filename |

**Note**: At least one of `filename` or `file_path` must be present for file matching.

### Optional Columns

| Column Name | Description | Example | Notes |
|------------|-------------|---------|-------|
| `category` | Category/grouping field | `photos`, `documents`, `videos` | Used for grouping uploads |
| `tags` | Comma-separated tags | `vacation,2024,family` | For organization |
| `description` | File description | `Family photo from vacation` | Added to caption |
| `channel` | Target Telegram channel username/ID | `@my_channel` or `-1001234567890` | Where to upload |
| `group_by` | Grouping column value | `project1`, `2024-01` | Override default grouping |
| `upload_as` | Upload format | `document`, `photo`, `video`, `auto` | Telegram upload type |
| `quality` | Video quality | `HD`, `high`, `standard` | For video files |
| `caption` | Custom caption | `Custom caption text` | Override auto-generated caption |
| `skip` | Skip this file | `true`, `false`, `1`, `0` | Don't upload if true |
| `priority` | Upload priority | `1`, `2`, `3` | Lower number = higher priority |

### Example CSV Format

```csv
filename,file_path,category,description,channel,upload_as,quality,tags
photo1.jpg,photos/2024/photo1.jpg,photos,Family vacation photo,@my_photos,photo,HD,vacation,2024
doc1.pdf,documents/reports/doc1.pdf,documents,Monthly report,@my_docs,document,,reports
video1.mp4,videos/events/video1.mp4,videos,Event recording,@my_videos,video,HD,events,2024
```

### Google Sheets Format

Same column structure as CSV. The bot will read from the first sheet (or specified sheet name).

### File Matching Strategy

The bot will try to match files using the following priority:

1. **Exact filename match**: Match by `filename` column
2. **Path match**: Match by `file_path` column
3. **Partial path match**: Match if file path contains the `file_path` value
4. **Fuzzy match**: Match by similar filename (if enabled)

### Grouping

Files can be grouped by any column. Common grouping columns:
- `category`: Group by category
- `channel`: Group by destination channel
- `tags`: Group by tags (first tag)
- `group_by`: Use explicit grouping column

### Upload Options

#### `upload_as` Values:
- `auto`: Bot decides based on file type (default)
- `document`: Upload as document (no preview)
- `photo`: Upload as photo (with preview)
- `video`: Upload as video (with preview)
- `audio`: Upload as audio (with preview)

#### `quality` Values (for videos):
- `HD`: High quality (default)
- `high`: High quality
- `standard`: Standard quality
- `low`: Lower quality (smaller file)

### Channel Format

Channels can be specified as:
- Username: `@channel_name`
- Channel ID: `-1001234567890`
- Chat ID: `1234567890`

If not specified, files upload to the current chat.

### Example Use Cases

#### Use Case 1: Simple Upload with Categories
```csv
filename,category
file1.jpg,photos
file2.jpg,photos
file3.pdf,documents
```

#### Use Case 2: Channel-Specific Uploads
```csv
filename,category,channel
photo1.jpg,photos,@my_photos
doc1.pdf,documents,@my_docs
video1.mp4,videos,@my_videos
```

#### Use Case 3: Custom Captions and Grouping
```csv
filename,category,description,group_by
photo1.jpg,photos,Event photo 1,event_2024
photo2.jpg,photos,Event photo 2,event_2024
photo3.jpg,photos,Event photo 3,event_2024
```

#### Use Case 4: Selective Upload with Priority
```csv
filename,category,priority,skip
important1.pdf,documents,1,false
important2.pdf,documents,1,false
old_file.pdf,documents,3,true
```

## Metadata Template

A template CSV file will be provided at `upload_bot/metadata_template.csv` for easy setup.

