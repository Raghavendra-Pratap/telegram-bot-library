# 🚀 How to Launch Your Bot on Railway - Step by Step

> ⚠️ **Archived**: This project now runs on a local server only. This Railway guide is kept for reference.  
> Use the local setup instead: **[LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md)**.

A simple, visual guide to deploy your Telegram bot on Railway in minutes.

---

## 📋 Before You Start

Make sure you have:
- ✅ Your code pushed to GitHub (if not, see Step 0 below)
- ✅ A Railway account (free signup at [railway.app](https://railway.app))
- ✅ Your Telegram bot token from @BotFather

---

## Step 0: Push Your Code to GitHub (If Not Already Done)

If your code isn't on GitHub yet:

1. **Create a GitHub repository:**
   ```bash
   # In your project directory
   git init
   git add .
   git commit -m "Initial commit"
   ```

2. **Create repo on GitHub:**
   - Go to [github.com](https://github.com)
   - Click "+" → "New repository"
   - Name it: `name-bot` (or any name)
   - Click "Create repository"

3. **Push your code:**
   ```bash
   git remote add origin https://github.com/YOUR_USERNAME/name-bot.git
   git branch -M main
   git push -u origin main
   ```

**Skip this step if your code is already on GitHub!**

---

## Step 1: Sign Up / Log In to Railway

1. Go to **[railway.app](https://railway.app)**
2. Click **"Start a New Project"** or **"Login"**
3. Choose **"Login with GitHub"** (recommended)
   - This connects Railway to your GitHub account
   - Authorize Railway when prompted

---

## Step 2: Create a New Project

1. After logging in, you'll see the Railway dashboard
2. Click the **"+ New Project"** button (top right, green button)
3. Select **"Deploy from GitHub repo"**
   - If first time, you'll need to authorize Railway to access your GitHub repos
   - Click "Authorize Railway" and approve

---

## Step 3: Select Your Repository

1. Railway will show a list of your GitHub repositories
2. Find and click on **`name-bot`** (or whatever you named your repo)
3. Railway will automatically:
   - Detect it's a Python project
   - Start setting up the deployment
   - Show you the project dashboard

---

## Step 4: Wait for Initial Build

Railway will automatically:
- ✅ Detect Python
- ✅ Install dependencies from `requirements.txt`
- ✅ Build your project
- ⏳ This takes 1-2 minutes

**Watch the build logs:**
- Click on your service name (e.g., "name-bot")
- Go to **"Deployments"** tab
- You'll see build progress in real-time

**What to look for:**
- ✅ `Installing dependencies...`
- ✅ `Building...`
- ✅ `Build completed successfully`

---

## Step 5: Add Your Bot Token (Environment Variable)

**This is the most important step!**

1. In your Railway project, click on your **service name** (e.g., "name-bot")
2. Click on the **"Variables"** tab (top menu)
3. Click **"+ New Variable"** button
4. Fill in:
   - **Key:** `TELEGRAM_BOT_TOKEN`
   - **Value:** `your_actual_bot_token_here`
     - Get this from @BotFather on Telegram
     - Example format: `1234567890:ABCdefGHIjklMNOpqrsTUVwxyz`
5. Click **"Add"**

**Railway will automatically redeploy after adding the variable!**

---

## Step 6: Configure Start Command (If Needed)

Railway usually auto-detects, but verify:

1. Click on your service
2. Go to **"Settings"** tab
3. Scroll to **"Start Command"**
4. Should be: `python bot.py`
   - If empty or wrong, set it to: `python bot.py`
5. Save if you changed it

---

## Step 7: Verify Deployment

### Check Logs:
1. Go to **"Deployments"** tab
2. Click on the latest deployment
3. Click **"View Logs"** or check **"Logs"** tab
4. Look for:
   ```
   Name bot starting...
   Bot is ready! Add it to your channels/groups as admin with 'Edit messages' permission.
   ```

### Test Your Bot:
1. Open Telegram
2. Search for your bot (by username)
3. Send `/start` command
4. Bot should respond with welcome message! ✅

---

## ✅ Success Checklist

- [ ] Code pushed to GitHub
- [ ] Railway account created
- [ ] Project deployed from GitHub
- [ ] Build completed successfully
- [ ] `TELEGRAM_BOT_TOKEN` variable added
- [ ] Deployment completed after adding variable
- [ ] Logs show "Bot is ready!"
- [ ] Bot responds to `/start` command

---

## 🎯 Visual Step-by-Step

```
1. Railway Dashboard
   └── [+ New Project] ← Click here
       └── [Deploy from GitHub repo]
           └── Select: name-bot
               └── Railway builds automatically
                   └── [Variables Tab] ← Add TELEGRAM_BOT_TOKEN
                       └── Bot redeploys automatically
                           └── ✅ Bot is running!
```

---

## 🔧 Troubleshooting

### Build Fails?
- **Check `requirements.txt` exists** and has correct packages
- **Check Python version** - Railway uses Python 3.11+ by default
- **Check logs** for specific error messages

### Bot Not Responding?
1. **Check logs** - Look for errors
2. **Verify token** - Make sure `TELEGRAM_BOT_TOKEN` is correct
3. **Check variable name** - Must be exactly `TELEGRAM_BOT_TOKEN` (case-sensitive)
4. **Redeploy** - Go to Deployments → Click three dots → Redeploy

### "TELEGRAM_BOT_TOKEN not set" Error?
- Go to **Variables** tab
- Verify variable name is exactly: `TELEGRAM_BOT_TOKEN`
- Check for typos or extra spaces
- Redeploy after fixing

### Service Keeps Crashing?
- Check logs for Python errors
- Verify bot token is valid (test with @BotFather)
- Check Railway resource limits (free tier)

---

## 📱 Quick Reference: Railway Dashboard Navigation

```
Railway Dashboard
├── Projects
    └── Your Project (name-bot)
        └── Services
            └── name-bot (your service)
                ├── [Overview] - Service status, metrics
                ├── [Variables] - Environment variables ← Add token here!
                ├── [Deployments] - Build history, logs
                ├── [Logs] - Real-time logs
                └── [Settings] - Service configuration
```

---

## 🎉 You're Done!

Your bot is now running on Railway! It will:
- ✅ Stay online 24/7 (on free tier, may sleep after inactivity but wakes up)
- ✅ Automatically restart if it crashes
- ✅ Update automatically when you push to GitHub (if auto-deploy enabled)

---

## 🔄 Updating Your Bot

When you make changes:

1. **Push to GitHub:**
   ```bash
   git add .
   git commit -m "Update bot"
   git push
   ```

2. **Railway auto-deploys:**
   - Railway detects the push
   - Automatically rebuilds and redeploys
   - Your bot updates! ✨

---

## 💡 Pro Tips

1. **Monitor Logs Regularly:**
   - Check logs weekly for errors
   - Railway dashboard → Logs tab

2. **Set Up Notifications:**
   - Railway can email you on deployment failures
   - Settings → Notifications

3. **Use Railway CLI (Optional):**
   ```bash
   npm i -g @railway/cli
   railway login
   railway link
   railway logs  # View logs from terminal
   ```

4. **Keep Your Token Secret:**
   - Never commit `.env` to GitHub ✅ (you already have this in `.gitignore`)
   - Only add variables in Railway dashboard

---

## 📚 Need More Help?

- **Railway Docs:** [docs.railway.app](https://docs.railway.app)
- **Railway Discord:** [discord.gg/railway](https://discord.gg/railway)
- **Check your bot logs** for specific error messages

---

**That's it! Your bot should now be live on Railway! 🚀**
