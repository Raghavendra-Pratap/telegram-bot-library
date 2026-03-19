#!/bin/bash
# Script to setup local file server on WiFi network

cd "$(dirname "$0")"

echo "🌐 Setting up Local File Server"
echo "================================"
echo ""

# Get local IP
if command -v ifconfig >/dev/null 2>&1; then
    LOCAL_IP=$(ifconfig | grep -E "inet " | grep -v 127.0.0.1 | awk '{print $2}' | head -1)
elif command -v ip >/dev/null 2>&1; then
    LOCAL_IP=$(ip addr show | grep -E "inet " | grep -v 127.0.0.1 | awk '{print $2}' | cut -d'/' -f1 | head -1)
else
    echo "❌ Could not detect local IP"
    exit 1
fi

if [ -z "$LOCAL_IP" ]; then
    echo "❌ Could not find local IP address"
    exit 1
fi

echo "✅ Found local IP: $LOCAL_IP"
echo ""

# Get port from .env or use default
if [ -f ".env" ]; then
    PORT=$(grep "FILE_SERVER_PORT" .env | cut -d'=' -f2 | tr -d ' ' || echo "8082")
else
    PORT="8082"
fi

NEW_URL="http://${LOCAL_IP}:${PORT}"

echo "📝 Updating .env file..."
echo "   FILE_SERVER_BASE_URL=$NEW_URL"
echo ""

# Update .env file
if [ -f ".env" ]; then
    # Check if FILE_SERVER_BASE_URL exists
    if grep -q "FILE_SERVER_BASE_URL" .env; then
        # Update existing line
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            sed -i '' "s|FILE_SERVER_BASE_URL=.*|FILE_SERVER_BASE_URL=${NEW_URL}|" .env
        else
            # Linux
            sed -i "s|FILE_SERVER_BASE_URL=.*|FILE_SERVER_BASE_URL=${NEW_URL}|" .env
        fi
        echo "✅ Updated FILE_SERVER_BASE_URL in .env"
    else
        # Add new line
        echo "" >> .env
        echo "# Local network file server URL" >> .env
        echo "FILE_SERVER_BASE_URL=${NEW_URL}" >> .env
        echo "✅ Added FILE_SERVER_BASE_URL to .env"
    fi
else
    echo "❌ .env file not found!"
    echo "   Please create it from env_template.txt first"
    exit 1
fi

echo ""
echo "✅ Configuration updated!"
echo ""
echo "📋 Summary:"
echo "   Local IP: $LOCAL_IP"
echo "   Port: $PORT"
echo "   File Server URL: $NEW_URL"
echo ""
echo "🔧 Next steps:"
echo "   1. Make sure your firewall allows connections on port $PORT"
echo "   2. Restart the bot for changes to take effect"
echo "   3. Devices on the same WiFi can now access download links!"
echo ""
echo "⚠️  Note: This URL only works on your local network (same WiFi)"
echo "   For public access, use a public IP or domain name"
