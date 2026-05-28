# Upload pipeline

Smart ingest with **fingerprints**, **content lanes**, **bulk upload jobs**, and a **course vault**.

**End-to-end test checklist:** [PIPELINE_E2E_TEST.md](PIPELINE_E2E_TEST.md)

## Admin menu (Telegram)

`/menu` → **📤 Upload pipeline**

### Bot workflow (recommended)

1. **➕ New upload job** — pick content type (course / media / archive / shortform)
2. **📁 Scan folder**, **📄 Use file path(s)**, or **📄 CSV** — paths must exist on the machine that will upload
3. Preview shows **new vs already in library** (fingerprint dedup)
4. Open job → **Upload all new** → **▶️ Start upload** (source channel comes from pipeline setup)
5. Keep `bot.py` running so channel posts are indexed and linked to the job

### Mac upload worker (files on Mac, bot on Termux)

When media is on your **Mac** but the bot runs on a phone/server:

1. Use **PostgreSQL** — same `DATABASE_URL` on Termux and Mac ([DEPLOYMENT.md](./DEPLOYMENT.md)).
2. On Termux: `./run_all.sh` (bot + portal).
3. In Telegram: create job with **file path(s)** pointing to Mac paths (e.g. `/Users/you/Movies/file.mkv`).
4. On Mac:
   ```bash
   cd Index_bot
   python telethon_login.py    # once
   ./run_upload_worker.sh
   ```
5. Tap **▶️ Start upload** in Telegram (or leave job planned — worker picks it up).

Only one upload worker should run at a time. Do **not** start upload on Termux for the same job if paths are Mac-only.

### Pipeline upload targets (one-time)

**Library setup → 📤 Pipeline upload targets**

Map each upload type to a default **source channel** (where Telethon uploads files). New jobs inherit this automatically — you do not need to pick a channel on every job.

| Concept | Meaning |
|---------|---------|
| **Source channel** | Telegram channel where file messages live (playback / indexing) |
| **Publish channel** (media only) | Watch library with TMDB catalog cards — set under Distribution channels |

Types: media, course, adult, archive, shortform, mixed (ingest sink).

**🔍 Check folder dupes** — dry-run duplicate report without creating a job.

- **Upload jobs** — review planned batches
- **Duplicates** — files that match something already indexed
- **Course vault** / **All vaults** — browse indexed content

CLI still works: `upload_planner.py`, `upload_bot_bridge.py`, `course_upload.py`.

## Content types & channels

**Index** can ingest from any monitored channel (including random dumps). Each file gets a **content type** (media, course, archive, …) during indexing.

**Pipeline upload targets** (Library setup) set the default **source** channel per upload type for bulk jobs.

**Distribution channels** (Library setup → Distribution channels) are where you **publish** organized content by type — catalog cards and delivery.

**Staging defaults** (Advanced, optional) only apply when a channel is dedicated to one upload type (e.g. course-only staging). Mixed dump channels do not need this.

| Type | Typical distribution channel |
|------|------------------------------|
| Media | Movies/series library |
| Course | Course catalog / lessons |
| Archive | PDFs, ebooks, files |
| Shortform | Reels/clips |

## Duplicate detection

On every new post the bot computes a **fingerprint** (`file_unique_id` or size + normalized name).

If a match exists:

- Row is stored as `duplicate_hold`
- Admin reviews under **Upload pipeline → Duplicates**
- **Skip** or **Index anyway**

## Bulk course upload (100+ videos)

### 1. Staging channel

Create a Telegram channel, add the bot as admin, set lane to **🎓 Course**.

### 2. Plan (Termux / server)

```bash
cd Index_bot
source venv/bin/activate

# From a folder (module subfolders supported)
python upload_planner.py ~/storage/shared/MyCourse \
  --name "Python Mastery" \
  --channel @MyCourseStaging \
  --course-title "Python Mastery"

# Or from CSV
python upload_planner.py manifest.csv --name "Python Mastery" --channel @MyCourseStaging

# Dry run only
python upload_planner.py ~/path/to/course --name "Test" --dry-run
```

### 3. Review job in bot

`/menu` → **Upload pipeline** → job → **Skip all dups** / **Upload all new**

### 4. Upload via Telethon

```bash
python telethon_login.py   # once
python course_upload.py --job 1 --delay 3
```

Keep **bot.py** running so each new channel post is indexed and linked to the job.

### CSV format

**Manifest only** (plan order + titles in the bot):

```csv
sequence,module,lesson_title,filename
1,01 Intro,Welcome,01 - Welcome.mp4
2,01 Intro,Setup,02 - Setup.mp4
```

