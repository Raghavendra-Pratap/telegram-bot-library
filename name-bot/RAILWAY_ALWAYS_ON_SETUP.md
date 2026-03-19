# Railway Always-On Setup (Fix Auto-Restart Issue)

> ⚠️ **Archived**: This project now runs on a local server only. This Railway guide is kept for reference.  
> Use the local setup instead: **[LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md)**.

## 🔴 The Problem

Railway's free tier **puts services to sleep** after inactivity, even with health checks. When the service sleeps:
- ❌ Bot can't receive Telegram updates
- ❌ HTTP health checks don't wake it up
- ❌ Manual restart required

## ✅ The Solution: External Ping Service

Use a **free external service** to ping your bot every few minutes. This keeps Railway from sleeping your service.

---

## 🚀 Quick Setup (5 Minutes)

### Step 1: Get Your Railway URL

1. Go to Railway Dashboard → Your Service
2. Click **Settings** → **Networking**
3. Copy your **public URL** (e.g., `https://your-bot.up.railway.app`)
4. Or create a custom domain if you have one

### Step 2: Set Up UptimeRobot (Free)

1. **Sign up** at [uptimerobot.com](https://uptimerobot.com) (free)
2. Click **Add New Monitor**
3. Configure:
   - **Monitor Type**: `HTTP(s)`
   - **Friendly Name**: `Railway Bot Health Check`
   - **URL**: `https://your-railway-url.up.railway.app:8080/`
     - Replace `your-railway-url` with your actual Railway URL
     - Port `8080` is the default health check port
   - **Monitoring Interval**: `5 minutes` (recommended)
   - **Alert Contacts**: (Optional) Add your email
4. Click **Create Monitor**

### Step 3: Verify It Works

1. Wait 5-10 minutes
2. Check Railway logs - you should see:
   ```
   Health check received - activity timer reset
   ```
3. Check UptimeRobot dashboard - monitor should show "UP"

**That's it!** Your bot will now stay awake and automatically restart when needed.

---

## 🔄 Alternative: cron-job.org

If you prefer cron-job.org:

1. **Sign up** at [cron-job.org](https://cron-job.org) (free)
2. Click **Create cronjob**
3. Configure:
   - **Title**: `Railway Bot Health Check`
   - **Address**: `https://your-railway-url.up.railway.app:8080/`
   - **Schedule**: `Every 5 minutes`
4. Click **Create**

---

## 📋 How It Works

```
Every 5 minutes:
  UptimeRobot → Pings Railway URL → HTTP Server responds
  → Activity timer resets → Bot stays alive
  → Railway keeps service running → Bot receives Telegram updates
```

### Timeline:

```
10:00 AM - UptimeRobot pings → Bot stays awake
10:05 AM - UptimeRobot pings → Bot stays awake
10:10 AM - User uploads file → Bot processes it ✅
10:15 AM - UptimeRobot pings → Bot stays awake
... (continues every 5 minutes)
```

---

## ⚙️ Configuration

### Check Your Bot Settings

Make sure in Railway environment variables:

```env
ENABLE_HTTP_SERVER=true
HTTP_SERVER_PORT=8080
ENABLE_AUTO_SHUTDOWN=true
IDLE_TIMEOUT_MINUTES=12
```

### Port Configuration

1. **Railway Dashboard** → Your Service → **Settings** → **Networking**
2. Make sure port **8080** is exposed:
   - Click **Generate Domain** (if not done)
   - Or add custom domain
3. The health check URL should be accessible

---

## 🔍 Troubleshooting

### Bot Still Sleeps

**Problem**: Railway still puts service to sleep

**Solutions**:
1. **Check UptimeRobot is pinging**:
   - Go to UptimeRobot dashboard
   - Check monitor status (should be "UP")
   - Check last check time (should be recent)

2. **Verify URL is correct**:
   - Test manually: `curl https://your-railway-url.up.railway.app:8080/`
   - Should return JSON: `{"status": "ok", ...}`

3. **Check Railway logs**:
   - Look for "Health check received" messages
   - Should appear every 5 minutes

4. **Reduce ping interval**:
   - Change UptimeRobot to ping every **3 minutes** instead of 5
   - More frequent pings = less chance of sleep

### Health Check Not Responding

**Problem**: HTTP server not responding

**Solutions**:
1. **Check bot is running**:
   - Railway Dashboard → Logs
   - Should see: `HTTP health check server started on port 8080`

2. **Check port configuration**:
   - Railway → Settings → Networking
   - Verify port 8080 is exposed

3. **Check environment variables**:
   - Railway → Variables
   - Verify `ENABLE_HTTP_SERVER=true`
   - Verify `HTTP_SERVER_PORT=8080`

### Railway URL Not Working

**Problem**: Can't access Railway URL

**Solutions**:
1. **Generate Railway domain**:
   - Railway Dashboard → Settings → Networking
   - Click **Generate Domain**

2. **Check URL format**:
   - Should be: `https://your-service.up.railway.app`
   - Not: `http://localhost` or internal IP

3. **Test from browser**:
   - Open: `https://your-railway-url.up.railway.app:8080/`
   - Should see JSON response

---

## 💡 Best Practices

### 1. Ping Interval

- **Recommended**: 5 minutes
- **More frequent** (3 min): More reliable, but more requests
- **Less frequent** (10 min): May allow Railway to sleep

### 2. Multiple Monitors

Set up **2 monitors** for redundancy:
- UptimeRobot: Every 5 minutes
- cron-job.org: Every 5 minutes (offset by 2-3 minutes)

### 3. Monitor Status

- Check UptimeRobot dashboard weekly
- Ensure monitor is "UP" and pinging regularly
- Set up email alerts for downtime

### 4. Railway Settings

- Keep `ENABLE_HTTP_SERVER=true`
- Keep `ENABLE_AUTO_SHUTDOWN=true` (bot won't actually shut down with HTTP server)
- Set reasonable `IDLE_TIMEOUT_MINUTES=12`

---

## 🎯 Expected Behavior

### With UptimeRobot Setup:

✅ **Bot stays awake** - No sleep, always running
✅ **Receives updates** - Processes files immediately
✅ **Auto-restarts** - Railway keeps it running
✅ **No manual intervention** - Fully automatic

### Logs You Should See:

```
🌐 HTTP health check server started on port 8080
Health check URL: http://0.0.0.0:8080/
Health check received - activity timer reset  (every 5 minutes)
```

---

## 📊 Monitoring

### UptimeRobot Dashboard

- **Status**: Should always be "UP"
- **Uptime**: Should be 99%+
- **Response Time**: Usually < 1 second
- **Last Check**: Should be recent (within 5 minutes)

### Railway Logs

- **Health checks**: Should appear every 5 minutes
- **Activity resets**: Should see "activity timer reset"
- **No shutdown messages**: Bot should never shut down

---

## 🚨 Important Notes

1. **Free Tier Limits**:
   - UptimeRobot free: 50 monitors, 5-minute intervals
   - cron-job.org free: Unlimited jobs, 5-minute intervals
   - Both are sufficient for this use case

2. **Railway Free Tier**:
   - $5 credit/month
   - 500 hours runtime
   - Services may sleep, but ping service prevents it

3. **Cost**:
   - ✅ UptimeRobot: **Free**
   - ✅ cron-job.org: **Free**
   - ✅ Railway: **Free tier available**

---

## ✅ Verification Checklist

- [ ] Railway URL is accessible
- [ ] HTTP server is running (check logs)
- [ ] UptimeRobot monitor is "UP"
- [ ] Health checks appear in logs every 5 minutes
- [ ] Bot processes files immediately
- [ ] No manual restart needed

---

## 🎉 Result

After setup:
- ✅ Bot **never sleeps**
- ✅ Bot **receives updates immediately**
- ✅ Bot **auto-restarts** when Railway restarts
- ✅ **Zero manual intervention** needed
- ✅ **100% automatic** operation

**Your bot will now work reliably on Railway! 🚀**

---

## 📞 Need Help?

1. **Check Railway logs** for errors
2. **Check UptimeRobot** monitor status
3. **Test health check URL** manually
4. **Verify environment variables** in Railway

**The external ping service is the key to keeping Railway services awake!**
