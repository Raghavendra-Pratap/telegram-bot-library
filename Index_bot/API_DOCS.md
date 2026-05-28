# Watch Portal — HTTP API

REST API served by `run_portal.py` (FastAPI). The web UI in `portal/static/` uses these endpoints.

## Base URL

| Environment | Example |
|-------------|---------|
| Local | `http://127.0.0.1:8765` |
| LAN / Termux | Value of `PORTAL_PUBLIC_URL` in `.env` (e.g. `http://192.168.1.4:8765`) |

Interactive docs (auto-generated from code):

- **Swagger UI:** `{base}/docs`
- **OpenAPI JSON:** `{base}/openapi.json`

## Authentication

1. In Telegram, send **`/portal`** to Index_bot.
2. Open the link (contains `?token=...`) or copy the token.
3. For API calls, send:

```http
Authorization: Bearer <portal_token>
```

| Endpoint | Auth |
|----------|------|
| `GET /api/health` | None |
| `POST /api/auth/login` | Body: `{ "token": "..." }` |
| `GET /api/stream/{upload_id}` | Bearer **or** `?token=` query (browser `<video>`) |
| All other `/api/*` | Bearer required |
| `/api/admin/*` | Bearer + user must be in `ADMIN_USER_IDS` |

Tokens expire (default **72 hours**). Request a new `/portal` link when you get `401`.

## Common response codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 401 | Missing/invalid token |
| 403 | Not admin (admin routes) |
| 404 | Resource not found or not visible to user |
| 500 | Server error |
| 503 | Telethon/streaming not configured |

---

## Public API

### Health

`GET /api/health`

No auth. Returns service status:

```json
{
  "ok": true,
  "portal_url": "http://192.168.1.4:8765",
  "browser_stream": true,
  "ffmpeg_transcode": false,
  "tmdb_enabled": true,
  "tmdb_reachable": true,
  "tmdb_error": null
}
```

### Auth

`POST /api/auth/login`

Body: `{ "token": "<from /portal link>" }`

Response: `{ "user_id": 123, "token": "...", "role": "user" | "admin" }`

`GET /api/me` — current user: `{ "user_id", "role" }`

### Browse & search

`GET /api/browse`

| Query | Default | Description |
|-------|---------|-------------|
| `limit` | 28 | Page size (12–84) |
| `offset` | 0 | Offset |
| `page` | 1 | Alternative to offset |
| `type` | `all` | Media filter |
| `scope` | `media` | `media`, `course`, `archive`, `shortform`; admin scopes: `adult`, `non_catalog`, etc. |
| `sort` | `recent` | Sort field |
| `order` | `desc` | `asc` / `desc` |
| `min_year`, `max_year`, `min_rating` | — | Filters |
| `q` | — | Search within browse |

Response: `{ "items", "total", "offset", "limit", "page", "page_count", "has_more" }`

`GET /api/search?q=<text>` — library + TMDB suggestions.

### Title detail

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/title/{content_title_id}` | Title card + metadata (`scope` query) |
| GET | `/api/title/{content_title_id}/episodes` | Episode list (series) |
| GET | `/api/title/{content_title_id}/qualities` | Available files (`season`, `episode` optional) |

### Favorites & watchlist

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/favorites` | `{ "items": [...] }` |
| POST | `/api/favorites/{content_title_id}` | `{ "favorited": true/false }` |
| GET | `/api/watchlist` | `{ "items": [...] }` |
| POST | `/api/watchlist/{content_title_id}` | `{ "on_watchlist": true/false }` |

### User requests (ask admin to add title)

`GET /api/requests` — user's pending/done requests.

`POST /api/requests`

```json
{
  "tmdb_id": 12345,
  "media_type": "movie",
  "title": "Example",
  "release_year": 2024
}
```

### Playback

`POST /api/play/{upload_id}` — send file to user's Telegram DM (Bot API).

`GET /api/stream/{upload_id}` — browser stream (HTTP Range, Telethon). Auth via header or `?token=`.

`GET /api/stream/{upload_id}/progress` — stream buffer progress for UI.

---

## Admin API

All routes under `/api/admin/*` require **admin** role (`ADMIN_USER_IDS`).

### Dashboard & monitoring

| Method | Path |
|--------|------|
| GET | `/api/admin/dashboard` |
| GET | `/api/admin/channels/monitoring` |
| GET | `/api/admin/tracking` |
| GET | `/api/admin/metadata-gaps` |

### Pending queue (TMDB / confirm)

