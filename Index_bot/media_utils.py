"""Shared rules for which Telegram files count as library content."""
from __future__ import annotations

from pathlib import Path

# Subtitles and similar — not indexed or forwarded for backfill
SUBTITLE_EXTENSIONS = frozenset({".srt", ".vtt", ".ass", ".ssa", ".sub"})


def is_subtitle_filename(file_name: str | None) -> bool:
    if not file_name or not str(file_name).strip():
        return False
    return Path(str(file_name).strip()).suffix.lower() in SUBTITLE_EXTENSIONS


def is_indexable_filename(file_name: str | None) -> bool:
    """True for video/audio/documents we want in the library."""
    return not is_subtitle_filename(file_name)


def should_skip_local_scan_path(path: Path) -> bool:
    """
    Skip macOS / Windows junk when scanning folders on disk.
    AppleDouble files (._name.mp4) duplicate every file on external volumes.
    """
    name = path.name
    if name.startswith("._"):
        return True
    if name in (".DS_Store", "Thumbs.db", "desktop.ini"):
        return True
    if name.startswith("."):
        return True
    if "__MACOSX" in path.parts:
        return True
    return False
