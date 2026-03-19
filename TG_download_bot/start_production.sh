#!/bin/bash
# Production-ready startup script for TG_download_bot
# Handles process management, cleanup, and ensures only one instance runs

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

BOT_NAME="TG_download_bot"
PID_FILE="${SCRIPT_DIR}/.${BOT_NAME}.pid"
LOG_FILE="${SCRIPT_DIR}/bot.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to check if bot is running
is_running() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            return 0  # Running
        else
            # Stale PID file
            rm -f "$PID_FILE"
            return 1  # Not running
        fi
    fi
    return 1  # Not running
}

# Function to stop existing bot instances
stop_bot() {
    print_info "Stopping existing bot instances..."
    
    # Kill by PID file
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            print_info "Stopping bot process (PID: $PID)..."
            kill -TERM "$PID" 2>/dev/null || true
            sleep 2
            # Force kill if still running
            if ps -p "$PID" > /dev/null 2>&1; then
                print_warn "Force killing bot process (PID: $PID)..."
                kill -9 "$PID" 2>/dev/null || true
            fi
        fi
        rm -f "$PID_FILE"
    fi
    
    # Kill any other instances
    print_info "Cleaning up any other bot processes..."
    pkill -9 -f "python.*TG_download_bot.*bot.py" 2>/dev/null || true
    pkill -9 -f "python.*${SCRIPT_DIR}.*bot.py" 2>/dev/null || true
    
    # Wait for processes to fully terminate
    sleep 3
    
    # Clean up stale session files
    print_info "Cleaning up stale session files..."
    rm -f "${SCRIPT_DIR}/premium_account.session-journal" 2>/dev/null || true
    rm -f "${SCRIPT_DIR}/premium_account.session-wal" 2>/dev/null || true
    rm -f "${SCRIPT_DIR}/premium_account.session-shm" 2>/dev/null || true
    
    print_info "Cleanup complete"
}

# Function to start the bot
start_bot() {
    # Check if already running
    if is_running; then
        print_warn "Bot is already running (PID: $(cat "$PID_FILE"))"
        print_info "Use './start_production.sh stop' to stop it first"
        exit 1
    fi
    
    # Check for virtual environment
    if [ ! -d "venv" ]; then
        print_error "Virtual environment not found!"
        print_info "Please create it first: python3 -m venv venv"
        exit 1
    fi
    
    # Activate virtual environment
    source venv/bin/activate
    
    # Check for .env file
    if [ ! -f ".env" ]; then
        print_error ".env file not found!"
        print_info "Please create .env file from env_template.txt"
        exit 1
    fi
    
    # Stop any existing instances
    stop_bot
    
    print_info "Starting ${BOT_NAME}..."
    print_info "Logs will be written to: $LOG_FILE"
    
    # Start bot in background
    nohup python bot.py > "$LOG_FILE" 2>&1 &
    BOT_PID=$!
    
    # Save PID
    echo "$BOT_PID" > "$PID_FILE"
    
    print_info "Bot started with PID: $BOT_PID"
    print_info "Waiting for bot to initialize..."
    
    # Wait a bit and check if it's still running
    sleep 5
    
    if ! ps -p "$BOT_PID" > /dev/null 2>&1; then
        print_error "Bot process died immediately!"
        print_info "Check logs: tail -50 $LOG_FILE"
        rm -f "$PID_FILE"
        exit 1
    fi
    
    print_info "✅ Bot is running!"
    print_info "   PID: $BOT_PID"
    print_info "   Logs: tail -f $LOG_FILE"
    print_info "   Stop: ./start_production.sh stop"
}

# Function to stop the bot
stop_bot_clean() {
    if ! is_running; then
        print_warn "Bot is not running"
        exit 0
    fi
    
    stop_bot
    print_info "✅ Bot stopped"
}

# Function to restart the bot
restart_bot() {
    print_info "Restarting bot..."
    stop_bot_clean
    sleep 2
    start_bot
}

# Function to show status
show_status() {
    if is_running; then
        PID=$(cat "$PID_FILE")
        print_info "Bot is running (PID: $PID)"
        print_info "Logs: tail -f $LOG_FILE"
    else
        print_warn "Bot is not running"
    fi
}

# Main script logic
case "${1:-start}" in
    start)
        start_bot
        ;;
    stop)
        stop_bot_clean
        ;;
    restart)
        restart_bot
        ;;
    status)
        show_status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
