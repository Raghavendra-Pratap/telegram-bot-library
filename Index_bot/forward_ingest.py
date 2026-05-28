#!/usr/bin/env python3
"""
Batch-forward channel media (documents / video / audio files) from a source
chat into an ingest channel so Index_bot can index them via channel_post updates.

Requires a normal Telegram user session (API_ID + API_HASH from my.telegram.org).
Run from the Index_bot directory with venv activated.

First run will prompt for phone / login code — same as any Telethon script.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Awaitable, Callable, Optional

ProgressCallback = Optional[Callable[[int, int, int], Awaitable[None]]]

# Ensure imports work when run as script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from database import Database
from telethon import TelegramClient, utils
from telethon.errors import RPCError, FloodWaitError
from telethon.tl.types import MessageService, PeerChannel

load_dotenv(_ROOT / ".env")

from media_utils import is_indexable_filename
from fingerprint import compute_content_fingerprint

# While a backfill job runs, index posts using this source if Telegram omits forward metadata
_active_backfill_source_id: str | None = None


def get_active_backfill_source_id() -> str | None:
    return _active_backfill_source_id


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _peer_id_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


async def resolve_entity(
    client: TelegramClient,
    reference: str,
    *,
    peer_id: str | int | None = None,
    display_name: str | None = None,
):
    """
    Resolve a channel/group for Telethon.

    Numeric IDs from the bot DB often fail with get_entity until the user session
    has seen the chat — we fall back to scanning dialogs and PeerChannel.
    """
    ref = (reference or "").strip()
    target_peer = _peer_id_int(peer_id) or _peer_id_int(ref)
    label = display_name or ref or (str(target_peer) if target_peer else "channel")

    if ref.startswith("@"):
        return await client.get_entity(ref)

    if ref:
        try:
            return await client.get_entity(ref)
        except (ValueError, TypeError):
            pass

    if target_peer is not None:
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            try:
                if utils.get_peer_id(ent) == target_peer:
                    return ent
            except (TypeError, ValueError):
                continue

        peer_str = str(target_peer)
        if peer_str.startswith("-100"):
            try:
                return await client.get_entity(PeerChannel(int(peer_str[4:])))
            except (ValueError, TypeError, RPCError):
                pass
        try:
            return await client.get_entity(target_peer)
        except (ValueError, TypeError, RPCError):
            pass

    raise RuntimeError(
        f'Cannot find "{label}" ({ref or target_peer}).\n\n'
        "Historical ingestion uses your Telegram *user* account (Telethon), not the bot.\n"
        "• Open that channel in Telegram with the same account you used for telethon_login.py\n"
        "• Make sure you are a member (join if it is private)\n"
        "• If the channel is public, set an @username in channel settings and re-register it\n"
        "• Or pick a source channel that appears in your chat list (e.g. Movie Cloud)"
    )


def extract_telethon_message_file(message) -> dict | None:
    """File metadata from a Telethon message (documents, video, audio, photos)."""
    if isinstance(message, MessageService) or getattr(message, "action", None):
        return None
    if not getattr(message, "media", None):
        return None

    file_name = None
    file_size = None
    file_unique_id = None

    f = getattr(message, "file", None)
    if f is not None:
        file_name = getattr(f, "name", None)
        file_size = getattr(f, "size", None)
        fid = getattr(f, "id", None)
        if fid is not None:
            file_unique_id = str(fid)

    if not file_name:
        media = message.media
        doc = getattr(media, "document", None)
        if doc:
            for attr in getattr(doc, "attributes", None) or []:
                name = getattr(attr, "file_name", None)
                if name:
                    file_name = name
                    break
            file_size = file_size or getattr(doc, "size", None)
            if getattr(doc, "id", None) is not None:
                file_unique_id = file_unique_id or str(doc.id)

    if not file_name and getattr(message, "video", None):
        file_name = getattr(message.video, "file_name", None) or f"video_{message.id}.mp4"
        file_size = file_size or getattr(message.video, "size", None)
    if not file_name and getattr(message, "photo", None):
        file_name = f"photo_{message.id}.jpg"
        file_size = file_size or getattr(message.photo, "size", None)

    if not file_name:
        return None
    if not is_indexable_filename(file_name):
        return None
    return {
        "file_name": file_name,
        "file_size": file_size,
        "file_unique_id": file_unique_id,
    }


def _message_filename(message) -> str | None:
    info = extract_telethon_message_file(message)
    return info["file_name"] if info else None


def should_forward_message(message) -> bool:
    """Forward indexable media (skip subtitles and service messages)."""
    return extract_telethon_message_file(message) is not None


async def run_forward(
    *,
    source: str,
    dest: str,
    session_path: Path,
    api_id: int,
    api_hash: str,
    limit: int | None,
    batch_size: int,
    delay_s: float,
    dry_run: bool,
    progress_callback: ProgressCallback = None,
    source_peer_id: str | int | None = None,
    dest_peer_id: str | int | None = None,
    source_label: str | None = None,
    dest_label: str | None = None,
    skip_duplicates: bool = False,
) -> tuple[int, int, int, int]:
    """
    Forward indexable media from source to dest.

    Returns (scanned, indexable_forwarded, skipped_non_media, duplicates_skipped).
    """
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
            "Then start historical ingestion again in the bot."
        )

    global _active_backfill_source_id
    forwarded = 0
    scanned = 0
    skipped_non_media = 0
    duplicates_skipped = 0
    catalog_db = Database() if skip_duplicates or dry_run else None

    if source_peer_id is not None:
        _active_backfill_source_id = str(source_peer_id)
    try:
        source_ent = await resolve_entity(
            client,
            source,
            peer_id=source_peer_id,
            display_name=source_label,
        )
        dest_ent = await resolve_entity(
            client,
            dest,
            peer_id=dest_peer_id,
            display_name=dest_label,
        )

        if progress_callback:
            await progress_callback(0, 0, 0, 0)

        batch_ids: list[int] = []

        async def flush_batch() -> None:
            nonlocal forwarded, batch_ids
            if not batch_ids or dry_run:
                batch_ids.clear()
                return
            try:
                await client.forward_messages(
                    dest_ent,
                    batch_ids,
                    from_peer=source_ent,
                )
                forwarded += len(batch_ids)
            except FloodWaitError as e:
                await asyncio.sleep(e.seconds + 1)
                await client.forward_messages(
                    dest_ent,
                    batch_ids,
                    from_peer=source_ent,
                )
                forwarded += len(batch_ids)
            finally:
                batch_ids.clear()
            await asyncio.sleep(delay_s)

        # Oldest first: replays history like a normal catch-up
        async for message in client.iter_messages(
            source_ent,
            reverse=True,
            limit=limit,
        ):
            scanned += 1
            if progress_callback and (scanned == 1 or scanned % 5 == 0):
                await progress_callback(scanned, forwarded, skipped_non_media, duplicates_skipped)

            info = extract_telethon_message_file(message)
            if not info:
                skipped_non_media += 1
                continue

            if catalog_db:
                fp = compute_content_fingerprint(
                    info["file_name"],
                    info.get("file_size"),
                    file_unique_id=info.get("file_unique_id"),
                )
                incoming = (
                    str(dest_peer_id)
                    if dest_peer_id
                    else catalog_db.get_ingest_channel_id()
                )
                if catalog_db.find_uploads_by_fingerprint(
                    fp, limit=1, incoming_channel_id=incoming
                ):
                    duplicates_skipped += 1
                    if skip_duplicates and not dry_run:
                        continue

            if dry_run:
                forwarded += 1
                continue
            batch_ids.append(message.id)
            if len(batch_ids) >= batch_size:
                await flush_batch()

        await flush_batch()
    finally:
        _active_backfill_source_id = None
        await client.disconnect()

    if progress_callback:
        await progress_callback(scanned, forwarded, skipped_non_media, duplicates_skipped)

    print(
        f"Done. Scanned={scanned} media_forwarded={forwarded} "
        f"skipped_no_media={skipped_non_media} duplicates={duplicates_skipped} "
        f"dry_run={dry_run} skip_duplicates={skip_duplicates}"
    )
    return scanned, forwarded, skipped_non_media, duplicates_skipped


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Forward document/video/audio posts from SOURCE to DEST for Index_bot ingest.",
    )
    p.add_argument(
        "source",
        help="Source channel or group (@username or numeric id)",
    )
    p.add_argument(
        "dest",
        nargs="?",
        default=None,
        help="Ingest channel (@username or id). Omit if set via /set_ingest_channel in the bot.",
    )
    p.add_argument(
        "--session",
        default=os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"),
        help="Telethon session file basename or path (default: forward_ingest.session)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max messages to scan from source (default: all)",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=15,
        help="How many messages to forward per API call (default: 15)",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to sleep after each forward batch (default: 2.0)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Iterate and count indexable media only; do not forward",
    )
    p.add_argument(
        "--skip-duplicates",
        action="store_true",
        help="Do not forward messages that match an existing library fingerprint",
    )
    return p.parse_args(argv)


def resolve_ingest_dest(dest: str | None = None) -> str:
    """Resolve ingest destination from CLI arg or bot database."""
    if dest:
        return dest.strip()
    ingest = Database().get_ingest_channel()
    if not ingest:
        raise RuntimeError(
            "No ingest channel configured.\n"
            "Set one in the bot: /backfill → Register ingest channel."
        )
    if ingest.channel_username:
        return f"@{ingest.channel_username}"
    return ingest.channel_id


def _resolve_dest(dest: str | None) -> str:
    try:
        return resolve_ingest_dest(dest)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    dest = _resolve_dest(args.dest)
    if not args.dest:
        print(f"Using ingest channel from bot DB: {dest}")

    api_id = _env_int("API_ID")
    api_hash = os.getenv("API_HASH", "").strip()
    if api_id is None or not api_hash:
        print(
            "Missing API_ID or API_HASH in .env — get them from https://my.telegram.org/apps",
            file=sys.stderr,
        )
        return 1

    session_path = Path(args.session).expanduser()
    if not session_path.is_absolute():
        session_path = _ROOT / session_path

    try:
        asyncio.run(
            run_forward(
                source=args.source.strip(),
                dest=dest,
                session_path=session_path,
                api_id=api_id,
                api_hash=api_hash,
                limit=args.limit,
                batch_size=max(1, args.batch_size),
                delay_s=max(0.0, args.delay),
                dry_run=args.dry_run,
                skip_duplicates=args.skip_duplicates,
            )
        )
        return 0
    except RPCError as e:
        print(f"Telegram RPC error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
