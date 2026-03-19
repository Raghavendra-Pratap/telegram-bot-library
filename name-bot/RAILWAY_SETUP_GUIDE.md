# Railway Setup Guide - Adding Environment Variables

> ⚠️ **Archived**: This project now runs on a local server only. This Railway guide is kept for reference.  
> Use the local setup instead: **[LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md)**.

This guide will walk you through setting up your Telegram bot on Railway and adding environment variables.

## 📋 Prerequisites

- GitHub account
- Railway account (sign up at [railway.app](https://railway.app))
- Your Telegram bot token (from @BotFather)

---

## 🚀 Step 1: Deploy Your Project to Railway

### 1.1 Sign Up / Log In
1. Go to [railway.app](https://railway.app)
2. Click **"Login"** or **"Start a New Project"**
3. Sign in with your **GitHub account** (recommended)

### 1.2 Create New Project
1. Click **"New Project"** button (top right)
2. Select **"Deploy from GitHub repo"**
3. Authorize Railway to access your GitHub (if first time)
4. Select your repository: `name-bot` (or your repo name)
5. Railway will automatically detect it's a Python project

### 1.3 Initial Deployment
- Railway will start building your project automatically
- Wait for the build to complete (usually 1-2 minutes)
- You'll see build logs in the Railway dashboard

---

## 🔐 Step 2: Add Environment Variables

### Method 1: Using Railway Dashboard (Recommended)

#### Step 2.1: Navigate to Variables Tab
1. In your Railway project dashboard, you'll see your service
2. Click on your **service name** (e.g., "name-bot")
3. Click on the **"Variables"** tab at the top
   - You can also find it in the left sidebar under your service

#### Step 2.2: Add Required Variable (TELEGRAM_BOT_TOKEN)
1. Click **"+ New Variable"** button
2. In the **"Key"** field, enter: `TELEGRAM_BOT_TOKEN`
3. In the **"Value"** field, enter: `your_actual_bot_token_here`
   - Replace `your_actual_bot_token_here` with your real token from @BotFather
   - Example: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`
4. Click **"Add"** button
5. ✅ Your variable is now added!

#### Step 2.3: Add Optional Variables (If Needed)

**User Verification (Optional):**
- **Key:** `ENABLE_USER_VERIFICATION`
- **Value:** `false` (or `true` if you want to restrict access)

**Allowed User IDs (Only if ENABLE_USER_VERIFICATION=true):**
- **Key:** `ALLOWED_USER_IDS`
- **Value:** `123456789,987654321` (comma-separated user IDs)

**Retry Configuration (Optional - uses defaults if not set):**
- **Key:** `RETRY_DELAY`
- **Value:** `2.0`

- **Key:** `MAX_RETRIES`
- **Value:** `5`

**Filename Handling (Optional):**
- **Key:** `SKIP_IF_NO_FILENAME`
- **Value:** `false`

**Rate Limiting (Optional):**
- **Key:** `PROCESSING_DELAY`
- **Value:** `2.0`

- **Key:** `FLOOD_RETRY_DELAY_MULTIPLIER`
- **Value:** `1.5`

#### Step 2.4: Verify Variables
- You should see all your variables listed in the Variables tab
- Each variable shows:
  - **Key** (name)
  - **Value** (hidden for security - shows as dots)
  - **Options** (edit/delete buttons)

---

### Method 2: Using Railway CLI (Advanced)

If you prefer using the command line:

1. **Install Railway CLI:**
   ```bash
   npm i -g @railway/cli
   ```

2. **Login:**
   ```bash
   railway login
   ```

3. **Link to your project:**
   ```bash
   railway link
   ```

4. **Add variables:**
   ```bash
   railway variables set TELEGRAM_BOT_TOKEN=your_token_here
   railway variables set ENABLE_USER_VERIFICATION=false
   railway variables set RETRY_DELAY=2.0
   ```

5. **View all variables:**
   ```bash
   railway variables
   ```

---

## 🔄 Step 3: Redeploy After Adding Variables

### Automatic Redeploy
- Railway **automatically redeploys** when you add/modify environment variables
- You'll see a new deployment starting in the **"Deployments"** tab
- Wait for deployment to complete (usually 30-60 seconds)

### Manual Redeploy (If Needed)
1. Go to **"Deployments"** tab
2. Click **"Redeploy"** button (three dots menu on latest deployment)
3. Select **"Redeploy"**

---

## ✅ Step 4: Verify Your Bot is Running

### 4.1 Check Logs
1. Go to **"Deployments"** tab
2. Click on the latest deployment
3. Click **"View Logs"** or check the **"Logs"** tab
4. Look for:
   - ✅ `Name bot starting...`
   - ✅ `Bot is ready! Add it to your channels/groups...`
   - ❌ Any error messages

### 4.2 Test Your Bot
1. Open Telegram
2. Find your bot (search by username)
3. Send `/start` command
4. Bot should respond with welcome message

### 4.3 Common Issues

**Bot not responding:**
- Check logs for errors
- Verify `TELEGRAM_BOT_TOKEN` is correct
- Ensure token doesn't have extra spaces
- Check if deployment completed successfully

**"TELEGRAM_BOT_TOKEN not set" error:**
- Go back to Variables tab
- Verify variable name is exactly: `TELEGRAM_BOT_TOKEN` (case-sensitive)
- Check for typos
- Redeploy after fixing

---

## 📸 Visual Guide (Step-by-Step)

### Finding the Variables Tab:
```
Railway Dashboard
├── Your Project
    ├── Your Service (name-bot)
        ├── [Overview] ← Default tab
        ├── [Variables] ← Click here!
        ├── [Deployments]
        ├── [Logs]
        └── [Settings]
```

### Adding a Variable:
```
Variables Tab
├── Existing Variables (if any)
└── [+ New Variable] ← Click this button
    ├── Key: TELEGRAM_BOT_TOKEN
    ├── Value: your_token_here
    └── [Add] ← Click to save
```

---

## 🔒 Security Best Practices

1. **Never commit `.env` file to Git** ✅ (You already have this in `.gitignore`)

2. **Never share your bot token publicly**
   - Token gives full control of your bot
   - If exposed, regenerate it immediately via @BotFather

3. **Use Railway's Variables tab** (not hardcoded in code)
   - Variables are encrypted at rest
   - Only visible to you and your team

4. **Regular token rotation** (optional but recommended)
   - Regenerate token every few months
   - Update in Railway Variables tab
   - Redeploy

---

## 📝 Complete Variable List

Here's a complete list of all variables you can set (copy-paste ready):

### Required:
```
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

### Optional (with recommended defaults):
```
ENABLE_USER_VERIFICATION=false
ALLOWED_USER_IDS=
RETRY_DELAY=2.0
MAX_RETRIES=5
SKIP_IF_NO_FILENAME=false
PROCESSING_DELAY=2.0
FLOOD_RETRY_DELAY_MULTIPLIER=1.5
```

**Note:** You only need to add `TELEGRAM_BOT_TOKEN`. All others are optional and will use defaults if not set.

---

## 🎯 Quick Reference: Minimum Setup

**For a quick start, you only need:**

1. Deploy project to Railway
2. Add **ONE** variable:
   - **Key:** `TELEGRAM_BOT_TOKEN`
   - **Value:** Your bot token from @BotFather
3. Wait for redeploy
4. Test with `/start` command

That's it! Your bot should work with default settings.

---

## 🔧 Editing/Deleting Variables

### Edit a Variable:
1. Go to **Variables** tab
2. Click **"Edit"** (pencil icon) next to the variable
3. Update the value
4. Click **"Save"**
5. Railway will automatically redeploy

### Delete a Variable:
1. Go to **Variables** tab
2. Click **"Delete"** (trash icon) next to the variable
3. Confirm deletion
4. Railway will automatically redeploy

---

## 📊 Monitoring Your Bot

### View Logs:
- **Deployments** tab → Click deployment → **View Logs**
- Or use **Logs** tab for real-time logs

### Check Status:
- **Overview** tab shows:
  - Service status (Running/Stopped)
  - Resource usage
  - Recent deployments

### Set Up Alerts (Optional):
- Railway can send email notifications for:
  - Deployment failures
  - Service crashes
  - Resource limits

---

## 🆘 Troubleshooting

### Variable Not Working?
1. ✅ Check variable name is **exactly** correct (case-sensitive)
2. ✅ Check for extra spaces before/after value
3. ✅ Verify deployment completed after adding variable
4. ✅ Check logs for error messages
5. ✅ Try deleting and re-adding the variable

### Bot Keeps Crashing?
1. Check logs for error messages
2. Verify bot token is valid (test with @BotFather)
3. Check Railway resource limits (free tier)
4. Look for Python errors in logs

### Can't Find Variables Tab?
- Make sure you've deployed your project first
- Variables tab appears after first deployment
- Try refreshing the page

---

## 🎉 Success Checklist

- [ ] Project deployed to Railway
- [ ] `TELEGRAM_BOT_TOKEN` variable added
- [ ] Deployment completed successfully
- [ ] Logs show "Bot is ready!"
- [ ] Bot responds to `/start` command
- [ ] Bot works in your channel/group

---

## 📚 Additional Resources

- [Railway Documentation](https://docs.railway.app)
- [Railway Variables Guide](https://docs.railway.app/develop/variables)
- [Railway Discord Community](https://discord.gg/railway)

---

**Need Help?** Check Railway's support or Discord community for assistance!
