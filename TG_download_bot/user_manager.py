"""
User Management System - Dynamic user access control
Allows admin to add/remove users without hardcoding IDs
"""
import json
import logging
from pathlib import Path
from typing import List, Optional, Set, Dict

logger = logging.getLogger(__name__)


class UserManager:
    """Manage allowed users dynamically"""
    
    def __init__(self, users_file: Path = Path("allowed_users.json"), initial_admins: List[int] = None):
        self.users_file = users_file
        self._allowed_users: Set[int] = set()
        self._admin_users: Set[int] = set()
        self._pending_requests: Dict[int, dict] = {}  # user_id -> {username, timestamp, message_id}
        self.initial_admins = initial_admins or []
        self.load_users()
    
    def load_users(self):
        """Load allowed users and admins from file"""
        if not self.users_file.exists():
            # Create default file
            # If initial admins are provided, add them
            if self.initial_admins:
                self._admin_users = set(self.initial_admins)
                logger.info(f"Initializing with {len(self.initial_admins)} admin(s) from config")
            self.save_users()
            logger.info(f"Created new users file: {self.users_file}")
            return
        
        try:
            with open(self.users_file, 'r') as f:
                data = json.load(f)
                self._allowed_users = set(data.get('allowed_users', []))
                self._admin_users = set(data.get('admin_users', []))
                # Load pending requests (convert keys from string to int)
                pending_data = data.get('pending_requests', {})
                self._pending_requests = {
                    int(k): v for k, v in pending_data.items()
                } if pending_data else {}
            
            # If no admins exist but initial admins are provided, add them
            if not self._admin_users and self.initial_admins:
                self._admin_users = set(self.initial_admins)
                logger.info(f"No admins found, initializing with {len(self.initial_admins)} admin(s) from config")
                self.save_users()
            
            logger.info(f"Loaded {len(self._allowed_users)} allowed users, {len(self._admin_users)} admins, {len(self._pending_requests)} pending requests")
        except Exception as e:
            logger.error(f"Error loading users file: {e}")
            self._allowed_users = set()
            self._admin_users = set()
            # If error loading, try to initialize with config admins
            if self.initial_admins:
                self._admin_users = set(self.initial_admins)
                logger.info(f"Initializing with {len(self.initial_admins)} admin(s) from config after load error")
                self.save_users()
    
    def save_users(self):
        """Save allowed users and admins to file"""
        try:
            data = {
                'allowed_users': list(self._allowed_users),
                'admin_users': list(self._admin_users),
                'pending_requests': self._pending_requests
            }
            with open(self.users_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved {len(self._allowed_users)} allowed users, {len(self._admin_users)} admins, {len(self._pending_requests)} pending requests")
        except Exception as e:
            logger.error(f"Error saving users file: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        return user_id in self._admin_users
    
    def is_allowed(self, user_id: int) -> bool:
        """Check if user is allowed to use the bot"""
        # Admins are always allowed
        if self.is_admin(user_id):
            return True
        return user_id in self._allowed_users
    
    def add_user(self, user_id: int, is_admin: bool = False) -> bool:
        """Add a user to allowed list"""
        if is_admin:
            self._admin_users.add(user_id)
            logger.info(f"Added admin user: {user_id}")
        else:
            self._allowed_users.add(user_id)
            logger.info(f"Added allowed user: {user_id}")
        self.save_users()
        return True
    
    def remove_user(self, user_id: int) -> bool:
        """Remove a user from allowed list (but not from admins)"""
        if user_id in self._allowed_users:
            self._allowed_users.remove(user_id)
            self.save_users()
            logger.info(f"Removed user: {user_id}")
            return True
        return False
    
    def remove_admin(self, user_id: int) -> bool:
        """Remove a user from admin list"""
        if user_id in self._admin_users:
            self._admin_users.remove(user_id)
            self.save_users()
            logger.info(f"Removed admin: {user_id}")
            return True
        return False
    
    def get_allowed_users(self) -> List[int]:
        """Get list of all allowed users"""
        return sorted(list(self._allowed_users))
    
    def get_admin_users(self) -> List[int]:
        """Get list of all admin users"""
        return sorted(list(self._admin_users))
    
    def get_all_users(self) -> List[int]:
        """Get list of all users (allowed + admins)"""
        return sorted(list(self._allowed_users | self._admin_users))
    
    def set_initial_admin(self, user_id: int):
        """Set initial admin (used on first run)"""
        if len(self._admin_users) == 0:
            self._admin_users.add(user_id)
            self.save_users()
            logger.info(f"Set initial admin: {user_id}")
    
    def add_request(self, user_id: int, username: str, message_id: int = None):
        """Add a pending access request"""
        import time
        self._pending_requests[user_id] = {
            'username': username,
            'timestamp': time.time(),
            'message_id': message_id
        }
        self.save_users()
        logger.info(f"Added access request from user {user_id} ({username})")
    
    def remove_request(self, user_id: int) -> bool:
        """Remove a pending request"""
        if user_id in self._pending_requests:
            del self._pending_requests[user_id]
            self.save_users()
            logger.info(f"Removed access request from user {user_id}")
            return True
        return False
    
    def get_pending_requests(self) -> Dict[int, dict]:
        """Get all pending requests"""
        return self._pending_requests.copy()
    
    def has_pending_request(self, user_id: int) -> bool:
        """Check if user has a pending request"""
        return user_id in self._pending_requests
