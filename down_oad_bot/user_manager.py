"""
Dynamic user approval system.

Approved/pending/denied state is persisted in data/users.json so it survives
bot restarts.  Users listed in ALLOWED_USER_IDS (from .env) are always allowed
and bypass this system entirely.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_FILE = Path(__file__).parent / "data" / "users.json"

_SCHEMA = {"approved": [], "pending": {}, "denied": []}


class UserManager:
    def __init__(self, data_file: Path = _DATA_FILE):
        self._file = data_file
        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = {}
        self._load()

    # ------------------------------------------------------------------ I/O --

    def _load(self) -> None:
        if self._file.exists():
            try:
                with open(self._file) as f:
                    self._data = json.load(f)
                # Ensure all keys exist (forward-compat with old files)
                for key, default in _SCHEMA.items():
                    self._data.setdefault(key, type(default)())
            except Exception as e:
                logger.error(f"Failed to load user data, starting fresh: {e}")
                self._data = {k: type(v)() for k, v in _SCHEMA.items()}
        else:
            self._data = {k: type(v)() for k, v in _SCHEMA.items()}

    def _save(self) -> None:
        try:
            with open(self._file, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save user data: {e}")

    # ------------------------------------------------------------ Predicates --

    def is_approved(self, user_id: int) -> bool:
        return user_id in self._data["approved"]

    def is_pending(self, user_id: int) -> bool:
        return str(user_id) in self._data["pending"]

    def is_denied(self, user_id: int) -> bool:
        return user_id in self._data["denied"]

    def get_pending_info(self, user_id: int) -> dict:
        return self._data["pending"].get(str(user_id), {})

    # -------------------------------------------------------------- Mutations --

    def add_pending(self, user_id: int, name: str, username: str | None = None) -> None:
        """Register a new access request.  No-op if already in any state."""
        if self.is_approved(user_id) or self.is_pending(user_id) or self.is_denied(user_id):
            return
        self._data["pending"][str(user_id)] = {
            "name": name,
            "username": username or "",
            "requested_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        logger.info(f"New access request from user {user_id} ({name})")

    def approve(self, user_id: int) -> None:
        if user_id not in self._data["approved"]:
            self._data["approved"].append(user_id)
        self._data["pending"].pop(str(user_id), None)
        if user_id in self._data["denied"]:
            self._data["denied"].remove(user_id)
        self._save()
        logger.info(f"User {user_id} approved")

    def deny(self, user_id: int) -> None:
        if user_id not in self._data["denied"]:
            self._data["denied"].append(user_id)
        self._data["pending"].pop(str(user_id), None)
        self._save()
        logger.info(f"User {user_id} denied")

    def revoke(self, user_id: int) -> None:
        """Remove a previously approved user."""
        if user_id in self._data["approved"]:
            self._data["approved"].remove(user_id)
        self._save()
        logger.info(f"User {user_id} revoked")
