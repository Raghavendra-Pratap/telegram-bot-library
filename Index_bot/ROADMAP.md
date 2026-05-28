# Index Bot — Roadmap

This document covers three horizons:

1. **Current stage** — Telegram bot as the operational core (index, admin, delivery).
2. **Admin ops web** — smoother pending / duplicate / setup workflows.
3. **Watch portal** — better discovery and playback UX (still Telegram-backed at first).

The bot remains the **source of truth** for ingest, Telethon jobs, and channel publishing unless a later phase explicitly adds external storage.

---

## Horizon 0 — Current stage (Telegram core)

**Goal:** Reliable index-from-anywhere → classify → publish to **distribution channels**; admins configure in-bot; users browse/watch via Telegram.

### Mental model

| Concept | Meaning |
|--------|---------|
| **Index** | Monitor channels / backfill; fingerprint + TMDB per file |
| **Ingest channel** | Historical sink (e.g. `index-backfill`); forwards only — not a distribution target |
| **Source channel** | Original archive (`source_channel_id`); never the ingest sink |
| **Distribution channel** | Where the bot **publishes** cards/files by lane (media, course, archive, …) |
| **Delivery** | `copy_message` from distribution (or post channel) → user DM |

### Done (recent)

- [x] **Library setup** — distribution channels per lane, ingest channel, discover channels
- [x] **`bot_can_post`** — distribution/upload pickers only list channels where Index bot is admin
- [x] **Heavy jobs in background** — discover / ingest / verify / bulk upload do not block menus
- [x] **Admin-only busy UI** — users never see “background task” banners; admins get menu + banner
- [x] **Exclusive job guard** — “Please wait” only when starting a *second* Telethon-scale job
- [x] **SQLAlchemy ingest fix** — `add_file_upload` detaches rows (no “not bound to Session” after TMDB)
- [x] **`flood_reply_photo`** — correct `photo=` kwarg for admin request cards

### In progress / next (stay on Telegram)

| Item | Priority | Notes |
|------|----------|--------|
| **Duplicate review labels** | High | Show *source archive* (e.g. Storage Shortage) when `source_channel_id` is set; avoid looking like ingest is the “library” |
| **Ingest-aware duplicate rules** | Medium | Prefer matches outside ingest; optional auto-skip when only duplicate is another ingest forward |
| **Backfill dedup clarity** | Medium | Align forward-ingest skip-duplicates with fingerprint rules above |
| **Phase 4 upload pipeline** | Ongoing | Jobs, duplicate merge, archive browse, `upload_bot_bridge` — see `UPLOAD_PIPELINE.md` |
| **`down_oad_bot` bridge** | Deferred | `DOWN_OAD_BOT_USERNAME` — download helper; separate bot in development |
| **Postgres for prod** | Recommended | Bot + future web app sharing `DATABASE_URL`; SQLite OK for single-device Termux |

### Out of scope for current stage

- Hosting video on your own CDN
- Replacing Telegram delivery for end users
- Full web admin / watch UI (Horizons 1–2)

**Docs:** `UPLOAD_PIPELINE.md`, `TERMUX_SETUP.md`, `.env.example`

---

## Horizon 1 — Admin ops web (pending & review)

**Goal:** Faster operations than inline Telegram keyboards — same database, bot still runs ingest and Telethon.

### Why

Telegram is fine for alerts and one-tap actions. It is weak for:

- Hundreds of pending TMDB rows
- Duplicate review with poster + filename + source side-by-side
- Bulk confirm / lane fixes / distribution map at a glance

### Architecture

```text
Telegram channels ──► Index_bot (ingest, publish, jobs)
                           │
                           ▼
                      Postgres / SQLite
                           ▲
                           │
                     Admin web app (read/write)
```

- **Single DB** — no duplicate catalog logic in the frontend.
- **Optional FastAPI** — thin API over shared Python modules (`database`, `upload_pipeline`, `title_indexer`).
- **Auth** — admin allowlist (same `ADMIN_USER_IDS`) or session login; HTTPS required if hosted.

### Phased delivery

#### Phase 1.1 — Read-only dashboard (MVP)

- [ ] Pending queue table (filters: lane, needs TMDB, deferred)
- [ ] Duplicate holds list → detail view
- [ ] Ingest / backfill job status (from bot logs or job table if added)
- [ ] Distribution map: lane → channel (`bot_can_post` only)
- [ ] Deep links from bot: `https://admin…/pending/{id}` on cards

#### Phase 1.2 — Write actions

- [ ] TMDB search + pick (reuse `apply_tmdb_pick` logic)
- [ ] Bulk confirm / defer pending
- [ ] Duplicate: merge, skip, index anyway
- [ ] Promote to library / approve distribution
- [ ] Set distribution channel per lane (mirror Library setup)

