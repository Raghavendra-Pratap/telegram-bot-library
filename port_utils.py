"""
Shared utility: find an available port.
Used by the launcher dashboard and can be used by bots that bind to a port.
"""
import socket


def find_available_port(start_port: int, max_tries: int = 50) -> int:
    """Find an available port starting from start_port. Tries start_port, start_port+1, ... up to max_tries."""
    for offset in range(max_tries):
        port = start_port + offset
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No available port found in range {start_port}..{start_port + max_tries - 1}")
