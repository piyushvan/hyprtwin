import fcntl
import json
import os
import signal
import subprocess
import sys
import time

import requests

from hyprtwin.system.config import get_binary_path

STATE_FILE = os.path.expanduser("~/.local/share/twin/server_state.json")


def _save_state(pid: int):
    """Saves the server PID to a hidden file with exclusive lock."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump({"pid": pid, "last_active": time.time()}, f)
        fcntl.flock(f, fcntl.LOCK_UN)


def _get_active_pid() -> int | None:
    """Reads the current active server PID with shared lock."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
                return data.get("pid")
        except (json.JSONDecodeError, IOError):
            pass
    return None


def _is_pid_alive(pid: int) -> bool:
    """Check if process exists (signal 0)."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def boot_server(model_path: str, context_size: int):
    # Check if a server is already alive (and actually running)
    pid = _get_active_pid()
    if pid and _is_pid_alive(pid):
        print(f"[*] Engine is already running (PID: {pid}).")
        return

    # Clean up stale state file
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)

    binary = get_binary_path("llama-server")
    command = [
        binary,
        "-m",
        model_path,
        "-c",
        str(context_size),
        "-ngl",
        "99",
        "-b",
        "256",
        "-ub",
        "256",
        "--mlock",
        "--flash-attn",
        "on",
        "--cache-type-k",
        "turbo4",
        "--cache-type-v",
        "turbo3",
        "--port",
        "8080",
    ]

    print("🚀 BOOTING BARE-METAL SOCKET...")
    log_dir = os.path.expanduser("~/.local/share/twin")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "llama.log")
    log_out = open(log_file_path, "a")

    # Start the process with process group detachment
    process = subprocess.Popen(
        command, stdout=log_out, stderr=log_out, preexec_fn=os.setsid
    )
    _save_state(process.pid)

    # Health-Check Loop
    print("[*] Waiting for engine to load model into VRAM...")
    for _ in range(60):  # 60 second timeout
        # Check if process crashed
        if process.poll() is not None:
            log_out.close()
            print("\n❌ CRITICAL: Engine crashed during boot.")
            print(f"[*] Check logs at {log_file_path}")
            # Clean up state file
            if os.path.exists(STATE_FILE):
                os.remove(STATE_FILE)
            sys.exit(1)

        # Poll health endpoint
        try:
            res = requests.get("http://127.0.0.1:8080/health", timeout=1.0)
            if res.status_code == 200:
                log_out.close()
                print(f"\n[+] Engine Online. PID: {process.pid}")
                return  # SUCCESS
        except requests.exceptions.RequestException:
            pass

        time.sleep(1)

    # Timeout: kill the server and exit
    log_out.close()
    print("\n❌ TIMEOUT: Engine failed to respond in 60s.")
    kill_server()
    sys.exit(1)


def kill_server():
    """Violently terminates the background process group, freeing VRAM."""
    pid = _get_active_pid()
    if not pid:
        print("[*] No active server found to kill.")
        return

    try:
        # Get process group ID (set by preexec_fn=os.setsid)
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        print(f"[+] Successfully killed process group (PGID: {pgid}). VRAM freed.")
    except OSError as e:
        # Fallback: kill the individual process
        logging.warning(f"Could not kill process group: {e}. Trying direct kill.")
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[+] Killed orphaned process (PID: {pid}).")
        except OSError:
            print(f"[-] Process {pid} already dead.")
    finally:
        # Remove state file regardless
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
