#!/usr/bin/env python3
"""
Bridge upload_bot folder scans to Index_bot upload jobs + duplicate report.

Usage (from Index_bot directory):
  python upload_bot_bridge.py /path/to/videos --name "My Course" --channel @Staging
  python upload_bot_bridge.py /path/to/videos --check-only   # fingerprint report only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import Config
from course_parser import scan_folder
from database import Database
from fingerprint import fingerprint_from_local_path


def scan_with_dupes(
    folder: Path, *, use_sha256: bool = False
) -> tuple[list[dict], int, int]:
    rows = scan_folder(folder)
    db = Database()
    new = dup = 0
    for row in rows:
        lp = row.get("local_path")
        if lp:
            p = Path(lp)
            if p.is_file():
                fp, size, name = fingerprint_from_local_path(p, use_sha256=use_sha256)
                row["content_fingerprint"] = fp
                row["file_size"] = size
                row["file_name"] = name
        fp = row.get("content_fingerprint")
        if fp and db.find_uploads_by_fingerprint(fp, limit=1):
            dup += 1
            row["_duplicate"] = True
        else:
            new += 1
            row["_duplicate"] = False
    return rows, new, dup


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan uploads from a folder with Index_bot dedup")
    ap.add_argument("folder", type=Path, help="Folder to scan (same layout as upload_planner)")
    ap.add_argument("--name", help="Job name (required unless --check-only)")
    ap.add_argument("--channel", help="Target Telegram channel for the job")
    ap.add_argument("--lane", default="course")
    ap.add_argument("--course-title", help="Course title metadata")
    ap.add_argument("--check-only", action="store_true", help="Print duplicate report only")
    ap.add_argument("--sha256", action="store_true")
    args = ap.parse_args()

    folder = args.folder.expanduser()
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 1

    use_sha = args.sha256 or Config.UPLOAD_PLANNER_USE_SHA256
    rows, new, dup = scan_with_dupes(folder, use_sha256=use_sha)

    print(f"Folder: {folder}")
    print(f"  Files: {len(rows)} · New: {new} · Already in library: {dup}")
    if args.check_only:
        for row in rows[:30]:
            flag = "DUP" if row.get("_duplicate") else "NEW"
            print(f"  [{flag}] {row.get('file_name')}")
        if len(rows) > 30:
            print(f"  ... +{len(rows) - 30} more")
        return 0

    if not args.name:
        print("--name is required to create a job", file=sys.stderr)
        return 1

    db = Database()
    job = db.create_upload_job(
        args.name,
        target_channel_id=args.channel,
        content_lane=args.lane,
        course_title=args.course_title or args.name,
    )
    if not job:
        print("Failed to create job", file=sys.stderr)
        return 1
    n = db.add_upload_job_items(job.id, rows)
    summary = db.get_upload_job_summary(job.id)
    print(f"Created job #{job.id} with {n} items.")
    print(f"  Decisions: {summary.get('decisions')}")
    print(f"\nIn Telegram: Upload pipeline → job #{job.id} → set target → Start upload")
    print(f"Or CLI: python course_upload.py --job {job.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