#### Phase 1.3 — Polish

- [ ] Audit log (who confirmed what)
- [ ] Notifications: webhook or poll → bot sends “3 duplicates need review” with link
- [ ] Mobile-friendly layout for quick review on phone

### Success criteria

- Admin can clear a 50+ pending backlog faster than in Telegram alone.
- No second source of truth for fingerprints, lanes, or TMDB rules.

---

## Horizon 2 — Watch portal (catalog & playback)

**Goal:** Better browse/discovery UX; **playback still from Telegram** in early phases.

### What exists today

- Catalog in DB (`content_title`, `file_uploads`, lanes, `library_visible`)
- User flow: browse → episode/quality → **`copy_message`** to DM
- Deep links: `/start file_{upload_id}`, `watch_…` payloads
- Optional: `DOWN_OAD_BOT_USERNAME` download helper
- Distribution channels = canonical published copies (not ingest sink)

### Architecture options

| Approach | Playback | Effort | Fits current stack |
|----------|----------|--------|-------------------|
| **A. Web catalog + Telegram delivery** | Bot copies file to user DM or `t.me` link | Medium | ✅ Best first step |
| **B. Telegram Mini App** | Same as A, UI inside Telegram | Medium | ✅ Good for TG-native users |
| **C. Stream server (HLS/CDN)** | Browser `<video>`; files pulled from TG to disk/S3 | High | ⚠️ New storage, cost, compliance |

**Recommendation:** A → B → consider C only if in-browser streaming is a hard requirement.

### Phased delivery

#### Phase 2.1 — Watch portal (orchestration only)

- [ ] REST/API: titles, seasons, episodes, qualities (public + adult policy flags)
- [ ] Web UI: search, posters (TMDB), watchlist/favorites (sync with DB)
- [ ] **Play** = `POST /play/{upload_id}` → bot `copy_message` to user’s `telegram_user_id`, or open `t.me/{bot}?start=file_{id}`
- [ ] Auth: Telegram Login Widget or “link account” via bot one-time code
- [ ] Continue watching / history (optional tables)

#### Phase 2.2 — Telegram Mini App

- [ ] Same API; embed catalog in Mini App WebView
- [ ] Native-feel navigation; still no self-hosted video

#### Phase 2.3 — Optional streaming cache (only if needed)

- [ ] Background export: distribution channel → object storage (S3/R2)
- [ ] Transcode to HLS (ffmpeg job queue)
- [ ] Signed URLs for web player
- [ ] Fallback to Telegram delivery when cache miss

### Non-goals (until explicitly chosen)

- Using **ingest/backfill channel** as the user-facing library
- Public torrent-style indexing without `library_visible` / lane policy
- Replacing distribution channels without a migration plan

### Risks

| Risk | Mitigation |
|------|------------|
| Telegram rate limits on `copy_message` | Queue + throttle (existing `telegram_flood`); cache in Phase 2.3 |
| Message deleted in channel | `verify_upload_list_for_watch`; unavailable UI |
| Rights / ToS | Private library; distribution channels you control |
| Adult content on web | Separate policy, age gate, no public SEO for adult lane |

---

## How the horizons fit together

```text
                    ┌─────────────────────┐
                    │   Horizon 0 (now)  │
                    │  Index_bot + TG     │
                    └──────────┬──────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
   ┌─────────────────────┐         ┌─────────────────────┐
   │ Horizon 1            │         │ Horizon 2            │
   │ Admin ops web        │         │ Watch portal         │
   │ pending · duplicates │         │ browse · play (TG)   │
   └─────────────────────┘         └─────────────────────┘
              │                                 │
              └────────────────┬────────────────┘
                               ▼
                    Shared DB + shared Python core
                    (lanes, fingerprints, TMDB)
```

**Order of execution (suggested):**

1. Finish Horizon 0 duplicate UX + any remaining pipeline items.
2. Horizon 1 Phase 1.1 if admin review pain is daily.
3. Horizon 2 Phase 2.1 if user discovery pain exceeds Telegram menus.
4. Horizon 2.3 only with clear storage budget and legal stance.

---

## Decision log (for later)

| Date | Decision |
|------|----------|
| 2026-05 | Distribution ≠ source lane on dump channels; setup in Library setup |
| 2026-05 | Heavy jobs non-blocking; exclusive lock only for overlapping Telethon jobs |
| 2026-05 | Users do not see admin background-task messaging |
| TBD | Postgres hosting for bot + web |
| TBD | Web admin vs Mini App first |
| TBD | Self-hosted streaming (Phase 2.3) yes/no |

---

*Update this file when a phase ships or priorities change.*
