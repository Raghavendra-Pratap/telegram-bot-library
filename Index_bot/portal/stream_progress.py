"""Track bytes relayed from Telegram during portal streaming."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock

_lock = Lock()
_states: dict[int, "StreamProgress"] = {}


@dataclass
class StreamProgress:
    upload_id: int
    request_start: int
    request_end: int
    file_size: int
    bytes_sent: int = 0
    active: bool = True
    error: str | None = None
    started_at: float = field(default_factory=time.time)


def begin(upload_id: int, start: int, end: int, file_size: int) -> None:
    with _lock:
        _states[int(upload_id)] = StreamProgress(
            upload_id=int(upload_id),
            request_start=int(start),
            request_end=int(end),
            file_size=int(file_size or 0),
        )


def add(upload_id: int, nbytes: int) -> None:
    if nbytes <= 0:
        return
    with _lock:
        st = _states.get(int(upload_id))
        if st:
            st.bytes_sent += int(nbytes)


def fail(upload_id: int, message: str) -> None:
    with _lock:
        st = _states.get(int(upload_id))
        if st:
            st.error = message[:200]
            st.active = False


def finish(upload_id: int) -> None:
    with _lock:
        st = _states.get(int(upload_id))
        if st:
            st.active = False


def snapshot(upload_id: int) -> dict | None:
    with _lock:
        st = _states.get(int(upload_id))
        if not st:
            return None
        req_total = max(1, st.request_end - st.request_start + 1)
        req_pct = min(100.0, st.bytes_sent / req_total * 100.0)
        file_pct = (
            min(100.0, st.bytes_sent / st.file_size * 100.0) if st.file_size > 0 else 0.0
        )
        return {
            "active": st.active,
            "bytes_from_telegram": st.bytes_sent,
            "request_bytes": req_total,
            "request_percent": round(req_pct, 1),
            "file_size": st.file_size,
            "file_percent": round(file_pct, 1),
            "phase": (
                "failed"
                if st.error
                else ("streaming_from_telegram" if st.active else "complete")
            ),
            "error": st.error,
        }
