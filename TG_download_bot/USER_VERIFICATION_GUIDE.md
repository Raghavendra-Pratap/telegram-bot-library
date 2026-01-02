# User Verification Guide

## What is User Verification?

User verification is a **security feature** that restricts bot access to only specific users you approve.

## Current Setting

```env
ENABLE_USER_VERIFICATION=false
```

**When `false` (current):**
- ✅ **Anyone** can use the bot
- ✅ No restrictions
- ✅ Public access

## If You Change It to `true`

```env
ENABLE_USER_VERIFICATION=true
```

**When `true`:**
- 🔒 **Only approved users** can use the bot
- 🔒 All other users get "Access Denied" message
- 🔒 You must specify which users are allowed

## How It Works

### Step 1: Enable Verification

```env
ENABLE_USER_VERIFICATION=true
```

### Step 2: Add Allowed User IDs

You need to add user IDs to the `ALLOWED_USER_IDS` setting:

```env
ALLOWED_USER_IDS=123456789,987654321,555123456
```

**How to Get User IDs:**

1. **Method 1: Using @userinfobot**
   - Forward any message from the user to [@userinfobot](https://t.me/userinfobot)
   - It will reply with the user's ID
   - Copy the ID number

2. **Method 2: Using @getidsbot**
   - Send `/start` to [@getidsbot](https://t.me/getidsbot)
   - It will show your own user ID
   - Ask other users to do the same

3. **Method 3: From Bot Logs**
   - When someone tries to use the bot, check the logs
   - You'll see: `Unauthorized access attempt by user 123456789`
   - Copy that number

### Step 3: Restart Bot

After updating `.env`, restart the bot:

```bash
# Stop the bot (Ctrl+C)
# Then start again
python bot.py
```

## Example Configuration

### For Personal Use (Only You)

```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=123456789
```
(Replace `123456789` with your actual user ID)

### For Team Use (Multiple Users)

```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=123456789,987654321,555123456
```
(Comma-separated list of user IDs)

## What Users See

### Authorized Users
- ✅ Can use all bot commands
- ✅ Can download files
- ✅ Normal bot experience

### Unauthorized Users
When they try to use the bot, they see:

```
🚫 Access Denied

This bot is restricted to authorized users only.

If you believe you should have access, please contact the bot administrator.
```

## Important Notes

### ⚠️ If You Enable Verification But Don't Add User IDs

```env
ENABLE_USER_VERIFICATION=true
ALLOWED_USER_IDS=
```

**Result:**
- ❌ **NO ONE** can use the bot (including you!)
- ❌ Bot will reject all users
- ⚠️ You'll see warning in logs: "User verification enabled but no allowed users specified!"

**Fix:** Add at least one user ID to `ALLOWED_USER_IDS`

### ⚠️ Adding Your Own User ID

**Important:** When you enable verification, make sure to add **your own user ID** first, or you'll lock yourself out!

1. Get your user ID (use @userinfobot or @getidsbot)
2. Add it to `ALLOWED_USER_IDS`
3. Then enable verification

## Use Cases

### When to Enable (`true`):

✅ **Personal bot** - Only you use it
✅ **Team bot** - Only specific team members
✅ **Private service** - Limited access
✅ **Cost control** - Limit who can use premium account
✅ **Security** - Prevent unauthorized usage

### When to Disable (`false`):

✅ **Public bot** - Anyone can use it
✅ **Testing** - Easier to test with multiple users
✅ **Open service** - No restrictions needed

## Quick Setup Example

### Scenario: Personal Bot (Only You)

1. Get your user ID:
   - Send `/start` to [@getidsbot](https://t.me/getidsbot)
   - Copy your ID (e.g., `123456789`)

2. Update `.env`:
   ```env
   ENABLE_USER_VERIFICATION=true
   ALLOWED_USER_IDS=123456789
   ```

3. Restart bot

4. Test: Only you can use the bot now!

### Scenario: Team Bot (3 People)

1. Get all user IDs:
   - User 1: `123456789`
   - User 2: `987654321`
   - User 3: `555123456`

2. Update `.env`:
   ```env
   ENABLE_USER_VERIFICATION=true
   ALLOWED_USER_IDS=123456789,987654321,555123456
   ```

3. Restart bot

4. Test: Only these 3 users can access the bot!

## Troubleshooting

### "I enabled verification but now I can't use the bot!"

**Problem:** You didn't add your own user ID.

**Solution:**
1. Disable verification temporarily:
   ```env
   ENABLE_USER_VERIFICATION=false
   ```
2. Restart bot
3. Get your user ID
4. Add it to `ALLOWED_USER_IDS`
5. Re-enable verification

### "User says they got 'Access Denied'"

**Problem:** Their user ID is not in `ALLOWED_USER_IDS`.

**Solution:**
1. Get their user ID
2. Add it to `ALLOWED_USER_IDS` (comma-separated)
3. Restart bot

### "How do I add more users later?"

**Solution:**
1. Get new user's ID
2. Add to `ALLOWED_USER_IDS`:
   ```env
   ALLOWED_USER_IDS=123456789,987654321,555123456,999888777
   ```
3. Restart bot

## Summary

| Setting | Effect |
|---------|--------|
| `ENABLE_USER_VERIFICATION=false` | ✅ Anyone can use bot (public) |
| `ENABLE_USER_VERIFICATION=true` + `ALLOWED_USER_IDS=123,456` | 🔒 Only users 123 and 456 can use bot |
| `ENABLE_USER_VERIFICATION=true` + `ALLOWED_USER_IDS=` | ❌ **NO ONE** can use bot (locked out!) |

**Recommendation:**
- For **personal use**: Enable and add your user ID
- For **public bot**: Leave disabled
- For **team use**: Enable and add all team member IDs
