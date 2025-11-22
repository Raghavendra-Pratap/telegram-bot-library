#!/bin/bash

# Setup script for Telegram Video Downloader Bot
# This script should be run from the down_oad_bot directory

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "🎬 Setting up Telegram Video Downloader Bot..."
echo ""

# Check Python version
echo "Checking Python version..."
python3 --version || { echo "❌ Python 3 not found. Please install Python 3.8 or higher."; exit 1; }

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Check FFmpeg
echo "Checking FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "✅ FFmpeg is installed"
    ffmpeg -version | head -n 1
else
    echo "⚠️  FFmpeg not found. Please install FFmpeg:"
    echo "   macOS: brew install ffmpeg"
    echo "   Linux: sudo apt-get install ffmpeg"
    echo "   Windows: Download from https://ffmpeg.org/download.html"
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp env_template.txt .env
    echo "⚠️  Please edit .env and add your TELEGRAM_BOT_TOKEN"
    echo "   Get your token from @BotFather on Telegram"
else
    echo "✅ .env file already exists"
fi

# Create downloads directory
mkdir -p downloads

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your TELEGRAM_BOT_TOKEN"
echo "2. Activate virtual environment: source venv/bin/activate"
echo "3. Run the bot: python bot.py"
echo "   Or use: ./START_BOT.sh"
echo ""

