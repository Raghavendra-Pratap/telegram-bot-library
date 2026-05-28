# Copy local-only files: Mac → Termux

`git pull` does **not** bring these (they are in `.gitignore`). Copy them once after pulling code.

## What to copy

| File | Required? | Notes |
|------|-----------|--------|
| `.env` | **Yes** | Secrets + config. Edit `PORTAL_PUBLIC_URL` for phone IP on Termux. |
| `index_bot.db` | **Yes** (if keeping data) | Main library DB. See SQLite note below. |
| `forward_ingest.session` | **Yes** (for Telethon) | Bot uploads, ingest, member watch. **Private.** |
| `forward_ingest_portal.session` | If using portal Play | Run `python telethon_login_portal.py` on Termux instead of copying. |
| `upload_journal.db` | Optional | Only if you use upload journal features. |
| `index_bot.db-wal`, `index_bot.db-shm` | With DB | Copy **all three** together, or checkpoint first (below). |

**Do not copy** (create fresh on Termux): `.bot.pid`, `.portal.pid`, `*.log`, `venv/`, `portal_transcode_cache/`.

## Before copying the database (Mac)

Stop the bot on Mac so SQLite is not writing:

```bash
cd /path/to/Index_bot
./stop_all.sh   # or ./stop_bot.sh
```

**Option A — copy DB + WAL files (easiest):**

```text
index_bot.db
index_bot.db-shm
index_bot.db-wal
```

**Option B — single file only (after checkpoint on Mac):**

```bash
cd /path/to/Index_bot
sqlite3 index_bot.db "PRAGMA wal_checkpoint(FULL);"
# then copy only index_bot.db
```

## Paths

| Machine | Typical path |
|---------|----------------|
| Mac | `~/Developer/Telegram_Bot_Library/Index_bot` |
| Termux | `~/projects/Telegram_Bot_Library/Index_bot` |

Adjust if your folders differ.

---

## Method 1: `scp` (same Wi‑Fi, Termux SSH)

**On Termux (once):**

```bash
pkg install openssh
sshd
whoami          # e.g. u0_a123
ifconfig wlan0  # phone IP, e.g. 192.168.1.10
```

**On Mac:**

```bash
MAC=~/Developer/Telegram_Bot_Library/Index_bot
PHONE=u0_a123@192.168.1.10
REMOTE=~/projects/Telegram_Bot_Library/Index_bot

scp "$MAC/.env" "$PHONE:$REMOTE/"
scp "$MAC/index_bot.db" "$MAC/index_bot.db-shm" "$MAC/index_bot.db-wal" "$PHONE:$REMOTE/" 2>/dev/null || scp "$MAC/index_bot.db" "$PHONE:$REMOTE/"
scp "$MAC/forward_ingest.session" "$PHONE:$REMOTE/"
scp "$MAC/forward_ingest.session-journal" "$PHONE:$REMOTE/" 2>/dev/null || true
```

Replace `u0_a123`, IP, and paths.

---

## Method 2: USB / Google Drive (no SSH)

**On Mac:** zip the files:

```bash
cd ~/Developer/Telegram_Bot_Library/Index_bot
zip -r ~/Desktop/index_bot_sync.zip \
  .env index_bot.db index_bot.db-shm index_bot.db-wal \
  forward_ingest.session forward_ingest.session-journal \
  upload_journal.db 2>/dev/null
```

Copy `index_bot_sync.zip` to the phone (AirDrop, Drive, cable → Downloads).

**On Termux:**

```bash
termux-setup-storage   # once
cd ~/projects/Telegram_Bot_Library/Index_bot
unzip -o ~/storage/shared/Download/index_bot_sync.zip
chmod 600 .env *.session 2>/dev/null
```

---

## After copy on Termux

1. **Edit `.env` for the phone:**

   ```env
   PORTAL_HOST=0.0.0.0
   PORTAL_PUBLIC_URL=http://YOUR_PHONE_LAN_IP:8765
   ```

   Use `ifconfig wlan0` on Termux for the IP.

2. **Append** new keys if missing (from `TERMUX_MIGRATION_ENV_APPEND.txt`):

   ```bash
   cat TERMUX_MIGRATION_ENV_APPEND.txt >> .env
   nano .env
   ```

3. **Install & run:**

   ```bash
   ./run_all.sh
   ```

4. **Portal session** (if Play fails): `python telethon_login_portal.py`

5. **Mac upload worker** (optional): run `./run_upload_worker.sh` on Mac only, not on Termux, with the same `DATABASE_URL` if using Postgres.

---

## Security

- Never commit `.env` or `*.session` to git.
- Treat the zip like a password vault; delete after unzip on the phone.
