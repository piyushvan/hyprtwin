import json
import sys
from pathlib import Path
from typing import List, Optional

import questionary
import typer

from hyprtwin.api.client import ask_server, clear_history
from hyprtwin.core.engine import boot_server, kill_server
from hyprtwin.system.config import auto_discover, get_config, save_config
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
    """Smart setup to discover your binaries and model folders."""
    config = get_config()
    print("🛠️  HyprTwin Environment Setup")

    # 1. Discover Binaries
    potential_bins = auto_discover(subdir="build/bin")
    bin_choice = questionary.select(
        "Select your llama.cpp 'bin' folder (or choose 'Manual'):",
        choices=potential_bins + ["Manual Entry"],
    ).ask()

    if bin_choice == "Manual Entry":
        bin_path = questionary.path("Enter binary path:").ask()
    else:
        bin_path = bin_choice

    # 2. Discover Models
    potential_models = auto_discover()
    model_choice = questionary.select(
        "Select your model directory (or choose 'Manual'):",
        choices=potential_models + ["Manual Entry"],
    ).ask()

    if model_choice == "Manual Entry":
        model_path = questionary.path("Enter model path:").ask()
    else:
        model_path = model_choice

    # 3. Save
    config["bin_path"] = str(Path(bin_path).resolve())
    config["model_paths"] = [str(Path(model_path).resolve())]
    save_config(config)

    print("\n✅ Setup complete. Paths validated.")


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
def build(
    debug: bool = typer.Option(
        False, "--debug", help="Enable llama-server debug logging."
    ),
):
    """Profiles hardware, builds the agent, and caches the safe profile."""
    config = get_config()
    model_paths = config.get("model_paths", [])

    # 1. Find all .gguf files
    gguf_files = []
    for d in model_paths:
        p = Path(d).expanduser()
        if p.exists() and p.is_dir():
            gguf_files.extend(list(p.rglob("*.gguf")))

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
    safe_data = calculate_safe_context(str(selected_file.resolve()), model_size_mb)
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
        # Save the successful profile (FIXED DICTIONARY)
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
                debug=debug,
            )

            # ---------------------------------------------------------
            # NEW: The "Systems Online" Handshake
            # ---------------------------------------------------------
            print("\n[+] Triggering systems check...")
            ask_server(
                "You are HyprTwin. You just booted into bare-metal memory successfully. Say a very short, cool 'system online' greeting to the user.",
                quick=True,
            )


@app.command()
def up(
    debug: bool = typer.Option(
        False, "--debug", help="Enable llama-server debug logging."
    ),
):
    """Fast-boots the server using the last known safe hardware profile."""
    if not PROFILE_FILE.exists():
        print(
            "[-] No hardware profile found. Run 'twin build' first to profile your system."
        )
        raise typer.Exit(1)

    try:
        with open(PROFILE_FILE, "r") as f:
            profile = json.load(f)
    except json.JSONDecodeError:
        # FIX: Gracefully handle corrupted config files
        print("❌ ERROR: Hardware profile is corrupted or unreadable.")
        print("[!] Please run 'twin build' to generate a fresh, safe profile.")
        raise typer.Exit(1)

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
            model_path=profile["model_path"],
            context_size=profile["context_size"],
            debug=debug,
        )

        # ---------------------------------------------------------
        # NEW: The "Systems Online" Handshake
        # ---------------------------------------------------------
        print("\n[+] Triggering systems check...")
        ask_server(
            "You are HyprTwin. You just woke up from sleep successfully. Say a very short, cool 'system online' greeting to the user.",
            quick=True,
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
        None, help="The question you want to ask."
    ),
    quick: bool = typer.Option(False, "--quick", "-q", help="Stateless response."),
    clear: bool = typer.Option(False, "--clear", "-c", help="Wipe memory."),
):
    """Talk to the agent. Supports terminal piping."""
    if clear:
        clear_history()
        print("[+] Short-term memory wiped.")
        if not query:
            return

    query_str = " ".join(query) if query else ""

    # 1. Capture and Truncate Piped Data (line-safe, no mid-UTF8 splits)
    piped_data = None
    MAX_PIPED_CHARS = 500_000  # ~500KB of text, safe for most context windows
    if not sys.stdin.isatty():
        lines = []
        total_chars = 0
        for raw_line in sys.stdin:
            total_chars += len(raw_line)
            if total_chars > MAX_PIPED_CHARS:
                print(
                    "[!] Warning: Piped input truncated to ~500K chars to fit context window."
                )
                break
            lines.append(raw_line)
        piped_data = "".join(lines).strip() if lines else None

    if not query_str and not piped_data:
        print("[-] Error: You must provide a question or pipe data.")
        raise typer.Exit(1)

    # 2. Call the server with the new context-aware client
    ask_server(query_str, piped_context=piped_data, quick=quick)


if __name__ == "__main__":
    app()
