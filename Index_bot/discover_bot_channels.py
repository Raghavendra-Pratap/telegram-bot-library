#!/usr/bin/env python3
"""
Find Telegram channels/groups where Index Bot is an administrator.

The Bot API cannot list all chats the bot is in. This script uses your
Telegram *user* session (Telethon, same as forward_ingest.py) to scan dialogs
you can access and registers every chat where the bot appears in the admin list.

Limitation: only channels your user account can see are scanned.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from telethon import TelegramClient, utils
from telethon.errors import ChatAdminRequiredError, ChannelPrivateError, FloodWaitError
from telethon.tl.types import ChannelParticipantsAdmins

load_dotenv(_ROOT / ".env")

from config import Config
from database import Database

ProgressCallback = Optional[Callable[[int, int, int], Awaitable[None]]]


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


async def discover_bot_admin_channels(
    *,
    api_id: int,
    api_hash: str,
    session_path: Path,
    bot_token: str,
    progress_callback: ProgressCallback = None,
) -> tuple[list, int, int]:
    """
    Returns (registered_channel_rows, dialogs_scanned, admin_channels_found).
    """
    from telegram import Bot

    tg_bot = Bot(token=bot_token)
    me = await tg_bot.get_me()
    bot_id = me.id
    await tg_bot.shutdown()

    db = Database()
    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError(
            "Telethon is not logged in yet.\n\n"
            "In your computer terminal (Cursor → Terminal):\n"
            "  cd Index_bot\n"
            "  source venv/bin/activate\n"
            "  python telethon_login.py\n\n"
            "Enter your phone + Telegram code when asked.\n"
            "Then run /discover_channels again in the bot."
        )

    registered: list = []
    scanned = 0
    found_admin = 0

    try:
        async for dialog in client.iter_dialogs():
            if not (dialog.is_channel or dialog.is_group):
                continue
            entity = dialog.entity
            scanned += 1

            if progress_callback and scanned % 15 == 0:
                await progress_callback(scanned, found_admin, len(registered))

            try:
                is_bot_admin = False
                async for participant in client.iter_participants(
                    entity, filter=ChannelParticipantsAdmins
                ):
                    if participant.id == bot_id:
                        is_bot_admin = True
                        break
                if not is_bot_admin:
                    continue

                found_admin += 1
                channel_id = utils.get_peer_id(entity)
                title = getattr(entity, "title", None) or dialog.name
                username = getattr(entity, "username", None)
                row = db.auto_register_channel(
                    channel_id=str(channel_id),
                    channel_username=username,
                    channel_title=title,
                )
                registered.append(row)
                print(f"  + {title} ({channel_id})" + (f" @{username}" if username else ""))

            except (ChannelPrivateError, ChatAdminRequiredError):
                continue
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
            except Exception as exc:
                print(f"  ! skip {getattr(entity, 'title', dialog.name)}: {exc}", file=sys.stderr)
    finally:
        await client.disconnect()

    return registered, scanned, found_admin


async def _run_cli(progress: bool) -> int:
    api_id = _env_int("API_ID")
    api_hash = os.getenv("API_HASH", "").strip()
    if api_id is None or not api_hash:
        print("Missing API_ID or API_HASH in .env", file=sys.stderr)
        return 1
    if not Config.BOT_TOKEN:
        print("Missing BOT_TOKEN in .env", file=sys.stderr)
        return 1

    session = Path(os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"))
    if not session.is_absolute():
        session = _ROOT / session

    print("Scanning dialogs for channels where Index Bot is admin...")
    print("(Only chats your user account can access)\n")

    registered, scanned, found = await discover_bot_admin_channels(
        api_id=api_id,
        api_hash=api_hash,
        session_path=session,
        bot_token=Config.BOT_TOKEN,
    )
    print(
        f"\nDone. Scanned {scanned} channel/group dialogs, "
        f"bot is admin in {found}, registered {len(registered)} in the database."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover channels where Index Bot is admin and register them in the DB.",
    )
    parser.parse_args(argv or sys.argv[1:])
    return asyncio.run(_run_cli(True))


if __name__ == "__main__":
    sys.exit(main())
