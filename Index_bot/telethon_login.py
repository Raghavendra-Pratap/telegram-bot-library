#!/usr/bin/env python3
"""
One-time login for Telethon (used by discover_bot_channels.py and forward_ingest.py).

Run in your terminal (not inside Telegram — it will ask for phone and code):

  cd Index_bot
  source venv/bin/activate
  python telethon_login.py
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

    session = Path(os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"))
    if not session.is_absolute():
        session = _ROOT / session

    print("Telethon login for Index_bot tools")
    print(f"Session file: {session}")
    print("You will be asked for phone number and Telegram login code.\n")

    client = TelegramClient(str(session), api_id, api_hash)
    await client.start()
    me = await client.get_me()
    print(f"\n✅ Logged in as {me.first_name} (id {me.id})")
    print("You can now run /discover_channels in the bot or:")
    print("  python discover_bot_channels.py")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
