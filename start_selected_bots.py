#!/usr/bin/env python3
"""
Start specific bots by ID
"""
import sys
import time
from bot_launcher import BotLauncher, Colors

def start_bots_by_id(bot_ids):
    """Start bots by their IDs"""
    launcher = BotLauncher()
    
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}🚀 Starting Selected Bots{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    available_bots = launcher.get_available_bots()
    bots_to_start = []
    
    # Find bots by ID
    for bot_id in bot_ids:
        bot = next((b for b in available_bots if b['id'] == bot_id), None)
        if bot:
            bots_to_start.append(bot)
        else:
            print(f"{Colors.RED}❌ Bot '{bot_id}' not found{Colors.RESET}")
    
    if not bots_to_start:
        print(f"{Colors.RED}❌ No valid bots to start{Colors.RESET}")
        return False
    
    # Check dependencies first
    print(f"{Colors.CYAN}Checking dependencies...{Colors.RESET}\n")
    launcher.ensure_dependencies(check_bots=bots_to_start, auto_install=True)
    
    # Start each bot
    started_bots = []
    for bot in bots_to_start:
        print(f"\n{Colors.BOLD}Starting: {bot['name']}{Colors.RESET}")
        bot_process = launcher.start_bot(bot, auto_install=True)
        
        if bot_process:
            started_bots.append(bot_process)
            print(f"{Colors.GREEN}✅ {bot['name']} started successfully (PID: {bot_process.pid}){Colors.RESET}")
        else:
            print(f"{Colors.RED}❌ Failed to start {bot['name']}{Colors.RESET}")
        
        time.sleep(1)  # Small delay between starts
    
    # Show status
    print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}📊 Status{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    print(f"{Colors.GREEN}✅ Successfully started: {len(started_bots)}/{len(bots_to_start)} bot(s){Colors.RESET}\n")
    
    if started_bots:
        print(f"{Colors.CYAN}Running bots:{Colors.RESET}")
        for bot_process in started_bots:
            port_info = f" | Port: {bot_process.port}" if bot_process.port else ""
            print(f"  • {bot_process.bot_name} (PID: {bot_process.pid}){port_info}")
        
        print(f"\n{Colors.YELLOW}💡 Tip: Use 'python3 bot_launcher.py' to manage bots interactively{Colors.RESET}")
        print(f"{Colors.YELLOW}💡 Tip: Use 'python3 check_all_bots.py' to check status{Colors.RESET}")
    
    return len(started_bots) == len(bots_to_start)

if __name__ == "__main__":
    # Bot IDs to start: name_bot and download_bot
    bot_ids = ['name_bot', 'download_bot']
    
    try:
        success = start_bots_by_id(bot_ids)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
