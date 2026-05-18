#!/usr/bin/env python3
"""
Periodic sweep: verify indexed channel posts still exist (Telethon).

Run from Index_bot/ with venv activated (same session as forward_ingest):

  python verify_uploads.py
  python verify_uploads.py --limit 1000 --force
  python verify_uploads.py --stale-hours 6

Suitable for cron, e.g. daily:
  0 4 * * * cd /path/to/Index_bot && ./venv/bin/python verify_uploads.py >> verify.log 2>&1
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from database import Database
from message_verify import run_verify_sweep, telethon_configured


async def main() -> int:
    parser = argparse.ArgumentParser(description="Verify indexed Telegram posts still exist")
    parser.add_argument("--limit", type=int, default=500, help="Max uploads to check")
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=24,
        help="Re-check rows older than this (0 with --force checks all in limit)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore last-checked time (still respects --limit)",
    )
    args = parser.parse_args()

    if not telethon_configured():
        print(
            "Set API_ID and API_HASH in .env, then run: python telethon_login.py",
            file=sys.stderr,
        )
        return 1

    db = Database()
    stale = 0 if args.force else args.stale_hours

    def progress(done: int, total: int) -> None:
        print(f"  … {done}/{total}", flush=True)

    async def on_progress(done: int, total: int) -> None:
        progress(done, total)

    print(f"Verifying up to {args.limit} uploads (stale_hours={stale})…")
    checked, available, unavailable, skipped = await run_verify_sweep(
        db,
        limit=args.limit,
        stale_hours=stale,
        force=args.force,
        progress_callback=on_progress,
    )
    print(
        f"Done. Checked: {checked}, still up: {available}, "
        f"removed: {unavailable}, skipped (no access): {skipped}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
