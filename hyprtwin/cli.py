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
    get_system_ram_mb,
)

app = typer.Typer(
    no_args_is_help=True, help="Twin: Maximized for 4GB VRAM. Strictly Linux Native."
)


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
    print("=== 🚀 HYPRTWIN V3.0: BARE-METAL TELEMETRY ===")
    print(f"[+] CPU Model: {get_cpu_model()}")
    print(f"[+] System RAM: {get_system_ram_mb()} MB")
    gpu = get_gpu_status()
    print(f"[+] GPU Type: {gpu['type']}")
    print(f"[+] GPU Total VRAM: {gpu['total_vram_mb']} MB")
    print(f"[*] GPU Free VRAM: {gpu['free_vram_mb']} MB")
    print("==============================================")


@app.command()
def build():
    """Profiles hardware and builds your custom system-aware agent."""
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

    # 4. Context Window Selection (Power of 2 Filter)
    master_powers = [1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072]

    # Only keep the powers of 2 that are less than or equal to your max calculated tokens
    valid_choices = [str(p) for p in master_powers if p <= safe_data["max_tokens"]]

    if not valid_choices:
        valid_choices = [str(safe_data["max_tokens"])]  # Failsafe

    ctx_str = questionary.select(
        "📏 Select Context Window Size (Strict Powers of 2):",
        choices=valid_choices,
        default=valid_choices[-1],  # Defaults to the largest safe option
    ).ask()

    if not ctx_str:
        raise typer.Exit()

    # 5. Boot the Server
    confirm = questionary.confirm(
        "🚀 Boot the bare-metal socket with these parameters?"
    ).ask()
    if confirm:
        kill_server()
        boot_server(model_path=str(selected_file.resolve()), context_size=int(ctx_str))


@app.command()
def down():
    """Violently kills the background server to free VRAM."""
    kill_server()


@app.command()
def ask(
    # Tell Typer to accept multiple words as a list
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

    # The Fix: Stitch the unquoted words together with spaces
    query_str = " ".join(query) if query else ""

    piped_data = None
    if not sys.stdin.isatty():
        piped_data = sys.stdin.read().strip()

    if not query_str and not piped_data:
        print("[-] Error: You must provide a question or pipe data into the command.")
        raise typer.Exit(1)

    ask_server(query_str, piped_context=piped_data, quick=quick)


if __name__ == "__main__":
    app()
