import json
import os
import signal
import subprocess
import time

from hyprtwin.system.config import get_binary_path

STATE_FILE = os.path.expanduser("~/.local/share/twin/server_state.json")


def _save_state(pid: int):
    """Saves the server PID to a hidden file for the watchdog."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump({"pid": pid, "last_active": time.time()}, f)


def _get_active_pid() -> int | None:
    """Reads the current active server PID, if it exists."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return data.get("pid")
        except json.JSONDecodeError:
            pass
    return None


from hyprtwin.system.config import get_binary_path

# ... keep your _get_active_pid and _save_state functions ...


def boot_server(model_path: str, context_size: int):
    # ... (Keep your PID check logic) ...

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
        "512",  # Restricts compute buffer
        "--flash-attn",
        "on",  # Correct syntax for the TurboQuant fork
        "--cache-type-k",
        "turbo4",
        "--cache-type-v",
        "turbo3",
        "--port",
        "8080",
    ]

    print("🚀 BOOTING BARE-METAL SOCKET...")
    print(f"[*] Executing: {binary}")

    # Replicating your Fish log routing
    log_dir = os.path.expanduser("~/.local/share/twin")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, "llama.log")

    with open(log_file_path, "w") as log_out:
        process = subprocess.Popen(
            command, stdout=log_out, stderr=log_out, preexec_fn=os.setsid
        )

    _save_state(process.pid)
    time.sleep(2)
    print(f"[+] Socket alive on 127.0.0.1:8080. PID: {process.pid}")
    print(f"[i] To watch logs: tail -f {log_file_path}")


def kill_server():
    """Violently terminates the background server to free VRAM."""
    pid = _get_active_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"[+] Successfully killed llama-server (PID: {pid}). VRAM freed.")
        except OSError:
            pass  # Already dead

        # Clean up the state file
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
    else:
        print("[*] No active server found to kill.")
