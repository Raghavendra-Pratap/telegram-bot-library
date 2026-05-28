"""Content fingerprints for duplicate detection across channels."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from name_parser import NameParser

_parser = NameParser()

# Strip release noise for basename matching (light touch)
_NOISE_RE = re.compile(
    r"\b(webrip|web[- ]?dl|bluray|brrip|x265|x264|hevc|h\.?265|h\.?264|"
    r"\d{3,4}p|2160p|4k|aac|ac3|dts|remux)\b",
    re.I,
)


def normalize_basename(file_name: str) -> str:
    base = Path(file_name or "").stem.lower()
    base = _NOISE_RE.sub(" ", base)
    base = re.sub(r"[^\w\s.-]", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base[:240] if base else ""


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Full-file SHA-256 for local duplicate detection (upload planner)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def compute_content_fingerprint(
    file_name: str,
    file_size: int | None,
    *,
    file_unique_id: str | None = None,
    sha256: str | None = None,
) -> str:
    """
    Stable fingerprint for duplicate lookup.
    Priority: sha256 (local) > Telegram file_unique_id > size + normalized name.
    """
    digest = (sha256 or "").strip().lower()
    if digest:
        raw = f"sha256:{digest}"
    else:
        uid = (file_unique_id or "").strip()
        if uid:
            raw = f"uid:{uid}"
        else:
            norm = normalize_basename(file_name)
            size = int(file_size) if file_size is not None else 0
            raw = f"sz:{size}|{norm}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def fingerprint_from_local_path(
    path: str | Path,
    *,
    use_sha256: bool = False,
) -> tuple[str, int | None, str]:
    """For upload planner CLI — optional full-file hash."""
    p = Path(path)
    size = p.stat().st_size if p.is_file() else None
    name = p.name
    sha = sha256_file(p) if use_sha256 and p.is_file() else None
    fp = compute_content_fingerprint(name, size, sha256=sha)
    return fp, size, name
