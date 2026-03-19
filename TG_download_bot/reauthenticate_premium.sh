#!/bin/bash
# Script to re-authenticate with personal account (not bot account)

cd "$(dirname "$0")"

echo "🔧 Re-authenticating MTProto with Personal Account"
echo "=================================================="
echo ""
echo "⚠️  IMPORTANT: You must use your PERSONAL phone number, NOT the bot token!"
echo ""
echo "Current issue: Session is authenticated as bot account (cannot have premium)"
echo "Solution: Re-authenticate with your personal Telegram account"
echo ""

# Stop any running bots
echo "1. Stopping any running bot processes..."
pkill -9 -f "python.*bot.py" 2>/dev/null
sleep 2

# Remove old session
echo "2. Removing old session file..."
rm -f premium_account.session premium_account.session-journal
echo "   ✅ Session files removed"
echo ""

# Activate venv
echo "3. Activating virtual environment..."
source venv/bin/activate

echo ""
echo "4. Starting bot for re-authentication..."
echo "   When prompted:"
echo "   - Enter your PHONE NUMBER (e.g., +1234567890)"
echo "   - NOT the bot token!"
echo "   - Enter verification code from Telegram app"
echo "   - Enter 2FA password if enabled"
echo ""
echo "   Press Ctrl+C after you see 'Bot polling started'"
echo ""
echo "=================================================="
echo ""

# Run bot interactively
python bot.py
