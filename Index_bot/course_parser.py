"""Parse course lesson filenames and CSV manifest rows."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# 01 - Title.mp4, 01. Title, M02 - L05 - Title
_COURSE_PATTERNS = [
    re.compile(
        r"^(?:(?:m|mod(?:ule)?)\s*(\d+)[\s._-]+)?(?:l|lec(?:ture)?\s*)?(\d+)[\s._-]+(.+)$",
        re.I,
    ),
    re.compile(r"^(\d+)[\s._-]+(.+)$"),
]


def parse_lesson_filename(file_name: str) -> dict:
    """Extract module, lesson number, title from a filename stem."""
    stem = Path(file_name or "").stem.strip()
    module_num = None
    lesson_num = None
    title = stem

    for pat in _COURSE_PATTERNS:
        m = pat.match(stem)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                module_num = _int_or_none(groups[0])
                lesson_num = _int_or_none(groups[1])
                title = (groups[2] or stem).strip()
            elif len(groups) == 2:
                lesson_num = _int_or_none(groups[0])
                title = (groups[1] or stem).strip()
            break

    return {
        "module": f"Module {module_num:02d}" if module_num is not None else None,
        "module_number": module_num,
        "lesson_number": lesson_num,
        "lesson_title": title[:200] if title else stem[:200],
    }


def _int_or_none(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return None


def parse_manifest_csv(text: str) -> list[dict]:
    """
    CSV columns: sequence,module,lesson_title,filename
    Header row optional (auto-detected).
    """
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        return []
    fields = {f.lower().strip(): f for f in reader.fieldnames if f}
    seq_k = fields.get("sequence") or fields.get("seq") or fields.get("order")
    mod_k = fields.get("module")
    title_k = fields.get("lesson_title") or fields.get("title") or fields.get("lesson")
    file_k = fields.get("filename") or fields.get("file")
    path_k = fields.get("path") or fields.get("local_path") or fields.get("filepath")
    size_k = fields.get("file_size") or fields.get("size")
    if not file_k and not path_k:
        return []

    rows: list[dict] = []
    for i, row in enumerate(reader):
        raw_path = (row.get(path_k) or "").strip() if path_k else ""
        fn = (row.get(file_k) or "").strip() if file_k else ""
        if not fn and raw_path:
            fn = raw_path
        if not fn:
            continue
        local_path = raw_path or None
        if local_path and not Path(local_path).is_absolute():
            local_path = str(Path(local_path).expanduser())
        seq_raw = row.get(seq_k) if seq_k else None
        try:
            sequence = int(str(seq_raw).strip()) if seq_raw not in (None, "") else i + 1
        except (TypeError, ValueError):
            sequence = i + 1
        module = (row.get(mod_k) or "").strip() if mod_k else None
        lesson_title = (row.get(title_k) or "").strip() if title_k else None
        if not lesson_title:
            lesson_title = Path(fn).stem
        file_size = None
        if size_k:
            try:
                file_size = int(str(row.get(size_k) or "").strip())
            except (TypeError, ValueError):
                file_size = None
        entry: dict = {
            "sequence": sequence,
            "module": module or None,
            "lesson_title": lesson_title,
            "file_name": Path(fn).name,
        }
        if local_path:
            entry["local_path"] = local_path
        if file_size is not None:
            entry["file_size"] = file_size
        rows.append(entry)
    return rows


def scan_folder(
    root: Path,
    *,
    extensions: frozenset[str] | None = None,
    on_progress=None,
) -> list[dict]:
    """Build manifest rows from folder tree (sorted paths)."""
    if extensions is None:
        extensions = frozenset(
            {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".mp3", ".m4a", ".pdf"}
        )
    from media_utils import should_skip_local_scan_path

    root = root.resolve()
    files: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in extensions:
            continue
        if should_skip_local_scan_path(p):
            continue
        files.append(p)
        if on_progress and len(files) % 25 == 0:
            on_progress(
                {
                    "phase": "listing",
                    "found": len(files),
                    "current": str(p.relative_to(root)),
                }
            )
    files.sort(key=lambda p: str(p.relative_to(root)).lower())
    if on_progress:
        on_progress({"phase": "listing", "found": len(files), "done_list": True})

    rows: list[dict] = []
    total = len(files)
    for i, p in enumerate(files):
        rel = p.relative_to(root)
        module = rel.parts[0] if len(rel.parts) > 1 else None
        parsed = parse_lesson_filename(p.name)
        rows.append(
            {
                "sequence": i + 1,
                "module": module or parsed.get("module"),
                "lesson_title": parsed.get("lesson_title") or p.stem,
                "file_name": p.name,
                "local_path": str(p),
            }
        )
        if on_progress and (i == 0 or (i + 1) % 40 == 0 or i + 1 == total):
            on_progress(
                {
                    "phase": "indexing",
                    "current": i + 1,
                    "total": total,
                    "file_name": p.name,
                }
            )
    return rows
