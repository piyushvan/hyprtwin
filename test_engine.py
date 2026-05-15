import os
import sys
import time
from pathlib import Path

import typer

# Ensure the script can find our local hyprtwin module
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from hyprtwin.core.engine import boot_server, kill_server
from hyprtwin.system.hardware import calculate_safe_context

app = typer.Typer()

DEFAULT_MODEL_DIR = Path("~/.local/share/twin/models/").expanduser()


@app.command()
def manage_engine(
    action: str = typer.Argument(..., help="'boot' or 'kill'"),
    model: Path = typer.Option(
        None, "--model", "-m", help="Custom path to your .gguf model file"
    ),
):
    print("=== 🚀 HYPRTWIN V3.0: ENGINE TEST ===")

    if action.lower() == "kill":
        kill_server()
        return

    if action.lower() == "boot":
        # 1. Resolve the model path
        if model is None:
            # Fallback to checking the default directory for any .gguf file
            if DEFAULT_MODEL_DIR.exists():
                models = list(DEFAULT_MODEL_DIR.glob("*.gguf"))
                if models:
                    model = models[0]  # Just grab the first one for testing
                else:
                    print(f"[!] Error: No models found in default {DEFAULT_MODEL_DIR}")
                    raise typer.Abort()
            else:
                print(
                    f"[!] Error: Default directory {DEFAULT_MODEL_DIR} does not exist. Use --model."
                )
                raise typer.Abort()

        # 2. Strict Validation
        if not model.exists() or not model.is_file():
            print(f"[!] Error: Model file not found at {model}")
            raise typer.Abort()

        if model.suffix.lower() != ".gguf":
            print(f"[!] Error: File must be a .gguf format.")
            raise typer.Abort()

        # 3. Dynamic Telemetry
        model_size_mb = model.stat().st_size // (1024 * 1024)
        print(f"[*] Selected Model: {model.name} ({model_size_mb} MB)")

        safe_ctx = calculate_safe_context(model_size_mb)
        print(f"[*] Hardware Math: Safe Context set to {safe_ctx} tokens/MB")

        if safe_ctx <= 0:
            print("[!] Error: Not enough free VRAM to boot this model safely.")
            raise typer.Abort()

        # 4. Fire the Engine
        boot_server(model_path=str(model.resolve()), context_size=safe_ctx)

        print(
            "\n[+] Test complete. The C++ socket is now running detached in the background."
        )
        print("[!] To stop it, run: python test_engine.py kill")


if __name__ == "__main__":
    app()
