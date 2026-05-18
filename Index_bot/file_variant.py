"""
Extract quality / format labels from release file names for the watch library UI.
"""
from __future__ import annotations

import re

_RESOLUTION_RE = re.compile(r"\b(\d{3,4}p|2160p|4k|8k|uhd)\b", re.I)
_SOURCE_RE = re.compile(
    r"\b(webrip|web[- ]?dl|bluray|brrip|dvdrip|hdtv|remux|amzn|netflix)\b",
    re.I,
)
_CODEC_RE = re.compile(r"\b(x265|x264|hevc|h\.?265|h\.?264|av1)\b", re.I)
_AUDIO_RE = re.compile(r"\b(aac|ac3|dts|eac3|opus|dd5\.?1)\b", re.I)


def format_file_size(size_bytes: int | None) -> str:
    if not size_bytes or size_bytes <= 0:
        return "?"
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.0f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def extract_quality_label(file_name: str) -> str:
    """Human-readable quality string from a release filename."""
    base = file_name or ""
    parts: list[str] = []

    m = _RESOLUTION_RE.search(base)
    if m:
        parts.append(m.group(1).upper().replace("UHD", "4K"))

    m = _SOURCE_RE.search(base)
    if m:
        src = m.group(1).upper().replace(" ", "").replace("-", "")
        if src == "WEBDL":
            src = "WEB-DL"
        parts.append(src)

    m = _CODEC_RE.search(base)
    if m:
        parts.append(m.group(1).lower().replace(".", ""))

    m = _AUDIO_RE.search(base)
    if m:
        parts.append(m.group(1).upper())

    if not parts:
        return "Standard"
    return " · ".join(parts)


def quality_sort_key(file_name: str, file_size: int | None = None) -> tuple:
    """Sort best quality first (higher res, then larger file)."""
    name = (file_name or "").lower()
    res_score = 0
    if "2160" in name or "4k" in name or "uhd" in name:
        res_score = 4
    elif "1080" in name:
        res_score = 3
    elif "720" in name:
        res_score = 2
    elif "480" in name:
        res_score = 1
    return (-res_score, -(file_size or 0), name)
