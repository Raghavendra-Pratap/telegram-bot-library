#!/usr/bin/env python3
"""
Non-interactive script to check all bots and their status
"""
import sys
from bot_launcher import BotLauncher, Colors

def check_all_bots():
    """Check all bots and their status"""
    launcher = BotLauncher()
    
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}🤖 Bot Launcher - Status Check{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    # Get available bots
    available_bots = launcher.get_available_bots()
    
    print(f"{Colors.CYAN}Found {len(available_bots)} bot(s) in configuration:{Colors.RESET}\n")
    
    # Check each bot
    results = []
    for bot in available_bots:
        bot_id = bot['id']
        bot_name = bot['name']
        
        print(f"{Colors.BOLD}Checking: {bot_name}{Colors.RESET}")
        print(f"  Directory: {bot['directory']}")
        
        # Check setup
        is_ok, message = launcher.check_bot_setup(bot)
        if not is_ok:
            print(f"  {Colors.RED}❌ Setup Check: {message}{Colors.RESET}")
            results.append({
                'bot': bot_name,
                'setup_ok': False,
                'setup_message': message,
                'dependencies_ok': False,
                'running': False
            })
            print()
            continue
        
        print(f"  {Colors.GREEN}✅ Setup: OK{Colors.RESET}")
        
        # Check dependencies
        deps_ok, missing_deps = launcher.check_bot_dependencies(bot)
        if not deps_ok:
            print(f"  {Colors.YELLOW}⚠️  Dependencies: Missing {len(missing_deps)} package(s){Colors.RESET}")
            print(f"     Missing: {', '.join(missing_deps[:5])}{'...' if len(missing_deps) > 5 else ''}")
        else:
            print(f"  {Colors.GREEN}✅ Dependencies: OK{Colors.RESET}")
        
        # Check if running
        if bot_id in launcher.running_bots:
            bot_process = launcher.running_bots[bot_id]
            if bot_process.process.poll() is None:
                print(f"  {Colors.GREEN}✅ Status: Running (PID: {bot_process.pid}){Colors.RESET}")
                running = True
            else:
                print(f"  {Colors.RED}❌ Status: Process exited{Colors.RESET}")
                running = False
        else:
            print(f"  {Colors.YELLOW}⚠️  Status: Not running{Colors.RESET}")
            running = False
        
        results.append({
            'bot': bot_name,
            'setup_ok': True,
            'setup_message': 'OK',
            'dependencies_ok': deps_ok,
            'missing_deps': missing_deps if not deps_ok else [],
            'running': running
        })
        print()
    
    # Summary
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}📊 Summary{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
    
    setup_ok_count = sum(1 for r in results if r['setup_ok'])
    deps_ok_count = sum(1 for r in results if r.get('dependencies_ok', False))
    running_count = sum(1 for r in results if r['running'])
    
    print(f"Total Bots: {len(results)}")
    print(f"{Colors.GREEN}✅ Setup OK: {setup_ok_count}/{len(results)}{Colors.RESET}")
    print(f"{Colors.GREEN if deps_ok_count == len(results) else Colors.YELLOW}✅ Dependencies OK: {deps_ok_count}/{len(results)}{Colors.RESET}")
    print(f"{Colors.GREEN if running_count > 0 else Colors.YELLOW}✅ Running: {running_count}/{len(results)}{Colors.RESET}")
    
    # Show issues
    issues = []
    for r in results:
        if not r['setup_ok']:
            issues.append(f"{r['bot']}: Setup issue - {r['setup_message']}")
        elif not r.get('dependencies_ok', False):
            issues.append(f"{r['bot']}: Missing dependencies - {', '.join(r.get('missing_deps', [])[:3])}")
        elif not r['running']:
            issues.append(f"{r['bot']}: Not running")
    
    if issues:
        print(f"\n{Colors.YELLOW}⚠️  Issues Found:{Colors.RESET}")
        for issue in issues:
            print(f"  - {issue}")
    
    return results

if __name__ == "__main__":
    try:
        results = check_all_bots()
        # Exit with error code if any bot has issues
        all_ok = all(r['setup_ok'] and r.get('dependencies_ok', False) for r in results)
        sys.exit(0 if all_ok else 1)
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted{Colors.RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"{Colors.RED}❌ Error: {str(e)}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
