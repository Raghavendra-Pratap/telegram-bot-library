"""
User management module for handling admins and allowed users
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Optional

# Path to users.json file
USERS_FILE = Path(__file__).parent / "users.json"


def load_users() -> Dict:
    """Load users from JSON file"""
    if not USERS_FILE.exists():
        # Create default structure
        default_data = {
            "admins": [392173275],  # Default admin
            "allowed_users": []
        }
        save_users(default_data)
        return default_data
    
    try:
        with open(USERS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading users.json: {e}")
        # Return default structure on error
        return {
            "admins": [392173275],
            "allowed_users": []
        }


def save_users(data: Dict):
    """Save users to JSON file"""
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving users.json: {e}")


def is_admin(user_id: int) -> bool:
    """Check if user is an admin"""
    users_data = load_users()
    return user_id in users_data.get("admins", [])


def is_allowed_user(user_id: int) -> bool:
    """Check if user is in allowed users list"""
    users_data = load_users()
    return user_id in users_data.get("allowed_users", [])


def get_admins() -> List[int]:
    """Get list of admin user IDs"""
    users_data = load_users()
    return users_data.get("admins", [])


def get_allowed_users() -> List[int]:
    """Get list of allowed user IDs"""
    users_data = load_users()
    return users_data.get("allowed_users", [])


def add_allowed_user(user_id: int) -> bool:
    """Add user to allowed users list"""
    users_data = load_users()
    allowed = users_data.get("allowed_users", [])
    
    if user_id not in allowed:
        allowed.append(user_id)
        users_data["allowed_users"] = allowed
        save_users(users_data)
        return True
    return False


def remove_allowed_user(user_id: int) -> bool:
    """Remove user from allowed users list"""
    users_data = load_users()
    allowed = users_data.get("allowed_users", [])
    
    if user_id in allowed:
        allowed.remove(user_id)
        users_data["allowed_users"] = allowed
        save_users(users_data)
        return True
    return False


def add_admin(user_id: int) -> bool:
    """Add user to admins list"""
    users_data = load_users()
    admins = users_data.get("admins", [])
    
    if user_id not in admins:
        admins.append(user_id)
        users_data["admins"] = admins
        save_users(users_data)
        return True
    return False
