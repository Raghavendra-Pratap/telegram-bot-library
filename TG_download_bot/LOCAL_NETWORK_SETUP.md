# Local Network File Server Setup

## Overview

Your file server is already running and accessible on your local network! You just need to configure the bot to use your local IP address instead of `localhost`.

## Quick Setup

### Option 1: Automatic Setup (Recommended)

Run the setup script:

```bash
cd TG_download_bot
./setup_local_server.sh
```

This will:
- ✅ Detect your local IP address
- ✅ Update `.env` file automatically
- ✅ Configure the file server URL

Then restart your bot!

### Option 2: Manual Setup

1. **Find your local IP:**
   ```bash
   ./get_local_ip.sh
   ```
   Or manually:
   - macOS/Linux: `ifconfig | grep inet`
   - Windows: `ipconfig | findstr IPv4`

2. **Update `.env` file:**
   ```env
   FILE_SERVER_BASE_URL=http://192.168.1.10:8082
   ```
   (Replace `192.168.1.10` with your actual local IP)

3. **Restart the bot**

## How It Works

### Current Setup

- **File Server**: Running on `0.0.0.0:8082` (accessible on all network interfaces)
- **Bot Configuration**: Needs to know the public URL for download links

### What Changes

**Before:**
```env
FILE_SERVER_BASE_URL=http://localhost:8082
```
- ❌ Only works on same computer
- ❌ Telegram rejects localhost URLs in buttons

**After:**
```env
FILE_SERVER_BASE_URL=http://192.168.1.10:8082
```
- ✅ Works on same WiFi network
- ✅ Telegram accepts the URL
- ✅ Clickable download buttons work!

## Network Access

### Same WiFi Network

Once configured, any device on your WiFi network can:
- ✅ Access download links
- ✅ Download files directly
- ✅ Use clickable buttons in Telegram

### Example URLs

After setup, download links will look like:
```
http://192.168.1.10:8082/download/abc123...
```

This works from:
- ✅ Your phone (same WiFi)
- ✅ Other computers (same WiFi)
- ✅ Tablets (same WiFi)
- ❌ Not from outside your network (need public IP/domain)

## Firewall Configuration

### macOS

The file server should work by default. If blocked:

1. **System Settings** → **Network** → **Firewall**
2. Allow incoming connections for Python
3. Or add port exception:
   ```bash
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add /usr/bin/python3
   ```

### Linux

```bash
# Ubuntu/Debian
sudo ufw allow 8082

# Or iptables
sudo iptables -A INPUT -p tcp --dport 8082 -j ACCEPT
```

### Windows

1. **Windows Defender Firewall** → **Advanced Settings**
2. **Inbound Rules** → **New Rule**
3. Allow port `8082` for TCP

## Testing

### 1. Test from Same Computer

```bash
curl http://192.168.1.10:8082/health
```

Should return: `OK`

### 2. Test from Phone (Same WiFi)

1. Open browser on phone
2. Go to: `http://192.168.1.10:8082/health`
3. Should see: `OK`

### 3. Test Download Link

1. Download a file via bot
2. Click the download link button
3. Should download the file!

## Troubleshooting

### "Connection refused" from phone

**Problem:** Firewall blocking or wrong IP

**Solution:**
1. Check firewall settings (see above)
2. Verify IP address: `./get_local_ip.sh`
3. Make sure phone is on same WiFi

### "Link not found or expired"

**Problem:** File server not running or wrong URL

**Solution:**
1. Check bot logs for "File server started"
2. Verify `FILE_SERVER_BASE_URL` in `.env`
3. Restart bot

### "Still shows localhost"

**Problem:** Bot not restarted after config change

**Solution:**
1. Stop bot (Ctrl+C or kill process)
2. Restart bot
3. Check `/status` command

## Advanced: Public Access

For access from outside your network:

### Option 1: Port Forwarding

1. Configure router port forwarding (8082 → your computer IP)
2. Use your public IP: `http://YOUR_PUBLIC_IP:8082`
3. Update `.env`:
   ```env
   FILE_SERVER_BASE_URL=http://YOUR_PUBLIC_IP:8082
   ```

### Option 2: Domain Name

1. Get a domain name
2. Point it to your public IP
3. Use HTTPS (recommended):
   ```env
   FILE_SERVER_BASE_URL=https://yourdomain.com
   ```

### Option 3: Tunneling (ngrok, Cloudflare Tunnel)

For quick testing:
```bash
# Using ngrok
ngrok http 8082

# Use the provided URL in .env
FILE_SERVER_BASE_URL=https://abc123.ngrok.io
```

## Summary

✅ **File server is already running** on your network
✅ **Just update the URL** in `.env` to your local IP
✅ **Restart bot** and it works!

The server uses your system's memory and network interface - no additional setup needed!
