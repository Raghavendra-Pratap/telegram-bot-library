#!/usr/bin/env python3
"""Plan bulk uploads: scan folder or CSV, detect duplicates, create upload job."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import Config
from course_parser import parse_manifest_csv, scan_folder
from database import Database
from fingerprint import fingerprint_from_local_path


def main() -> int:
    ap = argparse.ArgumentParser(description="Create an upload job from folder or CSV")
    ap.add_argument("source", help="Folder path or manifest.csv")
    ap.add_argument("--name", required=True, help="Job name")
    ap.add_argument("--channel", help="Target channel id (@user or -100...)")
    ap.add_argument("--lane", default="course", help="content_lane (default: course)")
    ap.add_argument("--course-title", help="Course collection title")
    ap.add_argument("--dry-run", action="store_true", help="Print plan only, no DB job")
    ap.add_argument(
        "--sha256",
        action="store_true",
        help="Hash file contents for duplicates (slower, exact for local files)",
    )
    args = ap.parse_args()
    use_sha = args.sha256 or Config.UPLOAD_PLANNER_USE_SHA256

    src = Path(args.source).expanduser()
    rows: list[dict] = []
    if src.is_file() and src.suffix.lower() == ".csv":
        rows = parse_manifest_csv(src.read_text(encoding="utf-8", errors="replace"))
    elif src.is_dir():
        rows = scan_folder(src)
    else:
        print(f"Not a folder or .csv: {src}", file=sys.stderr)
        return 1

    if not rows:
        print("No files found.", file=sys.stderr)
        return 1

    for row in rows:
        lp = row.get("local_path")
        if lp and not row.get("file_size"):
            p = Path(lp)
            if p.is_file():
                fp, size, name = fingerprint_from_local_path(p, use_sha256=use_sha)
                row["file_size"] = size
                row["content_fingerprint"] = fp
                row["file_name"] = name
        elif lp and use_sha and not row.get("content_fingerprint"):
            p = Path(lp)
            if p.is_file():
                fp, size, name = fingerprint_from_local_path(p, use_sha256=True)
                row["content_fingerprint"] = fp
                row["file_size"] = row.get("file_size") or size

    db = Database()
    dup = new = 0
    for row in rows:
        fp = row.get("content_fingerprint") or fingerprint_from_local_path(
            Path(row["local_path"]) if row.get("local_path") else Path(row["file_name"])
        )[0]
        if db.find_uploads_by_fingerprint(fp, limit=1):
            dup += 1
        else:
            new += 1

    print(f"Plan: {args.name}")
    print(f"  Files: {len(rows)} · New: {new} · Already in library: {dup}")
    if args.dry_run:
        for row in rows[:20]:
            print(f"  [{row.get('sequence')}] {row.get('file_name')}")
        if len(rows) > 20:
            print(f"  ... +{len(rows) - 20} more")
        return 0

    channel = args.channel
    if not channel:
        from pipeline_setup import resolve_source_channel_for_upload_type

        channel = resolve_source_channel_for_upload_type(args.lane, db=db)

    job = db.create_upload_job(
        args.name,
        target_channel_id=channel,
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
    if job.target_channel_id:
        print(f"  Source channel: {job.target_channel_id}")
    else:
        print(
            "  Source channel: not set — configure Library setup → Pipeline upload targets"
        )
    print(f"\nNext: python course_upload.py --job {job.id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
