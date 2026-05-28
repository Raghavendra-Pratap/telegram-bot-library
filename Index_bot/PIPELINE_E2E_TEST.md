# End-to-end pipeline test guide

Use this checklist to verify the full flow: **configure → plan → upload → index → (optional route) → publish**.

## Prerequisites

1. **Telethon session** (once):
   ```bash
   cd Index_bot && source venv/bin/activate
   python telethon_login.py
   ```
2. **Bot running** (live index + job linking):
   ```bash
   python bot.py
   ```
3. **Portal** (optional, for web admin):
   ```bash
   python run_portal.py
   ```
4. Create Telegram channels for each lane; add the bot as **admin** with post rights on source/target channels.

## 1. One-time setup

### Telegram bot

`/menu` → **⚙️ Library setup** → **📤 Pipeline upload targets**

| Upload type | Set as source channel |
|-------------|------------------------|
| Media | Your movies/series storage channel |
| Course | Course staging channel |
| Archive | PDFs / ebooks channel |
| Shortform | Reels channel (optional) |
| Mixed | Historical **ingest sink** (mixed dumps) |

Then **📺 Set media publish channel** → your watch library (TMDB catalog cards).

### Portal (optional)

Admin sidebar → **Upload pipeline** — same defaults + readiness checklist.

### Environment (optional)

```env
PIPELINE_CLASSIFY_INGEST=true   # default on — filename → lane on ingest sink
PIPELINE_AUTO_ROUTE=true        # forward ingest → bucket channels via Telethon
AUTO_PUBLISH_WATCH=false        # keep off until you want auto catalog cards
```

Restart `bot.py` after changing `.env`.

## 2. Bulk upload job test (course or media)

1. Put 2–3 test files in a folder with `local_path` friendly names, e.g. `01 - Intro.mp4`.
2. Bot: **Upload pipeline** → **New upload job** → pick lane → folder path.
3. Open job — confirm **Source channel** is pre-filled from pipeline setup.
4. **Upload all new** → **▶️ Start upload** (or CLI):
   ```bash
   python course_upload.py --job <id> --delay 3
   ```
5. Watch bot logs: `Indexed file: …` and job item → `indexed`.
6. Bot: **📊 Pipeline status** — readiness checks green where applicable.

## 3. Mixed ingest + classify + route

1. Post different file types to the **ingest sink** (or forward from another channel):
   - `01 - Lesson.mp4` → should classify as **course**
   - `Movie.Name.2024.mkv` → **media**
   - `notes.pdf` → **archive**
2. With `PIPELINE_CLASSIFY_INGEST=true`, check DB/portal: `content_lane` matches guess.
3. With `PIPELINE_AUTO_ROUTE=true`:
   - Upload rows get `pipeline_route_status=pending` then `routed`
   - Files should appear in the matching **pipeline source** channel
4. If queue stuck: **Upload pipeline** → **Pipeline status** → **Run route queue**.

## 4. Duplicate hold test

1. Upload the same file twice (same fingerprint) to a monitored channel.
2. Second copy → **duplicate_hold**.
3. Bot: **Upload pipeline** → **Duplicates** → Skip or Index anyway.
4. Portal: **Upload pipeline** → Duplicate holds list.

## 5. Publish flow (manual)

| Step | Action | Expected |
|------|--------|----------|
| Index | File lands in source channel | Row in DB, lane set |
| TMDB (media) | Portal **Pending** or bot pick | `tmdb_id` on title |
| Library | Course vault → **Publish to library** | `library_visible` + `distribution_approved` |
| Watch catalog | **Watch library** → publish slot | Card in media publish channel |

Media watch catalog requires **media lane + TMDB**. Courses do not get TMDB catalog cards.

With `AUTO_PUBLISH_WATCH=true`, library-visible media with TMDB may auto-publish after confirm.

## 6. Quick status commands

| Where | What |
|-------|------|
| Bot | Upload pipeline → **Pipeline status** |
| Portal | Admin → **Upload pipeline** |
| CLI | `python upload_planner.py … --dry-run` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Job has no source channel | Library setup → Pipeline upload targets |
| Telethon upload fails | `telethon_login.py`, `API_ID`/`API_HASH` in `.env` |
| Not indexed | `bot.py` must be running on the upload machine |
| Route failed | Bot admin in source + target; check `pipeline_route_error` in logs |
| Course in watch catalog | Should be blocked — only media + TMDB publishes |

See also [UPLOAD_PIPELINE.md](UPLOAD_PIPELINE.md).
