#!/usr/bin/env python3
"""
Find Telegram channels/groups where Index Bot is an administrator.

Uses your Telegram *user* session (Telethon) to scan dialogs you can access.
Bot-admin checks use the Bot API (works even when you are not a channel admin).

Also re-checks channel ids already in the database or from past uploads.
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
from telethon.errors import ChannelPrivateError, FloodWaitError

load_dotenv(_ROOT / ".env")

from config import Config
from database import Database
from bot_channel_access import verify_bot_can_post

ProgressCallback = Optional[Callable[[int, int, int], Awaitable[None]]]


def _collect_candidate_channel_ids(db: Database) -> set[str]:
    """Channel ids already in DB or referenced by indexed uploads."""
    ids: set[str] = set()
    for ch in db.get_all_channels_registered(active_only=False):
        ids.add(str(ch.channel_id))
    session = db.get_session()
    try:
        from sqlalchemy import distinct

        from database import FileUpload

        for (cid,) in session.query(distinct(FileUpload.channel_id)).all():
            if cid:
                ids.add(str(cid))
        for (cid,) in session.query(distinct(FileUpload.source_channel_id)).all():
            if cid:
                ids.add(str(cid))
    finally:
        session.close()
    return ids


async def _register_if_bot_admin(
    tg_bot,
    bot_id: int,
    channel_id: str | int,
    db: Database,
    *,
    title: str | None = None,
    username: str | None = None,
) -> object | None:
    """Register channel when Bot API confirms the bot is admin (no user admin list needed)."""
    cid = int(channel_id)
    try:
        member = await tg_bot.get_chat_member(cid, bot_id)
    except Exception:
        return None
    if member.status not in (CMS.ADMINISTRATOR, CMS.OWNER):
        return None
    if not title or not username:
        try:
            chat = await tg_bot.get_chat(cid)
            title = title or getattr(chat, "title", None)
            username = username or getattr(chat, "username", None)
        except Exception:
            pass
    can_post = await verify_bot_can_post(tg_bot, str(cid))
    return db.auto_register_channel(
        channel_id=str(cid),
        channel_username=username,
        channel_title=title,
        bot_can_post=can_post,
    )


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
    from telegram.constants import ChatMemberStatus as CMS

    tg_bot = Bot(token=bot_token)
    me = await tg_bot.get_me()
    bot_id = me.id

    db = Database()
    registered: list = []
    seen_ids: set[str] = set()
    scanned = 0
    found_admin = 0

    def _track(row) -> None:
        if row is None:
            return
        cid = str(row.channel_id)
        if cid in seen_ids:
            return
        seen_ids.add(cid)
        registered.append(row)

    client = TelegramClient(str(session_path), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        await tg_bot.shutdown()
        raise RuntimeError(
            "Telethon is not logged in yet.\n\n"
            "In your computer terminal (Cursor → Terminal):\n"
            "  cd Index_bot\n"
            "  source venv/bin/activate\n"
            "  python telethon_login.py\n\n"
            "Enter your phone + Telegram code when asked.\n"
            "Then run /discover_channels again in the bot."
        )

    try:
        async for dialog in client.iter_dialogs():
            if not (dialog.is_channel or dialog.is_group):
                continue
            entity = dialog.entity
            scanned += 1

            if progress_callback and scanned % 15 == 0:
                await progress_callback(scanned, found_admin, len(registered))

            try:
                channel_id = str(utils.get_peer_id(entity))
                title = getattr(entity, "title", None) or dialog.name
                username = getattr(entity, "username", None)
                row = await _register_if_bot_admin(
                    tg_bot,
                    bot_id,
                    channel_id,
                    db,
                    title=title,
                    username=username,
                )
                if row is None:
                    continue
                found_admin += 1
                _track(row)
                print(
                    f"  + {title} ({channel_id})"
                    + (f" @{username}" if username else "")
                )
            except ChannelPrivateError:
                continue
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
            except Exception as exc:
                print(
                    f"  ! skip {getattr(entity, 'title', dialog.name)}: {exc}",
                    file=sys.stderr,
                )

        # Channels the bot joined (or indexed before) but user cannot list admins for.
        extra_ids = _collect_candidate_channel_ids(db) - seen_ids
        for channel_id in sorted(extra_ids):
            if progress_callback and scanned % 15 == 0:
                await progress_callback(scanned, found_admin, len(registered))
            row = await _register_if_bot_admin(tg_bot, bot_id, channel_id, db)
            if row is None:
                continue
            found_admin += 1
            _track(row)
            label = row.channel_title or channel_id
            print(f"  + {label} ({channel_id}) [bot API]")
    finally:
        await client.disconnect()
        await tg_bot.shutdown()

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
