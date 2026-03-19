# Admin Setup Guide

## Setting Initial Admins in .env

You can now define initial admin user IDs directly in your `.env` file, so you don't need to use `/adduser` command first!

## How to Set Admins

### Step 1: Get Your User ID

**Method 1: Using @getidsbot (Easiest)**
1. Open Telegram
2. Search for [@getidsbot](https://t.me/getidsbot)
3. Send `/start`
4. Bot will show your user ID (e.g., `123456789`)
5. Copy that number

**Method 2: Using @userinfobot**
1. Forward any message from yourself to [@userinfobot](https://t.me/userinfobot)
2. Bot will reply with your user ID
3. Copy that number

### Step 2: Add to .env

Edit your `.env` file:

```env
# Initial Admin User IDs (comma-separated)
INITIAL_ADMIN_USER_IDS=123456789
```

**For multiple admins:**
```env
INITIAL_ADMIN_USER_IDS=123456789,987654321,555123456
```

### Step 3: Start the Bot

When the bot starts:
- Admins from `INITIAL_ADMIN_USER_IDS` are automatically added
- They can immediately use admin commands
- No need to use `/adduser` first!

## Example Setup

### Personal Bot (Only You as Admin)

```env
ENABLE_USER_VERIFICATION=true
USE_DYNAMIC_USER_MANAGEMENT=true
INITIAL_ADMIN_USER_IDS=123456789
```

### Team Bot (Multiple Admins)

```env
ENABLE_USER_VERIFICATION=true
USE_DYNAMIC_USER_MANAGEMENT=true
INITIAL_ADMIN_USER_IDS=123456789,987654321,555123456
```

## How It Works

### On First Run:
1. Bot reads `INITIAL_ADMIN_USER_IDS` from `.env`
2. Creates `allowed_users.json` file
3. Adds all specified user IDs as admins
4. Admins can immediately use the bot!

### If File Already Exists:
- If no admins exist in the file, initial admins from config are added
- If admins already exist, config admins are added (merged)
- Existing admins are preserved

## Benefits

### ✅ **Bootstrap Admins**
- Set admins before first run
- No need to use `/adduser` command first
- Perfect for production deployments

### ✅ **Multiple Admins**
- Set multiple admins at once
- All admins can manage users immediately

### ✅ **Persistent**
- Admins are saved to `allowed_users.json`
- Survives bot restarts
- Can still use `/adduser` to add more later

## Comparison

### Method 1: Using .env (New - Recommended for Setup)

```env
INITIAL_ADMIN_USER_IDS=123456789,987654321
```

**Pros:**
- ✅ Set before first run
- ✅ Multiple admins at once
- ✅ Good for production
- ✅ No manual commands needed

**Cons:**
- ⚠️ Requires restart to apply changes

### Method 2: Using /adduser Command

```
/adduser 123456789 --admin
```

**Pros:**
- ✅ No restart needed
- ✅ Interactive
- ✅ Can add on-the-fly

**Cons:**
- ⚠️ Need to be first admin or already admin
- ⚠️ One at a time

## Best Practice

**Recommended Approach:**
1. **Set initial admins in `.env`** for bootstrap
2. **Use `/adduser` command** to add more admins later
3. **Use `/adduser --admin`** to promote users to admin

This gives you:
- ✅ Initial setup from config
- ✅ Flexibility to add more later
- ✅ Best of both worlds!

## Example Workflow

### First Time Setup:

1. **Get your user ID:**
   ```
   Send /start to @getidsbot
   Copy your ID: 123456789
   ```

2. **Edit .env:**
   ```env
   ENABLE_USER_VERIFICATION=true
   USE_DYNAMIC_USER_MANAGEMENT=true
   INITIAL_ADMIN_USER_IDS=123456789
   ```

3. **Start bot:**
   ```bash
   python bot.py
   ```

4. **You're now an admin!** ✅
   - Can use `/adduser`, `/approve`, `/requests`, etc.
   - Can manage users immediately

### Adding More Admins Later:

**Option 1: Edit .env and restart**
```env
INITIAL_ADMIN_USER_IDS=123456789,987654321
```

**Option 2: Use command (no restart)**
```
/adduser 987654321 --admin
```

## Troubleshooting

### "I set INITIAL_ADMIN_USER_IDS but I'm not admin"

**Check:**
1. Is `USE_DYNAMIC_USER_MANAGEMENT=true`?
2. Did you restart the bot after editing `.env`?
3. Is your user ID correct? (Check with @getidsbot)
4. Check bot logs for initialization messages

### "Multiple admins not working"

**Check:**
- Format: `INITIAL_ADMIN_USER_IDS=123,456,789` (comma-separated, no spaces)
- All IDs are valid numbers
- Bot was restarted after changes

### "Admins from .env not added"

**Possible reasons:**
- File already exists with admins (they're merged, not replaced)
- `USE_DYNAMIC_USER_MANAGEMENT=false`
- Invalid user ID format

**Solution:**
- Delete `allowed_users.json` and restart (will recreate with initial admins)
- Or use `/adduser` command to add manually

## Summary

| Method | When to Use | Restart Needed |
|--------|-------------|----------------|
| `.env` (INITIAL_ADMIN_USER_IDS) | First setup, production | ✅ Yes |
| `/adduser --admin` | Adding more admins | ❌ No |

**Recommendation:** Use `.env` for initial setup, then use commands for ongoing management!
