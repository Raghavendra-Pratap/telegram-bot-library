# Free Hosting Options for Telegram Bot

> ⚠️ **Archived**: This project now runs on a local server only. This free hosting guide is kept for reference.  
> Use the local setup instead: **[LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md)**.

This guide covers free hosting platforms suitable for your Python Telegram bot without incurring any costs.

## 🎯 Best Free Hosting Options

### 1. **Railway** ⭐ (Recommended)
**Free Tier:**
- $5 credit per month (free tier)
- 500 hours of runtime per month
- Automatic deployments from GitHub
- Environment variables support
- Persistent storage
- **Best for:** Long-running bots with moderate usage

**Setup:**
1. Sign up at [railway.app](https://railway.app) with GitHub
2. Create new project → Deploy from GitHub repo
3. Add environment variables in Railway dashboard
4. Set start command: `python bot.py`
5. Deploy!

**Limitations:**
- Free tier may sleep after inactivity (but wakes up on request)
- 500 hours/month = ~20 days of continuous runtime
- May need to upgrade for 24/7 uptime

---

### 2. **Render**
**Free Tier:**
- 750 hours per month
- Automatic deployments from GitHub
- Environment variables support
- **Best for:** Bots with moderate traffic

**Setup:**
1. Sign up at [render.com](https://render.com)
2. New → Web Service
3. Connect GitHub repo
4. Build command: `pip install -r requirements.txt`
5. Start command: `python bot.py`
6. Add environment variables
7. Deploy!

**Limitations:**
- Free tier sleeps after 15 minutes of inactivity
- Wakes up on first request (may take 30-60 seconds)
- Not ideal for real-time bots (but polling will resume when awake)

---

### 3. **Fly.io**
**Free Tier:**
- 3 shared-cpu-1x VMs (256MB RAM each)
- 3GB persistent volume storage
- Global edge network
- **Best for:** Bots that need to stay awake 24/7

**Setup:**
1. Sign up at [fly.io](https://fly.io)
2. Install flyctl: `curl -L https://fly.io/install.sh | sh`
3. Run: `fly launch` in your project directory
4. Add secrets: `fly secrets set TELEGRAM_BOT_TOKEN=your_token`
5. Deploy: `fly deploy`

**Limitations:**
- More complex setup
- Requires CLI tool
- Free tier has resource limits

---

### 4. **PythonAnywhere**
**Free Tier:**
- Always-on task (one task)
- 512MB disk space
- Python 3.8+
- **Best for:** Simple bots, learning

**Setup:**
1. Sign up at [pythonanywhere.com](https://www.pythonanywhere.com)
2. Upload your files via web interface or Git
3. Create a "Always-on task" in Tasks tab
4. Set command: `python3.8 /home/username/name-bot/bot.py`
5. Add environment variables in Files → .env

**Limitations:**
- Only one always-on task (free tier)
- Limited disk space
- Web interface only (no SSH on free tier)
- Must verify phone number

---

### 5. **Heroku** (Limited Free Tier)
**Note:** Heroku removed free tier in 2022, but Eco Dyno is very cheap ($5/month). Not truly free, but included for reference.

---

### 6. **Replit**
**Free Tier:**
- Always-on option (with limitations)
- Automatic deployments
- **Best for:** Development and testing

**Setup:**
1. Sign up at [replit.com](https://replit.com)
2. Import from GitHub
3. Add environment variables in Secrets tab
4. Enable "Always On" (may require Replit Pro for 24/7)

**Limitations:**
- Free tier may have time limits
- Always-on may require subscription
- Better for development than production

---

### 7. **Koyeb**
**Free Tier:**
- 2 services
- 256MB RAM per service
- Automatic deployments from GitHub
- **Best for:** Simple bots

**Setup:**
1. Sign up at [koyeb.com](https://www.koyeb.com)
2. Create App → GitHub
3. Select your repo
4. Build: `pip install -r requirements.txt`
5. Run: `python bot.py`
6. Add environment variables
7. Deploy!

**Limitations:**
- Free tier may sleep after inactivity
- Limited resources

---

### 8. **Google Cloud Run** (Free Tier)
**Free Tier:**
- 2 million requests per month
- 360,000 GB-seconds compute time
- 180,000 vCPU-seconds
- **Best for:** Bots with variable traffic

**Setup:**
1. Sign up at [cloud.google.com](https://cloud.google.com)
2. Create Cloud Run service
3. Deploy container or use Cloud Build
4. Set environment variables
5. Configure to always run (or use Cloud Scheduler for polling)

**Limitations:**
- More complex setup
- Requires credit card (but free tier won't charge)
- May need to configure for long-running processes

---

### 9. **Oracle Cloud Infrastructure (OCI) Always Free**
**Free Tier:**
- 2 AMD-based Compute VMs (1/8 OCPU, 1GB RAM each)
- Always free, no expiration
- **Best for:** 24/7 bots with full control

**Setup:**
1. Sign up at [oracle.com/cloud](https://www.oracle.com/cloud)
2. Create Always Free VM instance
3. SSH into VM
4. Install Python and dependencies
5. Set up systemd service for auto-start
6. Run bot

**Limitations:**
- Requires credit card verification
- More technical setup (Linux server management)
- Need to manage updates and security

---

### 10. **AWS Free Tier** (EC2 t2.micro)
**Free Tier:**
- 750 hours per month of t2.micro instance (first 12 months)
- **Best for:** Learning AWS, temporary projects

**Setup:**
1. Sign up at [aws.amazon.com](https://aws.amazon.com)
2. Launch EC2 t2.micro instance (Ubuntu)
3. SSH into instance
4. Install Python and dependencies
5. Set up systemd service
6. Run bot

**Limitations:**
- Only free for 12 months
- Requires credit card
- More complex setup
- Need server management knowledge

---

## 🏆 Top Recommendations

### For Beginners:
1. **Railway** - Easiest setup, good free tier
2. **Render** - Simple, GitHub integration
3. **Koyeb** - Straightforward deployment

### For 24/7 Uptime:
1. **Oracle Cloud Always Free** - Truly always free, full control
2. **Fly.io** - Good free tier, stays awake
3. **Railway** - Good balance of ease and reliability

### For Development/Testing:
1. **Replit** - Great for testing
2. **PythonAnywhere** - Simple web interface

---

## 📋 Deployment Checklist

Before deploying, ensure:

- [ ] `.env` file is NOT committed to Git (add to `.gitignore`)
- [ ] All environment variables are set in hosting platform
- [ ] `requirements.txt` is up to date
- [ ] Bot token is valid and active
- [ ] Test bot locally first

---

## 🔧 Platform-Specific Setup

### Railway Setup

1. **Create `Procfile`** (optional, Railway auto-detects):
   ```
   worker: python bot.py
   ```

2. **Or use `railway.json`**:
   ```json
   {
     "$schema": "https://railway.app/railway.schema.json",
     "build": {
       "builder": "NIXPACKS"
     },
     "deploy": {
       "startCommand": "python bot.py",
       "restartPolicyType": "ON_FAILURE",
       "restartPolicyMaxRetries": 10
     }
   }
   ```

### Render Setup

1. **Create `render.yaml`** (optional):
   ```yaml
   services:
     - type: worker
       name: telegram-bot
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: python bot.py
       envVars:
         - key: TELEGRAM_BOT_TOKEN
           sync: false
   ```

### Fly.io Setup

1. **Create `fly.toml`**:
   ```toml
   app = "your-bot-name"
   primary_region = "iad"

   [build]

   [env]
     PYTHONUNBUFFERED = "1"

   [[services]]
     internal_port = 8080
     protocol = "tcp"
   ```

2. **Create `Dockerfile`** (optional, Fly can auto-detect):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["python", "bot.py"]
   ```

---

## ⚠️ Important Considerations

### 1. **Sleeping Services**
Some free tiers (Render, Koyeb) sleep after inactivity. For Telegram bots:
- **Polling bots** (like yours) will resume when service wakes up
- May miss messages during sleep period
- Consider using webhook instead (requires always-on service)

### 2. **Environment Variables**
Never commit `.env` to Git! Always set environment variables in hosting platform dashboard.

### 3. **Logs**
Most platforms provide logs in dashboard. Check regularly for errors.

### 4. **Monitoring**
- Set up uptime monitoring (UptimeRobot, free tier)
- Monitor bot logs for errors
- Check platform usage limits

### 5. **Backup**
- Keep code in GitHub
- Document your environment variables
- Export bot configuration

---

## 🚀 Quick Start: Railway (Recommended)

1. **Prepare your repo:**
   ```bash
   # Ensure .env is in .gitignore
   echo ".env" >> .gitignore
   git add .gitignore
   git commit -m "Add .gitignore"
   git push
   ```

2. **Deploy on Railway:**
   - Go to [railway.app](https://railway.app)
   - Sign up with GitHub
   - New Project → Deploy from GitHub
   - Select your repo
   - Add environment variables:
     - `TELEGRAM_BOT_TOKEN=your_token`
     - (Add other vars from `.env` if needed)
   - Deploy!

3. **Verify:**
   - Check logs in Railway dashboard
   - Test bot with `/start` command
   - Monitor for 24 hours

---

## 📊 Comparison Table

| Platform | Free Tier | Always On | Ease of Setup | Best For |
|----------|-----------|-----------|---------------|----------|
| Railway | $5/month credit | ⚠️ May sleep | ⭐⭐⭐⭐⭐ | Beginners |
| Render | 750 hrs/month | ❌ Sleeps | ⭐⭐⭐⭐ | Simple bots |
| Fly.io | 3 VMs | ✅ Yes | ⭐⭐⭐ | 24/7 bots |
| PythonAnywhere | 1 always-on task | ✅ Yes | ⭐⭐⭐⭐ | Simple bots |
| Koyeb | 2 services | ❌ Sleeps | ⭐⭐⭐⭐ | Quick deploy |
| Oracle Cloud | 2 VMs | ✅ Yes | ⭐⭐ | Advanced users |
| Replit | Limited | ⚠️ Limited | ⭐⭐⭐⭐⭐ | Development |

---

## 💡 Pro Tips

1. **Start with Railway or Render** - Easiest for beginners
2. **Use GitHub** - All platforms support GitHub deployments
3. **Monitor logs** - Check platform dashboard regularly
4. **Set up alerts** - Use free monitoring services
5. **Keep backups** - Document your setup
6. **Test locally first** - Always test before deploying

---

## 🔗 Useful Links

- [Railway Documentation](https://docs.railway.app)
- [Render Documentation](https://render.com/docs)
- [Fly.io Documentation](https://fly.io/docs)
- [PythonAnywhere Help](https://help.pythonanywhere.com)
- [Telegram Bot API](https://core.telegram.org/bots/api)

---

## ❓ Troubleshooting

### Bot not responding after deployment:
1. Check logs in platform dashboard
2. Verify environment variables are set correctly
3. Ensure bot token is valid
4. Check if service is running (not sleeping)

### Service keeps sleeping:
1. Use a platform with always-on free tier (Oracle Cloud, Fly.io)
2. Or upgrade to paid tier
3. Or use a "ping" service to keep it awake (not recommended)

### Deployment fails:
1. Check `requirements.txt` is correct
2. Verify Python version compatibility
3. Check build logs for errors
4. Ensure all files are committed to Git

---

**Good luck with your deployment! 🚀**
