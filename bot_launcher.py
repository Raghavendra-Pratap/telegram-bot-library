#!/usr/bin/env python3
"""
Unified Bot Launcher
Allows you to select and run multiple Telegram bots with monitoring and stats
"""
import os
import sys
import json
import time
import signal
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

# PyPI distribution name -> import module (when they differ)
PACKAGE_IMPORT_ALIASES = {
    "python-telegram-bot": "telegram",
    "python-dotenv": "dotenv",
}

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

@dataclass
class BotProcess:
    """Information about a running bot process"""
    bot_id: str
    bot_name: str
    process: subprocess.Popen
    start_time: datetime
    pid: int
    port: Optional[int] = None
    status: str = "running"
    restart_count: int = 0
    last_error: Optional[str] = None
    log_file: Optional[Any] = None  # open file handle for logs/<bot_id>.log

class BotLauncher:
    def __init__(self, config_path: str = "bots_config.json"):
        self.config_path = Path(config_path)
        self.base_dir = Path(__file__).parent.absolute()
        self.config = self.load_config()
        self.running_bots: Dict[str, BotProcess] = {}
        self.stats = defaultdict(lambda: {
            "start_count": 0,
            "stop_count": 0,
            "restart_count": 0,
            "total_uptime": 0,
            "errors": []
        })
        self.monitoring = False
        self.monitor_thread = None
    
    def check_launcher_dependencies(self) -> Tuple[bool, List[str]]:
        """Check if launcher dependencies are installed"""
        missing = []
        required = ['flask']
        
        for package in required:
            try:
                # Try to import the package
                if package == 'flask':
                    import flask
                else:
                    __import__(package)
            except ImportError:
                missing.append(package)
        
        return len(missing) == 0, missing
    
    def install_launcher_dependencies(self) -> bool:
        """Install launcher dependencies"""
        requirements_file = self.base_dir / "launcher_requirements.txt"
        
        if not requirements_file.exists():
            print(f"{Colors.YELLOW}⚠️  launcher_requirements.txt not found{Colors.RESET}")
            return False
        
        print(f"{Colors.CYAN}📦 Installing launcher dependencies...{Colors.RESET}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
                capture_output=True,
                text=True,
                check=True
            )
            print(f"{Colors.GREEN}✅ Launcher dependencies installed{Colors.RESET}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}❌ Failed to install launcher dependencies:{Colors.RESET}")
            print(e.stderr)
            return False
    
    def _normalize_requirement_name(self, line: str) -> Optional[str]:
        """Extract PyPI package name from a requirements line."""
        line = line.strip()
        if not line or line.startswith("#"):
            return None
        if line.startswith(("-r", "--requirement")):
            return None
        if line.startswith(("-", "[")):
            return None
        # PEP 508: name before version specifiers / extras
        token = line.split(";")[0].strip()
        token = token.split("[")[0].strip()
        for sep in ("==", ">=", "<=", "!=", "~=", ">", "<"):
            if sep in token:
                token = token.split(sep)[0].strip()
        return token or None

    def parse_requirements_file(
        self,
        requirements_path: Path,
        visited: Optional[set] = None,
    ) -> List[str]:
        """Parse requirements.txt, following -r includes recursively."""
        packages: List[str] = []
        if visited is None:
            visited = set()

        req_path = requirements_path.resolve()
        if req_path in visited:
            return packages
        visited.add(req_path)

        if not req_path.exists():
            return packages

        try:
            base_dir = req_path.parent
            with open(req_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith(("-r", "--requirement")):
                        parts = line.split(maxsplit=1)
                        if len(parts) == 2:
                            included = (base_dir / parts[1].strip()).resolve()
                            packages.extend(
                                self.parse_requirements_file(included, visited)
                            )
                        continue
                    name = self._normalize_requirement_name(line)
                    if name:
                        packages.append(name)
        except Exception as e:
            print(
                f"{Colors.YELLOW}⚠️  Error parsing {requirements_path}: {e}{Colors.RESET}"
            )

        return packages
    
    def _pip_list_names(self, python_exe: Path) -> set:
        result = subprocess.run(
            [str(python_exe), "-m", "pip", "list", "--format=json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return set()
        installed = json.loads(result.stdout)
        return {pkg["name"].lower() for pkg in installed}

    def check_package_installed(self, package_name: str, venv_python: Optional[Path] = None) -> bool:
        """Check if a package is installed in a specific virtual environment"""
        try:
            pip_name = package_name.lower()
            python_exe = venv_python or Path(sys.executable)

            installed = self._pip_list_names(python_exe)
            if pip_name in installed:
                return True

            import_name = PACKAGE_IMPORT_ALIASES.get(
                package_name.lower(),
                package_name.replace("-", "_").lower(),
            )
            try:
                __import__(import_name)
                return True
            except ImportError:
                return False
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
            return False
    
    def check_bot_dependencies(self, bot: dict) -> Tuple[bool, List[str]]:
        """Check if bot dependencies are installed"""
        bot_dir = self.base_dir / bot['directory']
        requirements_path = bot_dir / "requirements.txt"
        python_exe = self._get_bot_venv_python(bot)
        if python_exe is None:
            return False, ["Virtual environment Python not found"]
        
        # Parse requirements.txt
        required_packages = self.parse_requirements_file(requirements_path)
        
        if not required_packages:
            # No requirements file or empty, assume OK
            return True, []
        
        # Check each package
        missing = []
        for package in required_packages:
            # Check if installed in venv using the package name from requirements.txt
            # This works because pip uses the package name, not the import name
            if not self.check_package_installed(package, python_exe):
                missing.append(package)
        
        return len(missing) == 0, missing
    
    def install_bot_dependencies(self, bot: dict) -> bool:
        """Install bot dependencies"""
        bot_dir = self.base_dir / bot['directory']
        requirements_path = bot_dir / "requirements.txt"
        python_exe = self._get_bot_venv_python(bot)
        if python_exe is None:
            venv_path = bot_dir / bot['venv_path']
            print(f"{Colors.RED}❌ Python executable not found in {venv_path}{Colors.RESET}")
            return False
        
        if not requirements_path.exists():
            print(f"{Colors.YELLOW}⚠️  No requirements.txt found for {bot['name']}{Colors.RESET}")
            return True  # Not an error if no requirements file
        
        print(f"{Colors.CYAN}📦 Installing dependencies for {bot['name']}...{Colors.RESET}")
        try:
            result = subprocess.run(
                [str(python_exe), "-m", "pip", "install", "-r", str(requirements_path)],
                capture_output=True,
                text=True,
                check=True,
                cwd=str(bot_dir)
            )
            print(f"{Colors.GREEN}✅ Dependencies installed for {bot['name']}{Colors.RESET}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}❌ Failed to install dependencies for {bot['name']}:{Colors.RESET}")
            print(e.stderr)
            return False
    
    def ensure_dependencies(self, check_bots: Optional[List[dict]] = None, auto_install: bool = True) -> bool:
        """Ensure all required dependencies are installed"""
        print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"{Colors.BOLD}🔍 Checking Dependencies{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
        
        # Check launcher dependencies
        launcher_ok, missing_launcher = self.check_launcher_dependencies()
        if not launcher_ok:
            print(f"{Colors.YELLOW}⚠️  Missing launcher dependencies: {', '.join(missing_launcher)}{Colors.RESET}")
            if auto_install:
                print(f"{Colors.CYAN}Installing missing launcher dependencies...{Colors.RESET}")
                if not self.install_launcher_dependencies():
                    print(f"{Colors.YELLOW}⚠️  Dashboard feature will not be available{Colors.RESET}")
            else:
                if input(f"{Colors.CYAN}Install missing launcher dependencies? (y/n): {Colors.RESET}").lower() == 'y':
                    if not self.install_launcher_dependencies():
                        return False
                else:
                    print(f"{Colors.YELLOW}⚠️  Dashboard feature will not be available{Colors.RESET}")
        else:
            print(f"{Colors.GREEN}✅ Launcher dependencies OK{Colors.RESET}")
        
        # Check bot dependencies if bots are specified
        if check_bots:
            print(f"\n{Colors.CYAN}Checking bot dependencies...{Colors.RESET}\n")
            for bot in check_bots:
                bot_ok, missing_bot = self.check_bot_dependencies(bot)
                if not bot_ok:
                    print(f"{Colors.YELLOW}⚠️  {bot['name']}: Missing {len(missing_bot)} dependencies: {', '.join(missing_bot[:5])}{'...' if len(missing_bot) > 5 else ''}{Colors.RESET}")
                    if auto_install:
                        print(f"{Colors.CYAN}Installing missing dependencies for {bot['name']}...{Colors.RESET}")
                        if not self.install_bot_dependencies(bot):
                            print(f"{Colors.RED}❌ Failed to install dependencies for {bot['name']}{Colors.RESET}")
                            return False
                    else:
                        if input(f"{Colors.CYAN}Install missing dependencies for {bot['name']}? (y/n): {Colors.RESET}").lower() == 'y':
                            if not self.install_bot_dependencies(bot):
                                print(f"{Colors.RED}❌ Failed to install dependencies for {bot['name']}{Colors.RESET}")
                                return False
                else:
                    print(f"{Colors.GREEN}✅ {bot['name']}: Dependencies OK{Colors.RESET}")
        
        print()
        return True
        
    def load_config(self) -> dict:
        """Load bot configuration from JSON file"""
        if not self.config_path.exists():
            print(f"{Colors.RED}❌ Config file not found: {self.config_path}{Colors.RESET}")
            sys.exit(1)
        
        with open(self.config_path, 'r') as f:
            return json.load(f)
    
    def get_available_bots(self) -> List[dict]:
        """Get list of available bots"""
        return [bot for bot in self.config['bots'] if bot.get('enabled', True)]
    
    def _get_bot_venv_python(self, bot: dict) -> Optional[Path]:
        """Resolve the Python executable for a bot's venv (bin/python or bin/python3). Returns None if venv or python not found."""
        bot_dir = self.base_dir / bot['directory']
        venv_path = bot_dir / bot['venv_path']
        python_exe = venv_path / "bin" / "python"
        if not python_exe.exists():
            python_exe = venv_path / "bin" / "python3"
        return python_exe if python_exe.exists() else None
    
    def check_bot_env(self, bot: dict) -> Tuple[bool, str]:
        """Verify .env exists and required variables are set (non-secret check)."""
        required = bot.get("env_required") or []
        if not required:
            return True, "OK"

        bot_dir = self.base_dir / bot["directory"]
        env_path = bot_dir / ".env"
        if not env_path.exists():
            example = bot_dir / ".env.example"
            hint = f" (copy {example.name} to .env)" if example.exists() else ""
            return False, f".env not found in {bot_dir}{hint}"

        values: Dict[str, Optional[str]] = {}
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    values[key.strip()] = val.strip().strip('"').strip("'")
        except OSError as e:
            return False, f"Could not read .env: {e}"

        missing = [k for k in required if not (values.get(k) or "").strip()]
        if missing:
            return False, f"Missing or empty in .env: {', '.join(missing)}"
        return True, "OK"

    def _clear_stale_pid_file(self, bot_dir: Path, pid_file: str) -> Optional[str]:
        """Remove pid file if the process is gone. Return error message if still running."""
        path = bot_dir / pid_file
        if not path.exists():
            return None
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            return (
                f"Another instance is already running (PID {pid}). "
                f"Stop it first or remove stale {path.name} if incorrect."
            )
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return None

    def check_bot_setup(self, bot: dict) -> Tuple[bool, str]:
        """Check if bot is properly set up"""
        bot_dir = self.base_dir / bot['directory']
        
        if not bot_dir.exists():
            return False, f"Directory not found: {bot_dir}"
        
        script_path = bot_dir / bot['script']
        if not script_path.exists():
            return False, f"Script not found: {script_path}"
        
        venv_path = bot_dir / bot['venv_path']
        if not venv_path.exists():
            return False, f"Virtual environment not found: {venv_path}"
        
        if self._get_bot_venv_python(bot) is None:
            return False, f"Python executable not found in venv: {venv_path}"

        env_ok, env_msg = self.check_bot_env(bot)
        if not env_ok:
            return False, env_msg

        pid_file = bot.get("pid_file")
        if pid_file:
            pid_err = self._clear_stale_pid_file(bot_dir, pid_file)
            if pid_err:
                return False, pid_err
        
        return True, "OK"
    
    def start_bot(self, bot: dict, auto_install: bool = True) -> Optional[BotProcess]:
        """Start a bot process"""
        bot_id = bot['id']
        bot_name = bot['name']
        
        # Check if already running
        if bot_id in self.running_bots:
            proc = self.running_bots[bot_id]
            if proc.process.poll() is None:
                print(f"{Colors.YELLOW}⚠️  {bot_name} is already running (PID: {proc.pid}){Colors.RESET}")
                return proc
        
        # Check setup
        is_ok, message = self.check_bot_setup(bot)
        if not is_ok:
            print(f"{Colors.RED}❌ {bot_name}: {message}{Colors.RESET}")
            return None
        
        # Check and install dependencies
        bot_ok, missing_bot = self.check_bot_dependencies(bot)
        if not bot_ok:
            if auto_install:
                print(f"{Colors.YELLOW}⚠️  {bot_name}: Missing dependencies, installing...{Colors.RESET}")
                if not self.install_bot_dependencies(bot):
                    print(f"{Colors.RED}❌ {bot_name}: Failed to install dependencies{Colors.RESET}")
                    return None
            else:
                print(f"{Colors.RED}❌ {bot_name}: Missing dependencies: {', '.join(missing_bot)}{Colors.RESET}")
                return None
        
        bot_dir = self.base_dir / bot['directory']
        python_exe = self._get_bot_venv_python(bot)
        if python_exe is None:
            print(f"{Colors.RED}❌ {bot_name}: Virtual environment or Python not found{Colors.RESET}")
            return None
        
        script_path = bot_dir / bot['script']

        pid_file = bot.get("pid_file")
        if pid_file:
            pid_err = self._clear_stale_pid_file(bot_dir, pid_file)
            if pid_err:
                print(f"{Colors.RED}❌ {bot_name}: {pid_err}{Colors.RESET}")
                return None
        
        print(f"{Colors.CYAN}🚀 Starting {bot_name}...{Colors.RESET}")
        
        try:
            # Log file for this bot (so you can tail logs/<bot_id>.log)
            log_dir = self.base_dir / "logs"
            log_dir.mkdir(exist_ok=True)
            log_path = log_dir / f"{bot_id}.log"
            log_file = open(log_path, "a", encoding="utf-8")
            log_file.write(f"\n--- Started at {datetime.now().isoformat()} ---\n")
            log_file.flush()
            
            # Start bot process; stdout/stderr go to log file
            process = subprocess.Popen(
                [str(python_exe), str(script_path)],
                cwd=str(bot_dir),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )
            
            # Wait a moment to check if it started successfully
            time.sleep(2)
            
            if process.poll() is not None:
                # Process exited immediately - show last lines from log
                log_file.flush()
                try:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    error_msg = content[-2000:] if len(content) > 2000 else content
                except Exception:
                    error_msg = "(see logs/{} for details)".format(f"{bot_id}.log")
                log_file.close()
                print(f"{Colors.RED}❌ {bot_name} failed to start:{Colors.RESET}")
                print(error_msg[-500:] if len(error_msg) > 500 else error_msg)
                return None
            
            bot_process = BotProcess(
                bot_id=bot_id,
                bot_name=bot_name,
                process=process,
                start_time=datetime.now(),
                pid=process.pid,
                port=bot.get('port'),
                status="running",
                log_file=log_file
            )
            
            self.running_bots[bot_id] = bot_process
            self.stats[bot_id]["start_count"] += 1
            
            print(f"{Colors.GREEN}✅ {bot_name} started (PID: {process.pid}){Colors.RESET}")
            if bot.get('port'):
                print(f"   🌐 Port: {bot['port']}")
            print(f"   📄 Logs: tail -f logs/{bot_id}.log")
            
            return bot_process
            
        except Exception as e:
            print(f"{Colors.RED}❌ Error starting {bot_name}: {str(e)}{Colors.RESET}")
            return None
    
    def stop_bot(self, bot_id: str) -> bool:
        """Stop a running bot"""
        if bot_id not in self.running_bots:
            print(f"{Colors.YELLOW}⚠️  Bot {bot_id} is not running{Colors.RESET}")
            return False
        
        bot_process = self.running_bots[bot_id]
        process = bot_process.process
        
        print(f"{Colors.CYAN}🛑 Stopping {bot_process.bot_name}...{Colors.RESET}")
        
        try:
            # Try graceful shutdown
            process.terminate()
            
            # Wait up to 5 seconds
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop
                process.kill()
                process.wait()
            
            uptime = (datetime.now() - bot_process.start_time).total_seconds()
            self.stats[bot_id]["total_uptime"] += uptime
            self.stats[bot_id]["stop_count"] += 1
            
            if getattr(bot_process, "log_file", None) is not None:
                try:
                    bot_process.log_file.close()
                except Exception:
                    pass
            del self.running_bots[bot_id]
            print(f"{Colors.GREEN}✅ {bot_process.bot_name} stopped{Colors.RESET}")
            return True
            
        except Exception as e:
            print(f"{Colors.RED}❌ Error stopping {bot_id}: {str(e)}{Colors.RESET}")
            return False
    
    def restart_bot(self, bot_id: str) -> bool:
        """Restart a bot"""
        bot_config = next((b for b in self.config['bots'] if b['id'] == bot_id), None)
        if not bot_config:
            print(f"{Colors.RED}❌ Bot {bot_id} not found in config{Colors.RESET}")
            return False
        
        if bot_id in self.running_bots:
            self.stop_bot(bot_id)
            time.sleep(1)
        
        bot_process = self.start_bot(bot_config)
        if bot_process:
            bot_process.restart_count += 1
            self.stats[bot_id]["restart_count"] += 1
            return True
        return False
    
    def monitor_bots(self):
        """Monitor running bots and restart if they crash"""
        while self.monitoring:
            time.sleep(5)  # Check every 5 seconds
            
            for bot_id, bot_process in list(self.running_bots.items()):
                if bot_process.process.poll() is not None:
                    # Process has exited
                    print(f"{Colors.RED}⚠️  {bot_process.bot_name} crashed (PID: {bot_process.pid}). Check logs/{bot_id}.log{Colors.RESET}")
                    
                    if getattr(bot_process, "log_file", None) is not None:
                        try:
                            bot_process.log_file.close()
                        except Exception:
                            pass
                    
                    uptime = (datetime.now() - bot_process.start_time).total_seconds()
                    self.stats[bot_id]["total_uptime"] += uptime
                    del self.running_bots[bot_id]
                    
                    # Auto-restart if monitoring is enabled
                    bot_config = next((b for b in self.config['bots'] if b['id'] == bot_id), None)
                    if bot_config:
                        print(f"{Colors.YELLOW}🔄 Auto-restarting {bot_process.bot_name}...{Colors.RESET}")
                        time.sleep(2)
                        self.start_bot(bot_config)
    
    def show_status(self):
        """Show status of all bots"""
        print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"{Colors.BOLD}📊 Bot Status{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
        
        available_bots = self.get_available_bots()
        
        for bot in available_bots:
            bot_id = bot['id']
            bot_name = bot['name']
            status_icon = "🟢" if bot_id in self.running_bots else "🔴"
            
            if bot_id in self.running_bots:
                bot_process = self.running_bots[bot_id]
                uptime = datetime.now() - bot_process.start_time
                uptime_str = str(uptime).split('.')[0]  # Remove microseconds
                
                port_info = f" | Port: {bot_process.port}" if bot_process.port else ""
                print(f"{status_icon} {Colors.GREEN}{bot_name:20s}{Colors.RESET} | "
                      f"PID: {bot_process.pid:6d} | "
                      f"Uptime: {uptime_str:>12s}{port_info}")
            else:
                print(f"{status_icon} {Colors.RED}{bot_name:20s}{Colors.RESET} | "
                      f"{'Stopped':>20s}")
        
        print()
    
    def show_stats(self):
        """Show statistics for all bots"""
        print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
        print(f"{Colors.BOLD}📈 Bot Statistics{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
        
        for bot_id, stats in self.stats.items():
            bot_config = next((b for b in self.config['bots'] if b['id'] == bot_id), None)
            bot_name = bot_config['name'] if bot_config else bot_id
            
            total_uptime_hours = stats["total_uptime"] / 3600
            
            print(f"{Colors.BOLD}{bot_name}{Colors.RESET}")
            print(f"  Starts: {stats['start_count']}")
            print(f"  Stops: {stats['stop_count']}")
            print(f"  Restarts: {stats['restart_count']}")
            print(f"  Total Uptime: {total_uptime_hours:.2f} hours")
            if stats['errors']:
                print(f"  Errors: {len(stats['errors'])}")
            print()
    
    def interactive_menu(self):
        """Interactive menu for bot management"""
        while True:
            print(f"\n{Colors.BOLD}{'='*80}{Colors.RESET}")
            print(f"{Colors.BOLD}🤖 Telegram Bot Launcher{Colors.RESET}")
            print(f"{Colors.BOLD}{'='*80}{Colors.RESET}\n")
            
            available_bots = self.get_available_bots()
            
            print(f"{Colors.CYAN}Available Bots:{Colors.RESET}")
            for i, bot in enumerate(available_bots, 1):
                bot_id = bot['id']
                status = "🟢 Running" if bot_id in self.running_bots else "🔴 Stopped"
                print(f"  {i}. {bot['name']:20s} - {bot['description']:50s} [{status}]")
            
            print(f"\n{Colors.CYAN}Actions:{Colors.RESET}")
            print("  1. Start bot(s)")
            print("  2. Stop bot(s)")
            print("  3. Restart bot(s)")
            print("  4. Show status")
            print("  5. Show statistics")
            print("  6. Start monitoring (auto-restart)")
            print("  7. Stop monitoring")
            print("  8. Start dashboard (web interface)")
            print("  9. Exit")
            
            choice = input(f"\n{Colors.YELLOW}Select action (1-9): {Colors.RESET}").strip()
            
            if choice == '1':
                self._start_bots_menu(available_bots)
            elif choice == '2':
                self._stop_bots_menu()
            elif choice == '3':
                self._restart_bots_menu(available_bots)
            elif choice == '4':
                self.show_status()
                input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.RESET}")
            elif choice == '5':
                self.show_stats()
                input(f"\n{Colors.CYAN}Press Enter to continue...{Colors.RESET}")
            elif choice == '6':
                self._start_monitoring()
            elif choice == '7':
                self._stop_monitoring()
            elif choice == '8':
                self._start_dashboard()
            elif choice == '9':
                self._shutdown()
                break
            else:
                print(f"{Colors.RED}Invalid choice{Colors.RESET}")
    
    def _start_bots_menu(self, available_bots: List[dict]):
        """Menu for starting bots"""
        print(f"\n{Colors.CYAN}Select bots to start (comma-separated numbers, or 'all'):{Colors.RESET}")
        selection = input().strip().lower()
        
        if selection == 'all':
            bots_to_start = available_bots
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                bots_to_start = [available_bots[i] for i in indices if 0 <= i < len(available_bots)]
            except (ValueError, IndexError):
                print(f"{Colors.RED}Invalid selection{Colors.RESET}")
                return
        
        # Check dependencies for selected bots (auto-install enabled)
        print(f"\n{Colors.CYAN}Checking dependencies for selected bots...{Colors.RESET}")
        if not self.ensure_dependencies(check_bots=bots_to_start, auto_install=True):
            print(f"{Colors.YELLOW}⚠️  Some dependencies may be missing. Bots may not work correctly.{Colors.RESET}")
            if input(f"{Colors.CYAN}Continue anyway? (y/n): {Colors.RESET}").lower() != 'y':
                return
        
        for bot in bots_to_start:
            self.start_bot(bot, auto_install=True)
            time.sleep(1)  # Small delay between starts
    
    def _stop_bots_menu(self):
        """Menu for stopping bots"""
        if not self.running_bots:
            print(f"{Colors.YELLOW}No bots are running{Colors.RESET}")
            return
        
        print(f"\n{Colors.CYAN}Running bots:{Colors.RESET}")
        running_list = list(self.running_bots.items())
        for i, (bot_id, bot_process) in enumerate(running_list, 1):
            print(f"  {i}. {bot_process.bot_name} (PID: {bot_process.pid})")
        
        print(f"\n{Colors.CYAN}Select bots to stop (comma-separated numbers, or 'all'):{Colors.RESET}")
        selection = input().strip().lower()
        
        if selection == 'all':
            bot_ids = list(self.running_bots.keys())
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                bot_ids = [running_list[i][0] for i in indices if 0 <= i < len(running_list)]
            except (ValueError, IndexError):
                print(f"{Colors.RED}Invalid selection{Colors.RESET}")
                return
        
        for bot_id in bot_ids:
            self.stop_bot(bot_id)
            time.sleep(0.5)
    
    def _restart_bots_menu(self, available_bots: List[dict]):
        """Menu for restarting bots"""
        running_bots = [b for b in available_bots if b['id'] in self.running_bots]
        
        if not running_bots:
            print(f"{Colors.YELLOW}No bots are running{Colors.RESET}")
            return
        
        print(f"\n{Colors.CYAN}Running bots:{Colors.RESET}")
        for i, bot in enumerate(running_bots, 1):
            print(f"  {i}. {bot['name']}")
        
        print(f"\n{Colors.CYAN}Select bots to restart (comma-separated numbers, or 'all'):{Colors.RESET}")
        selection = input().strip().lower()
        
        if selection == 'all':
            bots_to_restart = running_bots
        else:
            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                bots_to_restart = [running_bots[i] for i in indices if 0 <= i < len(running_bots)]
            except (ValueError, IndexError):
                print(f"{Colors.RED}Invalid selection{Colors.RESET}")
                return
        
        for bot in bots_to_restart:
            self.restart_bot(bot['id'])
            time.sleep(1)
    
    def _start_monitoring(self):
        """Start monitoring thread"""
        if self.monitoring:
            print(f"{Colors.YELLOW}Monitoring is already running{Colors.RESET}")
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self.monitor_bots, daemon=True)
        self.monitor_thread.start()
        print(f"{Colors.GREEN}✅ Monitoring started (auto-restart enabled){Colors.RESET}")
    
    def _stop_monitoring(self):
        """Stop monitoring"""
        if not self.monitoring:
            print(f"{Colors.YELLOW}Monitoring is not running{Colors.RESET}")
            return
        
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        print(f"{Colors.GREEN}✅ Monitoring stopped{Colors.RESET}")
    
    def _start_dashboard(self):
        """Start web dashboard on the configured port or the next available port if that one is in use."""
        try:
            from dashboard import start_dashboard
            dashboard_port = self.config.get('dashboard', {}).get('port', 5000)
            dashboard_host = self.config.get('dashboard', {}).get('host', '0.0.0.0')
            port_holder = [None]  # dashboard thread will set port_holder[0] = actual port used
            
            print(f"{Colors.CYAN}Starting dashboard (trying port {dashboard_port}, or next available)...{Colors.RESET}")
            
            def run_dashboard():
                try:
                    start_dashboard(self, dashboard_host, dashboard_port, port_holder=port_holder)
                except Exception as e:
                    print(f"{Colors.RED}❌ Dashboard error: {e}{Colors.RESET}")
            
            dashboard_thread = threading.Thread(target=run_dashboard, daemon=True)
            dashboard_thread.start()
            
            # Wait for dashboard to pick a port (up to 3 seconds)
            for _ in range(30):
                time.sleep(0.1)
                if port_holder[0] is not None:
                    break
            actual_port = port_holder[0] or dashboard_port
            print(f"{Colors.GREEN}✅ Dashboard started{Colors.RESET}")
            print(f"   Open http://localhost:{actual_port} in your browser")
            
        except ImportError:
            print(f"{Colors.YELLOW}⚠️  Dashboard module not found. Run: pip install flask{Colors.RESET}")
        except Exception as e:
            print(f"{Colors.RED}❌ Error starting dashboard: {str(e)}{Colors.RESET}")
    
    def _shutdown(self):
        """Shutdown all bots and cleanup"""
        print(f"\n{Colors.CYAN}Shutting down all bots...{Colors.RESET}")
        self.monitoring = False
        
        for bot_id in list(self.running_bots.keys()):
            self.stop_bot(bot_id)
        
        print(f"{Colors.GREEN}✅ All bots stopped{Colors.RESET}")

def main():
    """Main entry point"""
    launcher = BotLauncher()
    
    # Check launcher dependencies on startup
    launcher_ok, missing_launcher = launcher.check_launcher_dependencies()
    if not launcher_ok:
        print(f"{Colors.YELLOW}⚠️  Missing launcher dependencies: {', '.join(missing_launcher)}{Colors.RESET}")
        if input(f"{Colors.CYAN}Install missing dependencies automatically? (y/n): {Colors.RESET}").lower() == 'y':
            if not launcher.install_launcher_dependencies():
                print(f"{Colors.RED}❌ Failed to install launcher dependencies{Colors.RESET}")
                print(f"{Colors.YELLOW}⚠️  Dashboard feature will not be available{Colors.RESET}")
        else:
            print(f"{Colors.YELLOW}⚠️  Dashboard feature will not be available{Colors.RESET}")
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print(f"\n{Colors.YELLOW}Shutting down...{Colors.RESET}")
        launcher._shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start interactive menu
    launcher.interactive_menu()

if __name__ == "__main__":
    main()
