#!/usr/bin/env python3
"""Upload files from an upload job to a Telegram channel via Telethon."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
from upload_job_runner import run_upload_job

load_dotenv(_ROOT / ".env")


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw or not str(raw).strip():
        return None
    return int(str(raw).strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", type=int, required=True)
    ap.add_argument("--delay", type=float, default=3.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    api_id = _env_int("API_ID")
    api_hash = os.getenv("API_HASH", "").strip()
    if api_id is None or not api_hash:
        print("Set API_ID and API_HASH in .env", file=sys.stderr)
        return 1

    session = Path(os.getenv("FORWARD_INGEST_SESSION", "forward_ingest.session"))
    if not session.is_absolute():
        session = _ROOT / session

    try:
        result = asyncio.run(
            run_upload_job(
                job_id=args.job,
                session_path=session,
                api_id=api_id,
                api_hash=api_hash,
                delay_s=args.delay,
                dry_run=args.dry_run,
            )
        )
        if result.get("dry_run"):
            print(f"Dry run: would upload {result['total']} files")
            return 0
        ok = result["ok"]
        fail = result["fail"]
        total = result["total"]
        print(f"Done: {ok}/{total} ok, {fail} failed. Keep bot.py running to index posts.")
        return 0 if fail == 0 else 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
