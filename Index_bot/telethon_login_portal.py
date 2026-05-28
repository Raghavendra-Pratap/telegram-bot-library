#!/usr/bin/env python3
"""
One-time Telethon login for the **portal** (streaming / Play).

Uses a separate session file so the bot gateway and portal never lock the same
SQLite session. Run after (or instead of) telethon_login.py for the bot session.

  cd Index_bot
  source venv/bin/activate
  python telethon_login_portal.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from telethon import TelegramClient

from config import Config
from message_verify import telethon_portal_session_path

load_dotenv(_ROOT / ".env")


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw or not str(raw).strip():
        return None
    return int(str(raw).strip())


async def main() -> int:
    api_id = _env_int("API_ID")
    api_hash = os.getenv("API_HASH", "").strip()
    if api_id is None or not api_hash:
        print("Set API_ID and API_HASH in .env — https://my.telegram.org/apps", file=sys.stderr)
        return 1

    session = telethon_portal_session_path()
    print("Telethon login for Index_bot **portal** (streaming)")
    print(f"Session file: {session}")
    print(f"(override with TELETHON_PORTAL_SESSION in .env; default: {Config.TELETHON_PORTAL_SESSION})")
    print("You will be asked for phone number and Telegram login code.\n")

    client = TelegramClient(str(session), api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Portal session logged in as {me.first_name} (id {me.id})")
    print("Restart the portal after this. Bot uploads use forward_ingest.session via the gateway.")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
