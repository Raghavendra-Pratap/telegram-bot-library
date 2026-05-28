"""Shared upload job planning for CLI and bot UI."""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Callable

from config import Config
from content_lanes import normalize_lane
from course_parser import parse_lesson_filename, parse_manifest_csv, scan_folder
from database import Database
from fingerprint import compute_content_fingerprint, fingerprint_from_local_path

_PATH_QUOTES = "'\"`"


def normalize_user_path(text: str) -> Path:
    """Parse a path from chat/CSV (strip wrapping quotes, expand ~)."""
    raw = (text or "").strip()
    while len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in _PATH_QUOTES:
        raw = raw[1:-1].strip()
    raw = raw.strip(_PATH_QUOTES)
    if not raw:
        raise ValueError("Empty path")
    path = Path(raw).expanduser()
    return path if path.is_absolute() else path.resolve()


ProgressCallback = Callable[[dict[str, Any]], None]


def progress_bar(fraction: float, width: int = 14) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return "█" * filled + "░" * (width - filled)


def format_scan_progress_message(
    info: dict[str, Any], *, folder_label: str | None = None
) -> str:
    """HTML status text for Telegram progress edits."""
    phase = info.get("phase") or "scan"
    lines = ["<b>📂 Scanning folder</b>"]
    if Config.UPLOAD_PLANNER_USE_SHA256:
        lines.append("<i>SHA-256 enabled — large files take longer</i>")
    if folder_label:
        short = folder_label if len(folder_label) <= 72 else "…" + folder_label[-69:]
        lines.append(f"<code>{escape(short)}</code>")

    if phase == "listing":
        found = int(info.get("found") or 0)
        lines.append("")
        lines.append(f"{progress_bar(0.15)}")
        lines.append(f"Discovering files… <b>{found}</b> found so far")
        cur = info.get("current")
        if cur:
            lines.append(f"<i>{escape(str(cur)[:80])}</i>")
    elif phase == "indexing":
        cur = int(info.get("current") or 0)
        total = int(info.get("total") or 1)
        lines.append("")
        lines.append(f"{progress_bar(cur / total if total else 0)}")
        lines.append(f"Reading paths <b>{cur}</b> / <b>{total}</b>")
        fn = info.get("file_name")
        if fn:
            lines.append(f"<i>{escape(str(fn)[:80])}</i>")
    elif phase == "fingerprint":
        cur = int(info.get("current") or 0)
        total = int(info.get("total") or 1)
        sha = info.get("use_sha256")
        lines.append("")
        lines.append(f"{progress_bar(cur / total if total else 0)}")
        label = "Hashing (SHA-256)" if sha else "Checking duplicates"
        lines.append(f"{label} <b>{cur}</b> / <b>{total}</b>")
        fn = info.get("file_name")
        if fn:
            lines.append(f"<i>{escape(str(fn)[:80])}</i>")
    elif phase == "counting":
        lines.append("")
        lines.append(f"{progress_bar(0.95)}")
        lines.append("Comparing with library…")
    elif phase == "done":
        lines.append("")
        lines.append(f"{progress_bar(1.0)}")
        total = info.get("total")
        if total is not None:
            lines.append(
                f"<b>Done</b> — {total} files · "
                f"new <b>{info.get('new', 0)}</b> · "
                f"in library <b>{info.get('dup', 0)}</b>"
            )
        else:
            lines.append("<b>Done</b>")
    return "\n".join(lines)


def enrich_rows(
    rows: list[dict],
    *,
    use_sha256: bool = False,
    on_progress: ProgressCallback | None = None,
) -> list[dict]:
    use_sha = use_sha256 or Config.UPLOAD_PLANNER_USE_SHA256
    total = len(rows)
    for i, row in enumerate(rows):
        lp = row.get("local_path")
        if lp:
            try:
                p = normalize_user_path(str(lp))
            except ValueError:
                p = Path(lp)
            row["local_path"] = str(p)
            if p.is_file():
                fp, size, name = fingerprint_from_local_path(p, use_sha256=use_sha)
                row["content_fingerprint"] = fp
                row["file_size"] = size
                row["file_name"] = name
        elif row.get("file_name") and not row.get("content_fingerprint"):
            row["content_fingerprint"] = compute_content_fingerprint(
                row["file_name"], row.get("file_size")
            )
        if on_progress and total and (
            i == 0 or (i + 1) % 8 == 0 or i + 1 == total
        ):
            on_progress(
                {
                    "phase": "fingerprint",
                    "current": i + 1,
                    "total": total,
                    "file_name": row.get("file_name"),
                    "use_sha256": use_sha,
                }
            )
    return rows


def count_new_and_dupes(
    rows: list[dict],
    db: Database | None = None,
    *,
    channel_id: str | None = None,
) -> tuple[int, int]:
    db = db or Database()
    dup = 0
    for row in rows:
        fp = row.get("content_fingerprint")
        if not fp:
            fp = compute_content_fingerprint(row.get("file_name", ""), row.get("file_size"))
        if db.resolve_library_upload_for_job_item(
            content_fingerprint=fp,
            file_name=row.get("file_name") or "",
            file_size=row.get("file_size"),
            channel_id=channel_id,
        ):
            dup += 1
    return len(rows) - dup, dup


