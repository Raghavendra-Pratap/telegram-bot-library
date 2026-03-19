# Railway Wake-Up Setup Guide

> ⚠️ **Archived**: This project now runs on a local server only. This Railway guide is kept for reference.  
> Use the local setup instead: **[LOCAL_SERVER_GUIDE.md](./LOCAL_SERVER_GUIDE.md)**.

> ⚠️ **IMPORTANT**: If your bot still sleeps on Railway, see **[RAILWAY_ALWAYS_ON_SETUP.md](./RAILWAY_ALWAYS_ON_SETUP.md)** for the complete solution using external ping services.

This guide explains how to configure Railway to automatically wake up your bot when files are uploaded.

## 🔧 The Problem

When the bot shuts down after idle timeout (or Railway puts it to sleep), Railway doesn't automatically restart it when Telegram messages arrive because:
1. The bot process is stopped and can't receive updates
2. Railway's free tier may sleep services after inactivity
3. When sleeping, the service can't receive HTTP requests or Telegram updates

## ✅ The Solution

The bot now includes an HTTP health check server that helps keep it alive. There are two approaches:

### Approach 1: Keep Bot Always Running (Recommended)

1. **Disable auto-shutdown** when HTTP server is enabled (default behavior)
2. **Configure Railway health checks** to ping the HTTP endpoint
3. **Railway keeps service alive** when health checks pass
4. **Bot stays running** and can receive Telegram updates

### Approach 2: External Ping Service

If Railway still sleeps, use an external service to ping the health check endpoint every few minutes to keep the bot awake.

## 🚀 Setup Steps

### 1. Enable HTTP Server (Already Done)

The bot is configured with HTTP server enabled by default. Check your `.env` file:

```env
ENABLE_HTTP_SERVER=true
HTTP_SERVER_PORT=8080
```

### 2. Configure Railway Health Checks

Railway needs to be configured to ping the health check endpoint. Here's how:

#### Option A: Railway Auto Health Checks (Recommended)

1. Go to your Railway project dashboard
2. Select your service
3. Go to **Settings** → **Health Checks**
4. Enable **Health Check Path**
5. Set the path to: `/` (root path)
6. Set the port to: `8080` (or your configured `HTTP_SERVER_PORT`)
7. Railway will automatically ping this endpoint to keep your service alive

#### Option B: External Ping Service (If Railway Sleeps)

If Railway's free tier still puts your service to sleep, use an external service to keep it awake:

1. **Get your Railway service URL:**
   - Railway Dashboard → Your Service → Settings → Domains
   - Copy the public URL (e.g., `https://your-bot.up.railway.app`)

2. **Set up UptimeRobot** (free):
   - Sign up at [uptimerobot.com](https://uptimerobot.com)
   - Add new monitor:
     - **Monitor Type**: HTTP(s)
     - **URL**: `https://your-bot.up.railway.app:8080/` (or your Railway URL)
     - **Monitoring Interval**: 5 minutes
   - This will ping your bot every 5 minutes to keep it awake

3. **Alternative: Use cron-job.org** (free):
   - Sign up at [cron-job.org](https://cron-job.org)
   - Create a new cron job:
     - **URL**: `https://your-bot.up.railway.app:8080/`
     - **Schedule**: Every 5 minutes
   - This will ping your bot regularly

**Note:** Each ping resets the activity timer, so the bot stays alive and can receive Telegram updates.

### 3. Configure Railway Port

Make sure Railway exposes port 8080:

1. Go to your Railway service settings
2. Under **Networking**, add a new port:
   - **Port**: `8080`
   - **Protocol**: `TCP`
   - **Public**: `Yes` (if you want external access)

### 4. Verify It's Working

1. Check bot logs - you should see:
   ```
   🌐 HTTP health check server started on port 8080
   Health check URL: http://0.0.0.0:8080/
   ```

2. Test the health check endpoint:
   ```bash
   curl http://your-railway-url:8080/
   ```
   
   You should get a JSON response:
   ```json
   {"status": "ok", "bot": "running", "timestamp": "..."}
   ```

3. Check logs when Railway pings it - you should see:
   ```
   Health check received - activity timer reset
   ```

## 📋 How It Works

1. **Bot starts** → HTTP server starts on port 8080
2. **Railway pings** → Health check endpoint receives request
3. **Activity reset** → Timer resets, bot stays alive
4. **File uploaded** → Bot receives Telegram update and processes it
5. **Idle timeout** → If no activity for 12 minutes, bot logs warning but stays running (because HTTP server is active)

## ⚙️ Configuration Options

### Disable HTTP Server (Not Recommended)

If you want to disable the HTTP server:

```env
ENABLE_HTTP_SERVER=false
```

**Note:** Without HTTP server, the bot will shut down completely after idle timeout and won't wake up automatically.

### Change Port

If port 8080 is already in use:

```env
HTTP_SERVER_PORT=3000
```

Then update Railway to use port 3000 instead.

### Adjust Idle Timeout

```env
IDLE_TIMEOUT_MINUTES=15
```

## 🔍 Troubleshooting

### Bot Still Shuts Down

1. **Check HTTP server is running:**
   - Look for log message: `HTTP health check server started on port 8080`
   - If not present, check `ENABLE_HTTP_SERVER=true` in `.env`

2. **Check Railway health checks:**
   - Go to Railway dashboard → Service → Settings → Health Checks
   - Verify health check path is set to `/` and port is `8080`

3. **Check port is exposed:**
   - Railway → Service → Settings → Networking
   - Verify port 8080 is added and public

### Health Check Not Responding

1. **Check bot logs** for errors
2. **Test manually:**
   ```bash
   curl http://localhost:8080/
   ```
3. **Verify port** matches `HTTP_SERVER_PORT` in `.env`

### Railway Can't Ping Health Check

1. **Check Railway service URL** is correct
2. **Verify port** is publicly accessible
3. **Check firewall/network** settings in Railway

## 💡 Best Practices

1. **Keep HTTP server enabled** - This is the recommended setup for Railway
2. **Set Railway health checks** - Automatically keeps bot alive
3. **Monitor logs** - Check that health checks are being received
4. **Test after deployment** - Verify health check endpoint responds

## 🎯 Summary

With HTTP server enabled and Railway health checks configured:
- ✅ Bot stays alive when Railway pings health check
- ✅ Activity timer resets on each health check
- ✅ Bot can receive Telegram updates continuously
- ✅ No manual restart needed
- ✅ Works automatically with Railway's infrastructure

---

**Need help?** Check the bot logs or Railway dashboard for more information.