| Method | Path |
|--------|------|
| GET | `/api/admin/pending` |
| GET | `/api/admin/pending/{upload_id}/tmdb` |
| POST | `/api/admin/pending/{upload_id}/tmdb-pick` |
| POST | `/api/admin/pending/{upload_id}/tmdb-retry` |
| POST | `/api/admin/pending/retry-all-tmdb` |
| POST | `/api/admin/pending/{upload_id}/approve` |
| POST | `/api/admin/pending/{upload_id}/confirm` |
| POST | `/api/admin/pending/{upload_id}/defer` |
| POST | `/api/admin/pending/{upload_id}/skip` |
| POST | `/api/admin/pending/{upload_id}/skip-catalog` |
| POST | `/api/admin/pending/{upload_id}/lane` |

Batch variants: `/api/admin/pending/batches/{match_key}/...` (tmdb, tmdb-pick, lane, defer, skip-catalog).

**TMDB pick body** (`TmdbPickBody`):

```json
{
  "suggestion_index": 0,
  "search_query": null,
  "tmdb_id": null,
  "apply_siblings": false,
  "page": 1,
  "title": null,
  "media_type": null,
  "year": null
}
```

### Uploads & titles (remap / lane)

| Method | Path |
|--------|------|
| GET | `/api/admin/titles/{content_title_id}/uploads` |
| POST | `/api/admin/titles/{content_title_id}/lane` |
| GET | `/api/admin/uploads/{upload_id}/tmdb` |
| POST | `/api/admin/uploads/{upload_id}/tmdb-pick` |
| POST | `/api/admin/uploads/{upload_id}/tmdb-retry` |
| POST | `/api/admin/uploads/{upload_id}/lane` |
| POST | `/api/admin/uploads/{upload_id}/queue-tmdb-pending` |
| POST | `/api/admin/uploads/{upload_id}/convert-mp4` |
| GET | `/api/admin/uploads/{upload_id}/convert-mp4` |

Lane body: `{ "lane": "media" }` (or `content_lane`).

### User title requests

| Method | Path |
|--------|------|
| GET | `/api/admin/requests` |
| POST | `/api/admin/requests/{request_id}` |

Body: `{ "status": "done" | "rejected" | ... }`

### Watch catalog publish

| Method | Path |
|--------|------|
| GET | `/api/admin/catalog` |
| GET | `/api/admin/catalog/unpublished` |
| GET | `/api/admin/catalog/published` |
| POST | `/api/admin/catalog/publish` |
| POST | `/api/admin/catalog/publish-all` |
| GET | `/api/admin/catalog/publish-all/status` |
| POST | `/api/admin/catalog/unpublish` |

Unpublish body: `{ "content_title_id": 1, "season_number": null }`

### Filename strip rules

| Method | Path |
|--------|------|
| GET | `/api/admin/filename-rules` |
| POST | `/api/admin/filename-rules` |
| DELETE | `/api/admin/filename-rules/{rule_id}` |
| POST | `/api/admin/filename-rules/preview` |

Add rule body: `{ "pattern": "...", "note": "...", "is_regex": false }`

### Pipeline & upload jobs

| Method | Path |
|--------|------|
| GET | `/api/admin/pipeline/status` |
| GET | `/api/admin/pipeline/defaults` |
| PUT | `/api/admin/pipeline/defaults/{upload_type}` |
| GET | `/api/admin/upload-jobs` |
| GET | `/api/admin/duplicate-holds` |

`PUT .../defaults/{upload_type}` body: `{ "source_channel_id": "-100..." }`  
`upload_type`: `media`, `course`, `adult`, `archive`, `shortform`, `mixed`.

---

## Static UI

| Path | Description |
|------|-------------|
| `GET /` | SPA (`portal/static/index.html`) |
| `/static/*` | CSS, JS, assets |

---

## Example: curl

```bash
BASE=http://192.168.1.4:8765
TOKEN="paste-from-portal-link"

curl -s "$BASE/api/health" | jq .

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/browse?limit=12" | jq .

curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title":"Inception","media_type":"movie","tmdb_id":27205}' \
  "$BASE/api/requests" | jq .
```

---

## Related docs

- [WATCH_PORTAL.md](./WATCH_PORTAL.md) — setup and features
- [HOW_TO_RUN.md](./HOW_TO_RUN.md) — `run_portal.sh`, `run_all.sh`
- [UPLOAD_PIPELINE.md](./UPLOAD_PIPELINE.md) — bulk upload (bot + Mac worker)
