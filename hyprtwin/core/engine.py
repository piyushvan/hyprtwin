import os
import signal
import subprocess
import time

from hyprtwin.system.config import get_binary_path
from hyprtwin.system.hardware import get_safe_thread_count

# XDG-compliant paths
SOCKET_PATH = "/tmp/hyprtwin.sock"
PID_DIR = os.path.expanduser("~/.local/state/twin")
PID_FILE = os.path.join(PID_DIR, "twin.pid")
LOG_DIR = os.path.expanduser("~/.local/share/twin")
LOG_FILE = os.path.join(LOG_DIR, "llama.log")
LOG_OLD_FILE = os.path.join(LOG_DIR, "llama.log.old")
MAX_LOG_BYTES = 10 * 1024 * 1024  # 10 MB


def _save_pid(pid: int):
    """Writes the server PID to a plain text file (XDG state dir)."""
    os.makedirs(PID_DIR, exist_ok=True)
    with open(PID_FILE, "w") as f:
        f.write(str(pid))


def _get_active_pid() -> int | None:
    """Reads the current active server PID from the .pid file."""
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            pass
    return None


def _rotate_log():
    """Rotates the log file if it exceeds MAX_LOG_BYTES."""
    if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
        try:
            if os.path.exists(LOG_OLD_FILE):
                os.remove(LOG_OLD_FILE)
            os.rename(LOG_FILE, LOG_OLD_FILE)
        except OSError:
            pass


def _wait_for_server(timeout: int = 60):
    """Polls the Unix socket health endpoint until the server is ready.

    Checks every 200ms. Fails hard after `timeout` seconds with a clear message.
    """
    import socket as sock
    import http.client

    deadline = time.monotonic() + timeout
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        # Step 1: Check if the socket file exists on disk
        if not os.path.exists(SOCKET_PATH):
            time.sleep(0.2)
            continue

        # Step 2: Attempt an HTTP health check through the Unix socket
        try:
            conn = http.client.HTTPConnection("localhost")
            # Override the socket to use Unix domain socket
            s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
            s.settimeout(2)
            s.connect(SOCKET_PATH)
            conn.sock = s
            conn.request("GET", "/health")
            resp = conn.getresponse()
            if resp.status == 200:
                s.close()
                return  # Server is alive!
            s.close()
        except (ConnectionRefusedError, OSError, sock.timeout, Exception):
            pass

        time.sleep(0.2)

    print("❌ ERROR: Server failed to become ready within 60 seconds.")
    print(f"[!] Check the log file: tail -f {LOG_FILE}")
    raise SystemExit(1)


def boot_server(model_path: str, context_size: int, debug: bool = False):
    # Check if a server is already alive before trying to boot a second one
    pid = _get_active_pid()
    if pid:
        try:
            os.kill(pid, 0)
            print(f"[*] Engine is already running (PID: {pid}).")
            return
        except OSError:
            pass  # Process is dead but file remained, safe to boot fresh

    # Clean up stale socket file from a previous crash
    if os.path.exists(SOCKET_PATH):
        try:
            os.remove(SOCKET_PATH)
        except OSError:
            pass

    binary = get_binary_path("llama-server")
    threads = get_safe_thread_count()

    command = [
        binary,
        "-m",
        model_path,
        "-c",
        str(context_size),
        "-ngl",
        "99",  # Offload everything to GPU
        "-t",
        str(threads),  # CPU thread limit (leaves cores for OS)
        "-b",
        "512",  # Logical compute buffer
        "-ub",
        "512",  # Physical compute buffer
        "--mlock",  # Lock memory to prevent SSD swapping
        "--flash-attn",
        "on",
        "--cache-type-k",
        "turbo4",
        "--cache-type-v",
        "turbo3",
        "--host",
        SOCKET_PATH,  # Unix Domain Socket — no TCP, no port collisions
    ]

    print("🚀 BOOTING BARE-METAL SOCKET...")
    print(f"[*] Executing: {binary}")
    print(f"[*] CPU threads: {threads} / {os.cpu_count()}")

    if debug:
        # Debug mode: rotate and write to log file
        os.makedirs(LOG_DIR, exist_ok=True)
        _rotate_log()
        log_out = open(LOG_FILE, "a")
        print(f"[i] Debug logging to: {LOG_FILE}")
    else:
        # Production mode: silence llama-server output
        log_out = open(os.devnull, "w")

    process = subprocess.Popen(
        command, stdout=log_out, stderr=log_out, preexec_fn=os.setsid
    )

    _save_pid(process.pid)

    print(f"[*] Waiting for engine to load model (PID: {process.pid})...")
    _wait_for_server(timeout=60)

    # Lock down socket permissions — only current user can access
    try:
        os.chmod(SOCKET_PATH, 0o600)
    except OSError:
        pass

    print(f"[+] Socket alive on {SOCKET_PATH}. PID: {process.pid}")
    if debug:
        print(f"[i] To watch logs: tail -f {LOG_FILE}")


def kill_server():
    """Terminates the ENTIRE background process group to free VRAM."""
    pid = _get_active_pid()
    if pid:
        try:
            # Get the process group ID and kill the entire tree
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            print(
                f"[+] Successfully assassinated llama-server group (PID: {pid}). VRAM freed."
            )
        except OSError:
            pass  # Already dead

        # Clean up PID file
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

        # Clean up Unix socket file
        if os.path.exists(SOCKET_PATH):
            try:
                os.remove(SOCKET_PATH)
            except OSError:
                pass
    else:
        print("[*] No active server found to kill.")
