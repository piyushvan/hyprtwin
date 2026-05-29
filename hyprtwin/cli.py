import json
import sys
from pathlib import Path
from typing import List, Optional

import questionary
import typer

from hyprtwin.api.client import ask_server, clear_history
from hyprtwin.core.engine import boot_server, kill_server
from hyprtwin.system.config import get_config, save_config
from hyprtwin.system.hardware import (
    calculate_safe_context,
    get_cpu_model,
    get_gpu_status,
    get_system_ram_info,
)

app = typer.Typer(
    no_args_is_help=True, help="Twin: Maximized for 4GB VRAM. Strictly Linux Native."
)

PROFILE_FILE = Path("~/.local/share/twin/profile.json").expanduser()


@app.command()
def init():
    """Initial setup to link your binaries and model folders."""
    config = get_config()
    print("🛠️  HyprTwin First-Run Setup")

    bin_path = questionary.path(
        "Where is your llama.cpp 'bin' folder? (Contains llama-server)",
        default=config.get("bin_path", ""),
    ).ask()
    model_path = questionary.path(
        "Add a directory to search for .gguf models:", default=config["model_paths"][0]
    ).ask()

    config["bin_path"] = bin_path
    if model_path not in config["model_paths"]:
        config["model_paths"].append(model_path)

    save_config(config)
    print("\n✅ Configuration saved to ~/.config/twin/config.json")


@app.command()
def scan():
    """Run a bare-metal telemetry scan (Shows real-time VRAM, CPU)."""
    print("=== 🚀 HYPRTWIN V3.1: BARE-METAL TELEMETRY ===")
    print(f"[+] CPU Model: {get_cpu_model()}")
    ram = get_system_ram_info()
    print(f"[+] System RAM (Total): {ram['total_mb']} MB")
    print(f"[*] System RAM (Free):  {ram['free_mb']} MB")
    gpu = get_gpu_status()
    print(f"[+] GPU Type: {gpu['type']}")
    print(f"[+] GPU Total VRAM: {gpu['total_vram_mb']} MB")
    print(f"[*] GPU Free VRAM: {gpu['free_vram_mb']} MB")
    print("==============================================")


@app.command()
def build():
    """Profiles hardware, builds the agent, and caches the safe profile."""
    config = get_config()
    model_paths = config.get("model_paths", [])

    # 1. Find all .gguf files
    gguf_files = []
    for d in model_paths:
        p = Path(d).expanduser()
        if p.exists() and p.is_dir():
            gguf_files.extend(list(p.glob("*.gguf")))

    if not gguf_files:
        print("[!] No .gguf models found in your configured paths.")
        raise typer.Exit(1)

    # 2. Build the interactive menu
    choices = [f"{m.name} ({m.stat().st_size // (1024 * 1024)} MB)" for m in gguf_files]
    selected_str = questionary.select(
        "🧠 Select a model to load into VRAM:", choices=choices
    ).ask()

    if not selected_str:
        raise typer.Exit()

    # 3. Hardware Math & Headroom
    selected_file = next(m for m in gguf_files if m.name in selected_str)
    model_size_mb = selected_file.stat().st_size // (1024 * 1024)

    gpu = get_gpu_status()
    safe_data = calculate_safe_context(model_size_mb)

    print("\n⚙️  HARDWARE GOVERNOR:")
    print(f"  [+] Free VRAM: {gpu['free_vram_mb']} MB")
    print(f"  [+] Model Footprint: {model_size_mb} MB")
    print(f"  [+] Context Headroom: {safe_data['headroom_mb']} MB")
    print(f"  [+] Absolute Max Tokens: {safe_data['max_tokens']}")

    if safe_data["headroom_mb"] <= 0 or safe_data["max_tokens"] < 1024:
        print("❌ ERROR: Not enough free VRAM to boot this model safely.")
        raise typer.Exit(1)

    # 4. Context Window Selection
    master_powers = [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]
    valid_choices = [str(p) for p in master_powers if p <= safe_data["max_tokens"]]

    if not valid_choices:
        valid_choices = [str(safe_data["max_tokens"])]

    ctx_str = questionary.select(
        "📏 Select Context Window Size (Strict Powers of 2):",
        choices=valid_choices,
        default=valid_choices[-1],
    ).ask()

    if not ctx_str:
        raise typer.Exit()

    # 5. Boot & Save Profile
    confirm = questionary.confirm(
        "🚀 Boot the bare-metal socket with these parameters?"
    ).ask()

    if confirm:
        # Save the successful profile
        profile_data = {
            "model_name": selected_file.name,
            "model_path": str(selected_file.resolve()),
            "context_size": int(ctx_str),
            "vram_required_mb": model_size_mb,
        }
        PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROFILE_FILE, "w") as f:
            json.dump(profile_data, f, indent=4)

        kill_server()
        boot_server(
            model_path=profile_data["model_path"],
            context_size=profile_data["context_size"],
        )


