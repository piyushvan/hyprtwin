import fcntl  # NEW: Linux native file locking
import json
import os
import signal
import subprocess
import time

from hyprtwin.system.config import get_binary_path

STATE_FILE = os.path.expanduser("~/.local/share/twin/server_state.json")


def _save_state(pid: int):
    """Saves the server PID to a hidden file with exclusive lock."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        # FIX: Lock the file exclusively so twin up/down don't corrupt it
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


def boot_server(model_path: str, context_size: int):
    # Check if a server is already alive before trying to boot a second one
    pid = _get_active_pid()
    if pid:
        try:
            os.kill(pid, 0)
            print(f"[*] Engine is already running (PID: {pid}).")
            return
        except OSError:
            pass  # Process is dead but file remained, safe to boot fresh

    binary = get_binary_path("llama-server")

    command = [
        binary,
        "-m",
        model_path,
        "-c",
        str(context_size),
        "-ngl",
        "99",  # Offload everything to GPU
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
        "--port",
        "8080",
    ]

    print("🚀 BOOTING BARE-METAL SOCKET...")
    print(f"[*] Executing: {binary}")

    log_dir = os.path.expanduser("~/.local/share/twin")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "llama.log")

    # FIX: Open log in append mode and pass the raw file descriptor
    log_out = open(log_file_path, "a")

    process = subprocess.Popen(
        command, stdout=log_out, stderr=log_out, preexec_fn=os.setsid
    )

    _save_state(process.pid)
    time.sleep(2)
    print(f"[+] Socket alive on 127.0.0.1:8080. PID: {process.pid}")
    print(f"[i] To watch logs: tail -f {log_file_path}")


def kill_server():
    """Violently terminates the ENTIRE background process group to free VRAM."""
    pid = _get_active_pid()
    if pid:
        try:
            # FIX: Get the process group ID and kill the entire tree
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
            print(
                f"[+] Successfully assassinated llama-server group (PID: {pid}). VRAM freed."
            )
        except OSError:
            pass  # Already dead

        # Clean up the state file safely
        if os.path.exists(STATE_FILE):
            try:
                os.remove(STATE_FILE)
            except OSError:
                pass
    else:
        print("[*] No active server found to kill.")
