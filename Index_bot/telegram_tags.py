"""
Telegram hashtag formatting for captions (tap to search within the chat).
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def to_telegram_hashtag(label: str) -> str:
    """Turn a genre, person name, or year into a clickable #Tag (underscores for spaces)."""
    raw = (label or "").strip()
    if not raw:
        return ""
    normalized = re.sub(r"[-/&]+", " ", raw)
    words = _WORD_RE.findall(normalized)
    if not words:
        return ""
    return "#" + "_".join(words)


def to_telegram_year_hashtag(year: int | str) -> str:
    """Year hashtag with a letter prefix — Telegram ignores tags that are only digits."""
    y = str(year).strip()
    if y.isdigit():
        return f"#year_{y}"
    return to_telegram_hashtag(y)


def join_hashtags(labels: list, *, limit: int = 6) -> str:
    tags: list[str] = []
    seen: set[str] = set()
    for label in labels[:limit]:
        tag = to_telegram_hashtag(str(label))
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return " ".join(tags)
