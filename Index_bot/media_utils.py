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
