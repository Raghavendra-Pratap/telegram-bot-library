#!/usr/bin/env python3
"""
Test script to start bots and verify they're working
"""
import sys
import time
from bot_launcher import BotLauncher, Colors

def test_bot_startup():
    """Test starting bots and verify they work"""
    launcher = BotLauncher()
    
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}🚀 Testing Bot Startup{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    available_bots = launcher.get_available_bots()
    
    print(f"{Colors.CYAN}Available bots: {len(available_bots)}{Colors.RESET}\n")
    
    # Test starting each bot one by one
    test_results = []
    
    for i, bot in enumerate(available_bots, 1):
        bot_name = bot['name']
        bot_id = bot['id']
        
        print(f"{Colors.BOLD}[{i}/{len(available_bots)}] Testing: {bot_name}{Colors.RESET}")
        
        # Check setup first
        is_ok, message = launcher.check_bot_setup(bot)
        if not is_ok:
            print(f"  {Colors.RED}❌ Setup failed: {message}{Colors.RESET}\n")
            test_results.append({
                'bot': bot_name,
                'status': 'setup_failed',
                'message': message
            })
            continue
        
        # Check dependencies
        deps_ok, missing = launcher.check_bot_dependencies(bot)
        if not deps_ok:
            print(f"  {Colors.YELLOW}⚠️  Missing dependencies: {', '.join(missing[:3])}{Colors.RESET}")
            print(f"  {Colors.CYAN}Installing dependencies...{Colors.RESET}")
            if not launcher.install_bot_dependencies(bot):
                print(f"  {Colors.RED}❌ Failed to install dependencies{Colors.RESET}\n")
                test_results.append({
                    'bot': bot_name,
                    'status': 'deps_failed',
                    'message': 'Failed to install dependencies'
                })
                continue
        
        # Try to start the bot
        print(f"  {Colors.CYAN}Starting bot...{Colors.RESET}")
        bot_process = launcher.start_bot(bot, auto_install=True)
        
        if not bot_process:
            print(f"  {Colors.RED}❌ Failed to start{Colors.RESET}\n")
            test_results.append({
                'bot': bot_name,
                'status': 'start_failed',
                'message': 'Failed to start bot'
            })
            continue
        
        # Wait a bit to see if it stays running
        print(f"  {Colors.CYAN}Waiting 5 seconds to verify bot stays running...{Colors.RESET}")
        time.sleep(5)
        
        # Check if still running
        if bot_process.process.poll() is None:
            print(f"  {Colors.GREEN}✅ Bot started successfully and is running (PID: {bot_process.pid}){Colors.RESET}")
            test_results.append({
                'bot': bot_name,
                'status': 'running',
                'pid': bot_process.pid
            })
        else:
            # Process exited
            stdout, stderr = bot_process.process.communicate()
            error = stderr.decode('utf-8', errors='ignore') or stdout.decode('utf-8', errors='ignore')
            print(f"  {Colors.RED}❌ Bot crashed after startup{Colors.RESET}")
            if error:
                print(f"  {Colors.YELLOW}Error output:{Colors.RESET}")
                print(f"  {error[:300]}...")
            test_results.append({
                'bot': bot_name,
                'status': 'crashed',
                'message': error[:200] if error else 'Unknown error'
            })
        
        # Stop the bot for testing
        print(f"  {Colors.CYAN}Stopping bot for testing...{Colors.RESET}")
        launcher.stop_bot(bot_id)
        print()
        
        # Small delay between tests
        time.sleep(2)
    
    # Summary
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}📊 Test Results Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    running_count = sum(1 for r in test_results if r['status'] == 'running')
    failed_count = len(test_results) - running_count
    
    print(f"Total Tested: {len(test_results)}")
    print(f"{Colors.GREEN}✅ Successfully Started: {running_count}/{len(test_results)}{Colors.RESET}")
    print(f"{Colors.RED if failed_count > 0 else Colors.GREEN}❌ Failed: {failed_count}/{len(test_results)}{Colors.RESET}\n")
    
    if failed_count > 0:
        print(f"{Colors.YELLOW}Failed Bots:{Colors.RESET}")
        for r in test_results:
            if r['status'] != 'running':
                print(f"  - {r['bot']}: {r['status']} - {r.get('message', 'N/A')}")
    
    return test_results

if __name__ == "__main__":
    try:
        results = test_bot_startup()
        # Exit with error code if any bot failed
        all_ok = all(r['status'] == 'running' for r in results)
        sys.exit(0 if all_ok else 1)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
