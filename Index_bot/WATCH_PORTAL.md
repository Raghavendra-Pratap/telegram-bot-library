# Watch portal (web / TV / phone)

JustWatch-style browse UI over your **Index_bot library**, with playback from **Telegram** (source of truth).

## Run

1. Keep **bot.py** running (indexes channels, delivers files).
2. Start the portal:

```bash
cd Index_bot
./run_portal.sh
# or: python run_portal.py
```

3. In Telegram, send **`/portal`** to the bot → open the link (phone, desktop, or Android TV browser).

Admins (`ADMIN_USER_IDS` in `.env`) see an extra **Admin** tab for pending review (with **TMDB posters + pick**, like the bot), user requests, and catalog publish.

## Configure

```env
PORTAL_HOST=0.0.0.0
PORTAL_PORT=8765
PORTAL_PUBLIC_URL=http://YOUR_LAN_IP:8765
```

`PORTAL_PUBLIC_URL` must match what users open (used in `/portal` links).

## Features

| Feature | Description |
|---------|-------------|
| **Browse** | Posters, ratings, year — movies, series, courses |
| **Search** | Library + TMDB titles not yet uploaded |
| **Request** | Ask admin to add missing titles |
| **Favorites** | Synced with bot DB |
| **Play** | In-browser video player (Telethon stream, any size) |
| **Telegram** | Optional — send file to your Telegram DM |

## Architecture

- `portal/api.py` — FastAPI + static UI
- `portal/service.py` — catalog + play logic
- Same SQLite/Postgres DB as the bot
- Files stay in Telegram channels; portal does not re-host (except small stream redirect)

## TV / Android

Open the `/portal` link in **Chrome on Android TV** or any browser. **Play** streams in the page; use a **dedicated portal session** so it does not lock the bot upload session:

```bash
python telethon_login_portal.py
```

## API documentation

- Human-readable: [API_DOCS.md](./API_DOCS.md)
- Interactive: `{PORTAL_PUBLIC_URL}/docs` (Swagger UI)
- OpenAPI: `{PORTAL_PUBLIC_URL}/openapi.json`

## Later (roadmap)

- HLS cache for large files in-browser (Phase 2.3)
- Telegram Login Widget (no `/portal` link)