@app.command()
def up():
    """Fast-boots the server using the last known safe hardware profile."""
    if not PROFILE_FILE.exists():
        print(
            "[-] No hardware profile found. Run 'twin build' first to profile your system."
        )
        raise typer.Exit(1)

    with open(PROFILE_FILE, "r") as f:
        profile = json.load(f)

    gpu = get_gpu_status()
    ram = get_system_ram_info()
    free_memory = (
        gpu["free_vram_mb"] if gpu["type"] in ["NVIDIA", "AMD"] else ram["free_mb"]
    )

    required_mb = profile["vram_required_mb"] + 200  # 200MB safety buffer

    print("⚡ HYPRTWIN FAST-BOOT")
    print(f"[*] Target Model: {profile['model_name']}")
    print(f"[*] Required VRAM: ~{required_mb} MB")
    print(f"[*] Available VRAM: {free_memory} MB")

    if free_memory >= required_mb:
        print("[+] VRAM check passed. Bypassing menus...")
        kill_server()
        boot_server(
            model_path=profile["model_path"], context_size=profile["context_size"]
        )
    else:
        print(
            "❌ ERROR: VRAM too low for cached profile. Close some apps or run 'twin build'."
        )
        raise typer.Exit(1)


@app.command()
def down():
    """Violently kills the background server to free VRAM."""
    kill_server()


@app.command()
def ask(
    query: Optional[List[str]] = typer.Argument(
        None, help="The question you want to ask the agent."
    ),
    quick: bool = typer.Option(
        False, "--quick", "-q", help="Bypass memory. Stateless, fast response."
    ),
    clear: bool = typer.Option(
        False, "--clear", "-c", help="Wipes the agent's short-term memory."
    ),
):
    """Talk to the agent. Supports terminal piping (e.g., ls | twin ask explain this)."""
    if clear:
        clear_history()
        print("[+] Short-term memory wiped cleanly.")
        if not query:
            return

    query_str = " ".join(query) if query else ""

    piped_data = None
    if not sys.stdin.isatty():
        max_bytes = 2097152  # 2MB limit
        try:
            # Read pure raw bytes from the buffer so Python doesn't implicitly crash
            raw_data = sys.stdin.buffer.read(max_bytes)

            # Safely decode, replacing non-text binary bytes with ''
            piped_data = raw_data.decode("utf-8", errors="replace").strip()

            # Check if there is more data remaining in the buffer
            if sys.stdin.buffer.read(1):
                print(
                    "[!] Warning: Piped input exceeded 2MB limit. Truncating safely to protect system memory.\n"
                )

        except AttributeError:
            # Fallback just in case sys.stdin doesn't have a buffer (rare environments)
            piped_data = sys.stdin.read(max_bytes).strip()
            if sys.stdin.read(1):
                print(
                    "[!] Warning: Piped input exceeded 2MB limit. Truncating safely.\n"
                )

    if not query_str and not piped_data:
        print("[-] Error: You must provide a question or pipe data into the command.")
        raise typer.Exit(1)

    ask_server(query_str, piped_context=piped_data, quick=quick)


if __name__ == "__main__":
    app()
