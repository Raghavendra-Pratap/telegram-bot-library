#!/bin/bash
# Script to get local IP address for file server

echo "🔍 Finding your local IP address..."
echo ""

# Try different methods to get local IP
if command -v ifconfig >/dev/null 2>&1; then
    # macOS/Linux
    LOCAL_IP=$(ifconfig | grep -E "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
elif command -v ip >/dev/null 2>&1; then
    # Linux (ip command)
    LOCAL_IP=$(ip addr show | grep -E "inet " | grep -v 127.0.0.1 | awk '{print $2}' | cut -d'/' -f1 | head -1)
elif command -v ipconfig >/dev/null 2>&1; then
    # Windows (in Git Bash or WSL)
    LOCAL_IP=$(ipconfig | grep -i "IPv4" | awk '{print $NF}' | head -1)
else
    echo "❌ Could not find network tools"
    exit 1
fi

if [ -z "$LOCAL_IP" ]; then
    echo "❌ Could not detect local IP address"
    echo ""
    echo "Please find it manually:"
    echo "  - macOS/Linux: ifconfig | grep inet"
    echo "  - Windows: ipconfig | findstr IPv4"
    exit 1
fi

echo "✅ Found local IP: $LOCAL_IP"
echo ""
echo "📝 Update your .env file:"
echo "   FILE_SERVER_BASE_URL=http://$LOCAL_IP:8082"
echo ""
echo "Then restart the bot for changes to take effect."
