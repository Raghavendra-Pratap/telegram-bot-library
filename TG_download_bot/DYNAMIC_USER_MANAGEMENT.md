# Dynamic User Management Guide

## Overview

Instead of hardcoding user IDs in the `.env` file, you can now manage users dynamically through bot commands!

## Features

- ✅ **No hardcoding** - Add/remove users via bot commands
- ✅ **Admin system** - First user becomes admin automatically
- ✅ **Easy management** - Reply to messages to add users
- ✅ **Persistent storage** - Users saved in JSON file
- ✅ **Admin commands** - Only admins can manage users

## Setup

### 1. Enable Dynamic User Management

In your `.env` file:

```env
ENABLE_USER_VERIFICATION=true
USE_DYNAMIC_USER_MANAGEMENT=true
```

### 2. Start the Bot

When you first start the bot and send `/adduser`, you'll automatically become the first admin!

## Commands

### For Admins:

#### `/adduser` - Add a User

**Usage 1: Reply to a message**
```
1. User sends a message to the bot
2. Admin replies with: /adduser
3. User is added automatically!
```

**Usage 2: With user ID**
```
/adduser 123456789
```

**Make someone admin:**
```
/adduser 123456789 --admin
# or
/adduser 123456789 -a
```

#### `/removeuser` - Remove a User

**Usage 1: Reply to a message**
```
1. User sends a message to the bot
2. Admin replies with: /removeuser
3. User is removed!
```

**Usage 2: With user ID**
```
/removeuser 123456789
```

#### `/listusers` - List All Users

Shows all admins and regular users:
```
/listusers
```

## How It Works

### First Run

1. Start the bot
2. Send `/adduser` (to yourself)
3. You become the first admin automatically!
4. Now you can add other users

### Adding Users

**Method 1: Reply to Message (Easiest)**
```
User: /start
Admin: /adduser (as reply)
→ User is added!
```

**Method 2: With User ID**
```
Admin: /adduser 123456789
→ User is added!
```

### User Storage

Users are stored in `allowed_users.json`:

```json
{
  "allowed_users": [123456789, 987654321],
  "admin_users": [123456789]
}
```

This file is created automatically and persists across bot restarts.

## Examples

### Example 1: First Time Setup

1. **Start bot** with `ENABLE_USER_VERIFICATION=true` and `USE_DYNAMIC_USER_MANAGEMENT=true`
2. **Send `/adduser`** to the bot
3. **You become admin!** ✅
4. **Add team members:**
   - They send `/start`
   - You reply with `/adduser`
   - They're added! ✅

### Example 2: Adding Multiple Users

```
Admin: /adduser 111111111
Admin: /adduser 222222222
Admin: /adduser 333333333
```

All three users are now allowed!

### Example 3: Making Someone Admin

```
Admin: /adduser 123456789 --admin
```

User 123456789 is now an admin and can manage users too!

### Example 4: Removing a User

```
Admin: /removeuser 123456789
```

User is removed and can no longer use the bot.

## Admin vs Regular Users

### Admins
- ✅ Can use the bot
- ✅ Can add/remove users
- ✅ Can view user list
- ✅ Can make other users admin

### Regular Users
- ✅ Can use the bot
- ❌ Cannot manage users

## File Structure

```
TG_download_bot/
├── allowed_users.json    ← Users stored here
├── bot.py
├── user_manager.py      ← User management logic
└── ...
```

## Migration from Hardcoded IDs

If you were using hardcoded IDs before:

### Old Way (Hardcoded):
```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=123456789,987654321
```

### New Way (Dynamic):
```env
ENABLE_USER_VERIFICATION=true
USE_DYNAMIC_USER_MANAGEMENT=true
```

Then use commands:
```
/adduser 123456789
/adduser 987654321
```

## Troubleshooting

### "Only admins can add users"

**Problem:** You're not an admin yet.

**Solution:**
1. Send `/adduser` to the bot
2. You'll become the first admin automatically!

### "User not found in allowed list"

**Problem:** User was never added or was removed.

**Solution:**
1. Use `/adduser` to add them again
2. Or check `/listusers` to see current users

### "You cannot remove yourself as admin"

**Problem:** You're trying to remove yourself.

**Solution:**
- You can't remove yourself (safety feature)
- Add another admin first, then they can remove you if needed

### "Dynamic user management is disabled"

**Problem:** `USE_DYNAMIC_USER_MANAGEMENT=false` in `.env`

**Solution:**
1. Set `USE_DYNAMIC_USER_MANAGEMENT=true` in `.env`
2. Restart bot

## Security Notes

- ✅ Only admins can manage users
- ✅ First user automatically becomes admin
- ✅ Admins can't remove themselves (safety)
- ✅ User list is stored locally in JSON file
- ⚠️ Keep `allowed_users.json` secure (contains user IDs)

## Comparison

| Feature | Hardcoded IDs | Dynamic Management |
|---------|--------------|-------------------|
| Setup | Edit .env file | Use bot commands |
| Add user | Edit .env, restart | `/adduser` command |
| Remove user | Edit .env, restart | `/removeuser` command |
| Admin system | ❌ No | ✅ Yes |
| Easy to use | ❌ No | ✅ Yes |
| Requires restart | ✅ Yes | ❌ No |

## Summary

**Dynamic user management is recommended** because:
- ✅ No need to edit files
- ✅ No need to restart bot
- ✅ Easy to use (reply to messages)
- ✅ Admin system for better control
- ✅ Persistent storage

Just enable it and start managing users through the bot!
