# Coursify — Telegram Video Storage Architecture
### Developer Implementation Guide

**Project:** Coursify LMS  
**Author:** For internal developer use  
**Stack:** Android (Samsung A51) · Telegram Bot API · Pyrogram · Python · Vercel (Next.js/React)  
**Goal:** Stream 1TB+ of course videos from Telegram via a self-hosted bot running on a local Android server, embedded into the Coursify web player.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [How It Works — End to End](#2-how-it-works--end-to-end)
3. [Samsung A51 Server Setup](#3-samsung-a51-server-setup)
4. [Telegram Setup](#4-telegram-setup)
5. [FileStreamBot — Installation & Configuration](#5-filestreambot--installation--configuration)
6. [Database Schema](#6-database-schema)
7. [Video Upload Workflow](#7-video-upload-workflow)
8. [Coursify Integration](#8-coursify-integration)
9. [Networking — Exposing the A51 to the Internet](#9-networking--exposing-the-a51-to-the-internet)
10. [Environment Variables Reference](#10-environment-variables-reference)
11. [API Reference](#11-api-reference)
12. [Error Handling & Edge Cases](#12-error-handling--edge-cases)
13. [Performance Considerations](#13-performance-considerations)
14. [Security Checklist](#14-security-checklist)
15. [Maintenance & Monitoring](#15-maintenance--monitoring)
16. [Known Limitations](#16-known-limitations)
17. [Phased Implementation Plan](#17-phased-implementation-plan)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        OWNER / ADMIN                            │
│                                                                 │
│   Local PC / Laptop                                             │
│   └── Telegram Desktop App (Premium account, 4GB/file)         │
│       └── Manually uploads .mp4 videos to Private Channel      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ upload (Telegram servers)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                    TELEGRAM INFRASTRUCTURE                      │
│                                                                 │
│   Private Storage Channel                                       │
│   └── Stores video files (file_id + message_id assigned)        │
│   └── Free, unlimited storage, up to 4GB per file              │
└──────────────────────────────┬──────────────────────────────────┘
                               │ MTProto API (Pyrogram)
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SAMSUNG A51 LOCAL SERVER                      │
│                                                                 │
│   Termux (Linux environment on Android)                         │
│   ├── Python 3.11                                               │
│   ├── FileStreamBot (Pyrogram-based)                            │
│   │   └── Listens on port 8080                                  │
│   ├── Cloudflared tunnel (exposes port 8080 to internet)        │
│   └── Keeps device awake (Wake Lock / Termux:Boot)             │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS stream URL
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      COURSIFY BACKEND                           │
│                                                                 │
│   Database (Supabase / PlanetScale / SQLite)                    │
│   └── courses, lessons, telegram_videos tables                  │
│                                                                 │
│   Coursify API (Next.js API routes on Vercel)                   │
│   └── Returns lesson data including stream_url                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ stream URL in JSON
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      COURSIFY FRONTEND                          │
│                                                                 │
│   Next.js / React (Vercel)                                      │
│   └── Video player (Plyr.js or Video.js)                        │
│       └── src="https://your-tunnel.trycloudflare.com/stream/…" │
│           └── Learner streams video directly                    │
└─────────────────────────────────────────────────────────────────┘
```

**Cost estimate:**
| Component | Cost |
|-----------|------|
| Samsung A51 server | $0 (spare device) |
| Telegram Premium | Already owned |
| Telegram storage | $0 (free, unlimited) |
| Cloudflared tunnel | $0 (free tier) |
| Vercel (Coursify frontend) | $0 (free tier) |
| Supabase (database) | $0 (free tier, 500MB) |
| **Total** | **~$0/month** |

---

## 2. How It Works — End to End

### Upload flow (admin only)

1. Admin opens Telegram Desktop on their laptop.
2. Admin uploads a `.mp4` video (up to 4GB) to a **private Telegram channel** they own.
3. Telegram assigns the file a `file_id` and `message_id`.
4. Admin runs a small helper script (see §7) that reads the `message_id` from Telegram and writes a record to the Coursify database: `{ lesson_id, message_id, file_id, title, duration }`.

### Playback flow (learner)

1. Learner opens a lesson in Coursify.
2. Coursify frontend calls `GET /api/lessons/:id` → backend returns lesson data including `stream_url`.
3. The `stream_url` looks like: `https://your-tunnel.trycloudflare.com/watch/MESSAGE_ID/VIDEO_FILE_NAME.mp4`
4. The video player sets `src` to this URL.
5. The request hits the **Samsung A51** running FileStreamBot.
6. FileStreamBot authenticates with Telegram using the owner's **Pyrogram session** (user account, not bot — this is how 4GB works), fetches the file from Telegram servers in chunks, and streams it back to the learner's browser as an HTTP video response with proper `Range` header support.
7. Learner watches the video. Telegram serves the bytes; the A51 is just a proxy.

### Why user account (Pyrogram), not a bot token?

Telegram Bot API caps file downloads at 20MB (or 2GB with a local Bot API server). To serve **4GB files** without running a local Telegram server, FileStreamBot uses a **Pyrogram user session** (the owner's Telegram account credentials) via MTProto. This is legitimate and within Telegram's ToS for personal use.

---

## 3. Samsung A51 Server Setup

### Prerequisites

The Samsung A51 should be set up as a permanently-running server. Required:

- Android 11+ (A51 ships with this)
- **Termux** installed (from F-Droid — NOT from Play Store, the Play Store version is outdated)
- USB cable or charger keeping the device powered
- Phone connected to home WiFi
- Battery optimisation **disabled** for Termux

### Step 1: Install Termux

1. Download Termux from [https://f-droid.org/en/packages/com.termux/](https://f-droid.org/en/packages/com.termux/)
2. Install and open Termux.
3. Run initial setup:

```bash
pkg update && pkg upgrade -y
pkg install python git wget curl nano openssh -y
```

### Step 2: Keep the phone awake

Android aggressively kills background processes. Fix this:

**Disable battery optimisation:**
- Settings → Battery → Battery Optimisation → Termux → Don't optimise

**Acquire wake lock from inside Termux:**
```bash
# Install Termux:API (from F-Droid)
pkg install termux-api -y

# Acquire wake lock (keeps CPU running even with screen off)
termux-wake-lock
```

**Auto-start on reboot using Termux:Boot:**
1. Install Termux:Boot from F-Droid.
2. Create the boot script:
```bash
mkdir -p ~/.termux/boot
nano ~/.termux/boot/start-coursify.sh
```
Content of `start-coursify.sh`:
```bash
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
cd ~/coursify-stream
source venv/bin/activate
python bot.py >> ~/logs/bot.log 2>&1 &
cloudflared tunnel run coursify >> ~/logs/tunnel.log 2>&1 &
```
```bash
chmod +x ~/.termux/boot/start-coursify.sh
```

### Step 3: Install Python dependencies

```bash
# Create project directory
mkdir ~/coursify-stream && cd ~/coursify-stream

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install pyrogram tgcrypto aiohttp aiofiles python-dotenv
```

> **Note:** `tgcrypto` is a C extension that dramatically speeds up Pyrogram's encryption. On ARM (A51), it compiles fine via pip.

### Step 4: Check storage

The A51 has limited internal storage. FileStreamBot does **not** download files to disk — it streams them in chunks directly from Telegram to the HTTP response. Storage on the A51 is not a concern.

---

## 4. Telegram Setup

### Step 1: Create a private storage channel

1. Open Telegram → New Channel.
2. Name it something like `Coursify Video Storage` (private, invite-only).
3. Note the channel username or ID — you'll need this.

**Getting the channel ID:**
Forward any message from the channel to `@userinfobot` or use:
```python
# Run once to get channel ID
from pyrogram import Client
app = Client("session", api_id=API_ID, api_hash=API_HASH)
with app:
    for dialog in app.get_dialogs():
        if "Coursify" in dialog.chat.title:
            print(dialog.chat.id)  # Will be a negative number like -1001234567890
```

### Step 2: Get Telegram API credentials

1. Go to [https://my.telegram.org](https://my.telegram.org)
2. Log in with the owner's phone number.
3. Go to **API development tools**.
4. Create a new application:
   - App title: `Coursify Stream`
   - Short name: `coursifystream`
   - Platform: Other
5. Note down `api_id` and `api_hash`.

> **Important:** These are the **user account** credentials, not a bot token. This is what allows 4GB file access.

### Step 3: Create a Telegram bot (for metadata only)

A bot is needed only for the **upload helper script** (to receive `message_id` after upload). It's not used for streaming.

1. Open `@BotFather` in Telegram.
2. `/newbot` → follow instructions.
3. Note the bot token.
4. Add the bot as an **admin** to the storage channel.

### Step 4: Generate a Pyrogram session string

Run this **once** on any machine with Python + Pyrogram:

```python
from pyrogram import Client

api_id = YOUR_API_ID      # integer
api_hash = "YOUR_API_HASH"  # string

with Client("coursify_session", api_id=api_id, api_hash=api_hash) as app:
    print(app.export_session_string())
```

This will prompt for your phone number and OTP. It generates a **session string** — a long encoded string. Save this securely. This goes in the `.env` file on the A51. You don't need to repeat this step.

---

## 5. FileStreamBot — Installation & Configuration

The recommended codebase is **Thunder** (actively maintained fork of FileStreamBot):

```
https://github.com/databaseandbot-png/FileToLink
```

Or use the original:
```
https://github.com/avipatilpro/FileStreamBot
```

### Installation

```bash
cd ~/coursify-stream
git clone https://github.com/databaseandbot-png/FileToLink .
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration — `.env` file

Create `~/coursify-stream/.env`:

```env
# Telegram API credentials (from my.telegram.org)
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890

# Pyrogram session string (generated in §4 Step 4)
SESSION_STRING=BQA...very_long_string...

# Bot token (from BotFather — used only for upload helper)
BOT_TOKEN=1234567890:ABCDEFabcdefABCDEF

# The private channel where videos are stored
BIN_CHANNEL=-1001234567890

# Server config
PORT=8080
HOST=0.0.0.0

# Your Cloudflare tunnel public URL (set after §9)
PUBLIC_URL=https://your-tunnel.trycloudflare.com

# Optional: restrict who can use the bot
ALLOWED_USERS=123456789,987654321

# Optional: secret token to validate requests from Coursify backend
STREAM_SECRET=your_random_secret_here
```

### Running the bot

```bash
cd ~/coursify-stream
source venv/bin/activate
python bot.py
```

On first run, if SESSION_STRING is not set, Pyrogram will prompt for OTP via CLI. After generating the session string (§4 Step 4), paste it into `.env` — then the bot starts without interaction.

### Verifying the bot is running

```bash
# Check if port 8080 is listening
curl http://localhost:8080/

# Expected response: some JSON or HTML from the bot
```

### Stream URL format

Once the bot is running, stream URLs follow this pattern:

```
https://PUBLIC_URL/watch/MESSAGE_ID/filename.mp4
```

Example:
```
https://abc123.trycloudflare.com/watch/42/intro-to-python.mp4
```

The `MESSAGE_ID` is the Telegram message ID of the video in the storage channel. The filename is cosmetic — the bot ignores it and uses the `MESSAGE_ID` to look up the file.

---

## 6. Database Schema

Use Supabase (recommended — free tier, REST API, easy to integrate with Vercel).

### Tables

```sql
-- Courses table
CREATE TABLE courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  description TEXT,
  thumbnail_url TEXT,
  is_published BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Sections (chapters within a course)
CREATE TABLE sections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id UUID REFERENCES courses(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Lessons
CREATE TABLE lessons (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  section_id UUID REFERENCES sections(id) ON DELETE CASCADE,
  course_id UUID REFERENCES courses(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  duration_seconds INTEGER,   -- video duration in seconds
  is_free_preview BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Telegram video metadata (linked to lessons)
CREATE TABLE telegram_videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lesson_id UUID UNIQUE REFERENCES lessons(id) ON DELETE CASCADE,
  message_id BIGINT NOT NULL,         -- Telegram message ID in BIN_CHANNEL
  file_id TEXT,                       -- Telegram file_id (can change; use message_id as primary)
  file_unique_id TEXT,                -- Stable unique ID across bots
  file_size_bytes BIGINT,
  mime_type TEXT DEFAULT 'video/mp4',
  original_filename TEXT,
  telegram_channel_id BIGINT NOT NULL, -- The BIN_CHANNEL id
  stream_url TEXT NOT NULL,           -- Full URL: PUBLIC_URL/watch/MESSAGE_ID/filename.mp4
  uploaded_at TIMESTAMPTZ DEFAULT now()
);

-- Learner progress
CREATE TABLE lesson_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,              -- References your auth users table
  lesson_id UUID REFERENCES lessons(id) ON DELETE CASCADE,
  completed BOOLEAN DEFAULT false,
  watch_time_seconds INTEGER DEFAULT 0,
  last_watched_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, lesson_id)
);
```

### Indexes

```sql
CREATE INDEX idx_lessons_course_id ON lessons(course_id);
CREATE INDEX idx_lessons_section_id ON lessons(section_id);
CREATE INDEX idx_telegram_videos_lesson_id ON telegram_videos(lesson_id);
CREATE INDEX idx_lesson_progress_user_id ON lesson_progress(user_id);
```

---

## 7. Video Upload Workflow

The admin's workflow for uploading new course videos:

### Step 1: Upload via Telegram Desktop

1. Open Telegram Desktop.
2. Navigate to the private storage channel.
3. Attach and send the video file (up to 4GB with Premium).
4. Wait for upload to complete. Note the message — it will show in the channel.

### Step 2: Run the upload helper script

This script reads the latest messages from the storage channel, extracts `message_id` and `file_id`, and inserts records into the Coursify database.

Save as `~/coursify-stream/scripts/register_video.py`:

```python
#!/usr/bin/env python3
"""
Usage:
  python register_video.py --lesson_id <uuid> --message_id <int> --title "Lesson Title"

Run after uploading a video to the Telegram storage channel.
Registers the video in the Coursify database and generates the stream URL.
"""

import argparse
import os
import asyncio
from pyrogram import Client
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BIN_CHANNEL = int(os.environ["BIN_CHANNEL"])
PUBLIC_URL = os.environ["PUBLIC_URL"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


async def register_video(lesson_id: str, message_id: int, filename: str):
    async with Client(
        "coursify_session",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING
    ) as app:
        # Fetch the message to get file metadata
        message = await app.get_messages(BIN_CHANNEL, message_id)

        if not message.video and not message.document:
            raise ValueError(f"Message {message_id} does not contain a video or document.")

        media = message.video or message.document
        file_id = media.file_id
        file_unique_id = media.file_unique_id
        file_size = media.file_size
        mime_type = getattr(media, 'mime_type', 'video/mp4')
        duration = getattr(media, 'duration', None)

        # Build stream URL
        safe_filename = filename.replace(" ", "-").lower() + ".mp4"
        stream_url = f"{PUBLIC_URL}/watch/{message_id}/{safe_filename}"

        # Insert into database
        result = supabase.table("telegram_videos").upsert({
            "lesson_id": lesson_id,
            "message_id": message_id,
            "file_id": file_id,
            "file_unique_id": file_unique_id,
            "file_size_bytes": file_size,
            "mime_type": mime_type,
            "original_filename": filename,
            "telegram_channel_id": BIN_CHANNEL,
            "stream_url": stream_url
        }).execute()

        # Update lesson duration if available
        if duration:
            supabase.table("lessons").update({
                "duration_seconds": duration
            }).eq("id", lesson_id).execute()

        print(f"✅ Registered: {filename}")
        print(f"   Lesson ID : {lesson_id}")
        print(f"   Message ID: {message_id}")
        print(f"   Stream URL: {stream_url}")
        print(f"   File size : {file_size / 1024 / 1024:.1f} MB")

        return stream_url


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lesson_id", required=True)
    parser.add_argument("--message_id", required=True, type=int)
    parser.add_argument("--title", required=True, help="Human-readable name (used in stream URL)")
    args = parser.parse_args()

    asyncio.run(register_video(args.lesson_id, args.message_id, args.title))
```

**Example usage:**
```bash
python scripts/register_video.py \
  --lesson_id "a1b2c3d4-..." \
  --message_id 42 \
  --title "intro-to-python-variables"
```

### Step 3: Bulk registration (optional)

For registering many videos at once, use a CSV:

```csv
lesson_id,message_id,title
a1b2c3d4-...,42,intro-to-python
b2c3d4e5-...,43,python-data-types
```

```bash
python scripts/bulk_register.py --csv videos.csv
```

---

## 8. Coursify Integration

### API route — fetch lesson with stream URL

In Next.js, create `pages/api/lessons/[id].js` (or `app/api/lessons/[id]/route.js` for App Router):

```javascript
// pages/api/lessons/[id].js
import { createClient } from '@supabase/supabase-js'

const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY
)

export default async function handler(req, res) {
  const { id } = req.query

  // TODO: Add auth check here — verify the user is enrolled in this course
  // const session = await getSession(req)
  // if (!session) return res.status(401).json({ error: 'Unauthorized' })

  const { data: lesson, error } = await supabase
    .from('lessons')
    .select(`
      id,
      title,
      duration_seconds,
      is_free_preview,
      position,
      telegram_videos (
        stream_url,
        file_size_bytes,
        mime_type
      )
    `)
    .eq('id', id)
    .single()

  if (error || !lesson) {
    return res.status(404).json({ error: 'Lesson not found' })
  }

  // Don't expose stream URL to unenrolled users (unless free preview)
  const streamUrl = lesson.telegram_videos?.stream_url || null

  return res.status(200).json({
    id: lesson.id,
    title: lesson.title,
    duration: lesson.duration_seconds,
    stream_url: streamUrl,
    mime_type: lesson.telegram_videos?.mime_type || 'video/mp4'
  })
}
```

### Video player component

Install a player that supports `Range` requests (required for seeking):

```bash
npm install plyr
# or
npm install video.js
```

Using Plyr:

```jsx
// components/VideoPlayer.jsx
import { useEffect, useRef, useState } from 'react'
import Plyr from 'plyr'
import 'plyr/dist/plyr.css'

export default function VideoPlayer({ lessonId }) {
  const videoRef = useRef(null)
  const playerRef = useRef(null)
  const [streamUrl, setStreamUrl] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetch(`/api/lessons/${lessonId}`)
      .then(r => r.json())
      .then(data => {
        if (data.stream_url) {
          setStreamUrl(data.stream_url)
        } else {
          setError('Video not available')
        }
      })
      .catch(() => setError('Failed to load video'))
      .finally(() => setLoading(false))
  }, [lessonId])

  useEffect(() => {
    if (streamUrl && videoRef.current) {
      // Destroy previous instance
      if (playerRef.current) playerRef.current.destroy()

      playerRef.current = new Plyr(videoRef.current, {
        controls: [
          'play-large', 'play', 'progress', 'current-time',
          'duration', 'mute', 'volume', 'settings', 'fullscreen'
        ],
        settings: ['speed', 'quality'],
        speed: { selected: 1, options: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2] }
      })

      // Track progress
      playerRef.current.on('timeupdate', () => {
        const currentTime = playerRef.current.currentTime
        // Debounce this in production — don't call the API every second
        if (Math.floor(currentTime) % 10 === 0) {
          updateProgress(lessonId, Math.floor(currentTime))
        }
      })

      playerRef.current.on('ended', () => {
        markComplete(lessonId)
      })
    }

    return () => {
      if (playerRef.current) playerRef.current.destroy()
    }
  }, [streamUrl, lessonId])

  if (loading) return <div className="video-skeleton">Loading...</div>
  if (error) return <div className="video-error">{error}</div>

  return (
    <div className="video-wrapper">
      <video
        ref={videoRef}
        controls
        playsInline
        preload="metadata"
      >
        <source src={streamUrl} type="video/mp4" />
        Your browser does not support HTML5 video.
      </video>
    </div>
  )
}

async function updateProgress(lessonId, seconds) {
  await fetch(`/api/progress`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lesson_id: lessonId, watch_time_seconds: seconds })
  })
}

async function markComplete(lessonId) {
  await fetch(`/api/progress/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lesson_id: lessonId })
  })
}
```

### CSS for video player

```css
/* styles/player.css */
.video-wrapper {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.video-wrapper video {
  width: 100%;
  height: 100%;
}

.video-skeleton {
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #1a1a2e;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  font-size: 14px;
}
```

---

## 9. Networking — Exposing the A51 to the Internet

The Samsung A51 is on a local WiFi network. To make FileStreamBot accessible from the internet (so Coursify on Vercel can reach it), you need a tunnel.

### Option A: Cloudflare Tunnel (Recommended — Free, permanent URL)

**Install cloudflared on the A51:**

```bash
# In Termux
pkg install wget -y

# Download cloudflared ARM binary
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm -O cloudflared
chmod +x cloudflared
mv cloudflared /data/data/com.termux/files/usr/bin/
```

**Quick tunnel (no account needed, but URL changes on restart):**

```bash
cloudflared tunnel --url http://localhost:8080
# Outputs: https://random-words.trycloudflare.com
```

**Persistent tunnel with a fixed URL (requires free Cloudflare account):**

1. Sign up at [cloudflare.com](https://cloudflare.com)
2. Add a domain (can use a free Cloudflare-registered domain or your own)
3. Run:

```bash
cloudflared tunnel login          # opens browser for auth
cloudflared tunnel create coursify
cloudflared tunnel route dns coursify stream.yourdomain.com
```

4. Create `~/.cloudflared/config.yml`:
```yaml
tunnel: <tunnel-id-from-above>
credentials-file: /data/data/com.termux/files/home/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: stream.yourdomain.com
    service: http://localhost:8080
  - service: http_status:404
```

5. Run:
```bash
cloudflared tunnel run coursify
```

Now `https://stream.yourdomain.com/watch/MESSAGE_ID/file.mp4` is your permanent stream URL.

Update `PUBLIC_URL` in `.env` with this URL.

### Option B: Ngrok (easier setup, URL changes on free plan)

```bash
# Install ngrok
pkg install wget -y
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm.tgz
tar xzf ngrok-v3-stable-linux-arm.tgz
mv ngrok /data/data/com.termux/files/usr/bin/

# Authenticate (free account at ngrok.com)
ngrok config add-authtoken YOUR_NGROK_TOKEN

# Start tunnel
ngrok http 8080
```

> Note: On Ngrok's free plan, the URL changes every time you restart. For production, use Cloudflare Tunnel.

### Option C: Static IP / Port forwarding (advanced)

If your ISP provides a static IP:
1. Log into your router admin panel.
2. Set up port forwarding: external port `443` → A51 local IP port `8080`.
3. Use `certbot` in Termux to get an SSL certificate.
4. Set `PUBLIC_URL=https://YOUR_STATIC_IP` or point a domain to it.

---

## 10. Environment Variables Reference

### Samsung A51 (`~/coursify-stream/.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `API_ID` | Telegram API ID from my.telegram.org | `12345678` |
| `API_HASH` | Telegram API hash from my.telegram.org | `abc123...` |
| `SESSION_STRING` | Pyrogram user session string | `BQA...long...` |
| `BOT_TOKEN` | Telegram bot token (upload helper only) | `123:ABC...` |
| `BIN_CHANNEL` | Storage channel ID (negative number) | `-1001234567890` |
| `PORT` | Port FileStreamBot listens on | `8080` |
| `HOST` | Host to bind to | `0.0.0.0` |
| `PUBLIC_URL` | Cloudflare tunnel public URL | `https://stream.yourdomain.com` |
| `STREAM_SECRET` | Secret token for request validation | `random_32_char_string` |

### Vercel / Coursify (`vercel env`)

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key (server-side only) |
| `SUPABASE_ANON_KEY` | Supabase anon key (client-side safe) |
| `STREAM_BOT_URL` | Same as `PUBLIC_URL` on the A51 |
| `NEXTAUTH_SECRET` | Random secret for NextAuth sessions |

---

## 11. API Reference

### FileStreamBot endpoints

These are served by the bot running on the A51.

#### `GET /watch/{message_id}/{filename}`

Streams the video file for the given `message_id`.

**Headers supported:**
- `Range: bytes=0-` — Required for video seeking in browser. The bot must return `206 Partial Content`.

**Response:**
```
HTTP/1.1 206 Partial Content
Content-Type: video/mp4
Content-Range: bytes 0-1048575/52428800
Content-Length: 1048576
Accept-Ranges: bytes
```

#### `GET /health`

Returns `200 OK` with `{"status": "ok"}`. Use for uptime monitoring.

### Coursify API routes

#### `GET /api/lessons/:id`

Returns lesson data including stream URL.

**Response:**
```json
{
  "id": "uuid",
  "title": "Introduction to Python",
  "duration": 1834,
  "stream_url": "https://stream.yourdomain.com/watch/42/intro-to-python.mp4",
  "mime_type": "video/mp4"
}
```

#### `POST /api/progress`

Updates watch time for a lesson.

**Body:**
```json
{
  "lesson_id": "uuid",
  "watch_time_seconds": 120
}
```

#### `POST /api/progress/complete`

Marks a lesson as complete.

**Body:**
```json
{
  "lesson_id": "uuid"
}
```

---

## 12. Error Handling & Edge Cases

### Bot is offline / A51 is unreachable

The stream URL will return a network error. Handle this in the Coursify frontend:

```javascript
videoRef.current.addEventListener('error', (e) => {
  console.error('Video error:', e)
  setError('Video temporarily unavailable. Please try again in a few minutes.')
})
```

Consider adding a health check endpoint ping before loading the player:

```javascript
const checkBotHealth = async (streamBotUrl) => {
  try {
    const res = await fetch(`${streamBotUrl}/health`, { signal: AbortSignal.timeout(3000) })
    return res.ok
  } catch {
    return false
  }
}
```

### Telegram rate limits

Telegram applies rate limits on MTProto file downloads per account. If many learners stream simultaneously, you may hit limits. Symptoms: slow streams, `429` errors in the bot logs.

Mitigation:
- FileStreamBot handles chunked reading and has built-in retry logic.
- For very high concurrent traffic, consider caching the first few MB of frequently-accessed videos using Redis or a local file cache on the A51.

### File_id expiry

Telegram's `file_id` can expire or change. The `message_id` is more stable. The bot uses `message_id` to fetch the file, so this is not a problem as long as you store `message_id` (which the schema does).

### Videos over 4GB

If a source video is over 4GB, split it before uploading:

```bash
# Install ffmpeg (on your PC, not the A51)
ffmpeg -i large_video.mp4 -c copy -map 0 -segment_time 3600 -f segment part_%03d.mp4
```

Each part becomes a separate lesson or you handle chapter navigation in Coursify.

### A51 WiFi drops

If the A51's WiFi disconnects, the tunnel goes down. Add a Termux widget or a Tasker profile that reconnects WiFi and restarts services on network change. Alternatively, connect the A51 via ethernet using a USB-C to ethernet adapter.

---

## 13. Performance Considerations

### Streaming performance

The A51 (Snapdragon 665, 4GB RAM) can handle concurrent streams comfortably. Realistic estimate:

| Concurrent streams | Expected performance |
|-------------------|---------------------|
| 1–5 | Excellent (full speed, limited by learner's internet) |
| 5–20 | Good (Telegram rate limits may slow things slightly) |
| 20–50 | Possible, may need multiple Pyrogram sessions |
| 50+ | Not recommended for a single A51 |

### Keep the A51 cool

Continuous streaming generates heat. Tips:
- Don't enclose the phone in a case while running as a server.
- Position it near a fan or in a cool area.
- Monitor temperature via Termux: `cat /sys/class/thermal/thermal_zone0/temp`

### Battery health

For a device permanently plugged in:
- Set a charge limit if your ROM supports it (e.g. 80%).
- Or use a smart plug to cycle power and keep battery around 50–80%.
- Samsung A51 supports a setting: Battery → More battery settings → Protect battery (limits to 85%).

### Video preload

In the Coursify player, use `preload="metadata"` (not `preload="auto"`). This fetches only enough to display duration and dimensions, not the whole file. Saves bandwidth and bot resources.

---

## 14. Security Checklist

- [ ] **Session string is secret.** Never commit `.env` to Git. Add `.env` to `.gitignore`.
- [ ] **Storage channel is private.** Do not make it public. Only the bot has access.
- [ ] **Stream URLs should require authentication.** Don't expose raw stream URLs to unauthenticated users. Gate the API route behind session checks.
- [ ] **Stream secret header.** Optionally, add a `X-Stream-Secret` header to requests from Coursify backend to the bot, so the bot rejects requests that don't come from Coursify.
- [ ] **Rate limit the Coursify API.** Prevent scraping of stream URLs by adding rate limiting (e.g. `express-rate-limit` or Vercel Edge middleware).
- [ ] **Don't expose the A51's local IP.** Cloudflare Tunnel proxies the connection — the device's real IP is not visible.
- [ ] **Keep Termux and Python packages updated.** Run `pkg upgrade` and `pip install --upgrade pyrogram` regularly.
- [ ] **Rotate the STREAM_SECRET periodically.**

---

## 15. Maintenance & Monitoring

### Logs

```bash
# Bot logs
tail -f ~/logs/bot.log

# Tunnel logs
tail -f ~/logs/tunnel.log
```

### Uptime monitoring

Use [UptimeRobot](https://uptimerobot.com) (free) to ping `https://stream.yourdomain.com/health` every 5 minutes. Get email/Telegram alerts if it goes down.

### Restart script

Save as `~/restart-coursify.sh`:
```bash
#!/data/data/com.termux/files/usr/bin/bash
echo "Restarting Coursify services..."
pkill -f "python bot.py"
pkill -f cloudflared
sleep 2
cd ~/coursify-stream
source venv/bin/activate
python bot.py >> ~/logs/bot.log 2>&1 &
cloudflared tunnel run coursify >> ~/logs/tunnel.log 2>&1 &
echo "Done."
```

```bash
chmod +x ~/restart-coursify.sh
```

### Database backups (Supabase)

Supabase free tier includes daily backups. For the `telegram_videos` table specifically, run a weekly export:

```bash
# On any machine with psql
pg_dump $SUPABASE_DB_URL -t telegram_videos > telegram_videos_backup_$(date +%Y%m%d).sql
```

---

## 16. Known Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| A51 requires continuous power | Server down if power cuts | UPS / power bank |
| A51 requires stable WiFi | Streams drop if WiFi drops | USB-C ethernet adapter |
| Telegram rate limits at high concurrency | Slow streams for many simultaneous learners | Multiple Pyrogram sessions, caching |
| Cloudflare free tunnel URL changes on restart | Stream URLs in DB become invalid | Use persistent Cloudflare named tunnel with your own domain |
| Telegram 4GB limit per file | Very long videos must be split | Pre-split with ffmpeg |
| No built-in DRM | Learners can potentially capture stream | Acceptable for most use cases; not suitable for high-value piracy-sensitive content |
| A51 ARM architecture | Some Python packages need compilation | Most packages have ARM wheels; use `pkg install` for system deps |

---

## 17. Phased Implementation Plan

### Phase 1 — Foundation (Week 1)

- [ ] Set up Termux on A51 with Python environment
- [ ] Create private Telegram storage channel
- [ ] Get Telegram API credentials (my.telegram.org)
- [ ] Generate Pyrogram session string
- [ ] Install and configure FileStreamBot
- [ ] Set up Cloudflare Tunnel with a named tunnel
- [ ] Test: upload one video to Telegram, generate stream URL, verify it plays in browser

**Milestone:** A single video streams successfully from the A51 to a browser tab.

### Phase 2 — Database & Backend (Week 2)

- [ ] Set up Supabase project
- [ ] Run database schema migrations (§6)
- [ ] Build and test `register_video.py` script
- [ ] Create Coursify API route `GET /api/lessons/:id`
- [ ] Test: register a video in DB, fetch stream URL via API

**Milestone:** API returns a valid stream URL for a registered lesson.

### Phase 3 — Coursify Frontend (Week 2–3)

- [ ] Integrate `VideoPlayer` component into lesson page
- [ ] Handle loading, error, and unavailable states
- [ ] Implement progress tracking (`/api/progress`)
- [ ] Test: full playback flow in Coursify, including seek and completion tracking

**Milestone:** Learner can watch a full video inside Coursify with progress tracked.

### Phase 4 — Bulk Content Upload (Week 3–4)

- [ ] Upload all course videos to Telegram (batch over several days due to upload time)
- [ ] Register all videos using bulk_register.py CSV workflow
- [ ] QA: verify stream URLs for all lessons

**Milestone:** All 1TB+ of content is accessible via stream URLs.

### Phase 5 — Hardening (Week 4)

- [ ] Add auth checks to API routes (enrollment verification)
- [ ] Set up UptimeRobot monitoring on `/health`
- [ ] Configure Termux:Boot auto-start
- [ ] Test A51 restart recovery end-to-end
- [ ] Set `Protect battery` on A51
- [ ] Document operating procedures for the team

**Milestone:** System is production-ready and self-recovering.

---

## Appendix A — Quick Reference Commands

```bash
# Start bot manually
cd ~/coursify-stream && source venv/bin/activate && python bot.py

# Start tunnel manually
cloudflared tunnel run coursify

# Register a new video
python scripts/register_video.py --lesson_id UUID --message_id 42 --title "lesson-name"

# Check bot is running
curl https://stream.yourdomain.com/health

# View logs
tail -f ~/logs/bot.log
tail -f ~/logs/tunnel.log

# Restart everything
~/restart-coursify.sh

# Check phone temperature
cat /sys/class/thermal/thermal_zone0/temp
```

## Appendix B — Useful Resources

- [Pyrogram documentation](https://docs.pyrogram.org)
- [FileStreamBot (Thunder fork)](https://github.com/databaseandbot-png/FileToLink)
- [Cloudflare Tunnel docs](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
- [Termux Wiki](https://wiki.termux.com)
- [Supabase documentation](https://supabase.com/docs)
- [Plyr video player](https://plyr.io)
- [Telegram API limits](https://core.telegram.org/bots/api#sending-files)

---

*Document version: 1.0 — Update PUBLIC_URL entries throughout whenever the Cloudflare tunnel URL changes.*