**Upload from disk** (required for ▶️ Start upload / `course_upload.py`):

```csv
sequence,module,lesson_title,filename,local_path
1,01 Intro,Welcome,01 - Welcome.mp4,/full/path/to/01 - Welcome.mp4
2,01 Intro,Setup,02 - Setup.mp4,/full/path/to/02 - Setup.mp4
```

Column aliases: `seq`/`order`, `title`/`lesson`, `file`, `path`/`local_path`/`filepath`, optional `file_size`/`size`.
Header row required. UTF-8.

## CLI reference

| Command | Purpose |
|---------|---------|
| `upload_planner.py` | Scan folder/CSV → create job + duplicate report |
| `course_upload.py` | Upload approved job items to target channel |
| `telethon_login.py` | User session for Telethon tools |
| `run_upload_worker.py` | Mac/PC: poll DB and run pipeline uploads only |
| `run_upload_worker.sh` | Wrapper with auto dependency install |

## Backfill existing fingerprints

```bash
python -c "from database import Database; print(Database().backfill_fingerprints())"
```

---

## Phase 2 features

### Historical ingest + duplicate report

In the bot: **Historical ingest** → pick source → **Dry run** shows:

- Indexable media count
- **Already in library** (fingerprint match)
- **Would forward (new)**

Then choose **Forward all** or **Skip dupes** (only new files).

CLI:

```bash
python forward_ingest.py @Source @Ingest --dry-run
python forward_ingest.py @Source @Ingest --skip-duplicates
```

Photos and videos without filenames are included in backfill scans.

### Promote to public library

**Course vault** → open a course →

- **Publish to library** — visible in Browse (stays course type)
- **Promote as media** — same + media lane + watch catalog eligible

Requires `library_visible` + `distribution_approved` for watch-channel auto-publish on non-media lanes.

### Per-lane watch channels (admin menu)

**Watch hub → Watch channels** — assign a catalog/delivery channel per lane (media, course, archive, shortform). No `.env` required.

Optional `.env` IDs still work as fallback if a lane is not set in the bot.

Catalog publish picks the channel from the title’s primary content lane.

### Stronger local duplicate detection

```bash
python upload_planner.py ~/Course --name "X" --channel @Y --sha256
```

Or set `UPLOAD_PLANNER_USE_SHA256=true` in `.env`.

---

## Phase 3 features

### Content vaults (admin)

`/menu` → **Upload pipeline** → **All vaults**

Browse by lane: **Course**, **Archive**, **Shortform**, **Adult**.

- Adult never appears in public browse or search.
- **Publish visible in lane** marks vault files `library_visible` + `distribution_approved` (except adult).
- Per-lane search from the vault screen.

### Public library filter

User-facing browse/search only shows:

- `library_visible` **and**
- lane ≠ adult **and**
- (lane = media **or** `distribution_approved`)

Admin vault and duplicate review still see everything.

### Duplicate review actions

**Duplicates** → open a hold →

- **Open** existing match → deliver that file
- **Use existing title** → skip the duplicate hold
- **Publish existing** → promote the matched upload
- **Skip** / **Index anyway**

### Promote + watch catalog

**Promote as media** (course vault) now also attempts **watch catalog publish** for that title (no extra Watch hub step).

### File deep links

Share a direct open link:

`https://t.me/YourIndexBot?start=file_{upload_id}`

Works in DM for public library files; admins can open vault-only files too.

### Download helper bot (optional)

```env
DOWN_OAD_BOT_USERNAME=YourDownloadBot
```

Adds a **Download helper** button after file delivery (deep link `file_{upload_id}` to that bot when you wire it there).

---

## Phase 4 features

### Upload jobs in the bot

**Upload pipeline → job** →

- **Set target channel** — searchable channel picker
- **Start upload** — runs Telethon in the background (same session as `forward_ingest.py`)
- Live progress: uploaded / indexed counts; **Refresh** on the job screen

Still works from CLI:

```bash
python upload_planner.py ~/Course --name "X" --channel @Staging
python course_upload.py --job 1 --delay 3
```

### upload_bot bridge

Scan a local folder with the same dedup DB as Index_bot:

```bash
python upload_bot_bridge.py /path/to/files --name "My batch" --channel @Staging
python upload_bot_bridge.py /path/to/files --check-only
```

Then finish in **Upload pipeline → job** (set target → Start upload).

### Duplicate merge

**Duplicates** → open hold → **Merge** links the hold to the existing file (hold skipped, not indexed twice).

### Public archive / documents

When archive-lane files are published (`library_visible` + `distribution_approved`), users see **Documents** on the main menu — browse PDFs, ebooks, and images and open them in DM.