def scan_folder_for_plan(
    folder: Path | str,
    *,
    use_sha256: bool = False,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[dict], int, int]:
    if isinstance(folder, str):
        folder = normalize_user_path(folder)
    else:
        folder = folder.expanduser()
        if not folder.is_absolute():
            folder = folder.resolve()
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    rows = scan_folder(folder, on_progress=on_progress)
    use_sha = use_sha256 or Config.UPLOAD_PLANNER_USE_SHA256
    enrich_rows(rows, use_sha256=use_sha, on_progress=on_progress)
    if on_progress:
        on_progress({"phase": "counting"})
    new, dup = count_new_and_dupes(rows)
    if on_progress:
        on_progress({"phase": "done", "total": len(rows), "new": new, "dup": dup})
    return rows, new, dup


def scan_files_for_plan(
    files: list[Path | str],
    *,
    use_sha256: bool = False,
    on_progress: ProgressCallback | None = None,
) -> tuple[list[dict], int, int]:
    """Build plan rows from one or more explicit local file paths."""
    from media_utils import should_skip_local_scan_path

    if not files:
        raise ValueError("No file paths provided.")
    normalized: list[Path] = []
    for raw in files:
        p = normalize_user_path(str(raw))
        if not p.is_file():
            raise ValueError(f"Not a file: {p}")
        if should_skip_local_scan_path(p):
            raise ValueError(f"Unsupported/ignored path: {p}")
        normalized.append(p)

    rows: list[dict] = []
    total = len(normalized)
    for i, p in enumerate(normalized):
        parsed = parse_lesson_filename(p.name)
        rows.append(
            {
                "sequence": i + 1,
                "module": parsed.get("module"),
                "lesson_title": parsed.get("lesson_title") or p.stem,
                "file_name": p.name,
                "local_path": str(p),
            }
        )
        if on_progress and (i == 0 or (i + 1) % 20 == 0 or i + 1 == total):
            on_progress(
                {
                    "phase": "indexing",
                    "current": i + 1,
                    "total": total,
                    "file_name": p.name,
                }
            )

    use_sha = use_sha256 or Config.UPLOAD_PLANNER_USE_SHA256
    enrich_rows(rows, use_sha256=use_sha, on_progress=on_progress)
    if on_progress:
        on_progress({"phase": "counting"})
    new, dup = count_new_and_dupes(rows)
    if on_progress:
        on_progress({"phase": "done", "total": len(rows), "new": new, "dup": dup})
    return rows, new, dup


def count_new_and_dupes_for_job(
    rows: list[dict], job_id: int, db: Database | None = None
) -> tuple[int, int]:
    db = db or Database()
    job = db.get_upload_job(job_id)
    channel_id = str(job.target_channel_id) if job and job.target_channel_id else None
    return count_new_and_dupes(rows, db, channel_id=channel_id)


def parse_csv_for_plan(
    text: str, *, use_sha256: bool = False
) -> tuple[list[dict], int, int]:
    rows = parse_manifest_csv(text)
    if not rows:
        return [], 0, 0
    enrich_rows(rows, use_sha256=use_sha256)
    return rows, *count_new_and_dupes(rows)


def create_job_from_rows(
    name: str,
    rows: list[dict],
    *,
    content_lane: str = "course",
    course_title: str | None = None,
    target_channel_id: str | None = None,
    created_by: int | None = None,
) -> tuple[int | None, dict]:
    db = Database()
    job = db.create_upload_job(
        name[:200],
        target_channel_id=target_channel_id,
        content_lane=normalize_lane(content_lane),
        course_title=(course_title or name)[:200],
        created_by=created_by,
    )
    if not job:
        return None, {}
    n = db.add_upload_job_items(job.id, rows)
    summary = db.get_upload_job_summary(job.id)
    return job.id, {
        "items": n,
        "summary": summary,
        "decisions": summary.get("decisions") or {},
    }


def format_plan_summary(
    *,
    total: int,
    new: int,
    dup: int,
    lane: str,
    sample_rows: list[dict] | None = None,
) -> str:
    from html import escape

    from content_lanes import LANE_LABELS

    lane_label = LANE_LABELS.get(normalize_lane(lane), lane)
    lines = [
        f"<b>Plan preview</b> · {lane_label}",
        "",
        f"Files: <b>{total}</b>",
        f"New (will upload): <b>{new}</b>",
        f"Already in library: <b>{dup}</b>",
    ]
    if sample_rows:
        lines.append("")
        lines.append("<i>Sample:</i>")
        for row in sample_rows[:6]:
            lines.append(
                f"📄 {escape((row.get('lesson_title') or row.get('file_name') or '?')[:50])}"
            )
        if total > 6:
            lines.append(f"<i>… +{total - 6} more</i>")
    return "\n".join(lines)
