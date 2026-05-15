import json
import os
from pathlib import Path

CONFIG_DIR = Path("~/.config/twin/").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_config():
    """Load config or return defaults if it doesn't exist."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        default = {
            "bin_path": "",  # User will set this
            "model_paths": [str(Path("~/.local/share/twin/models").expanduser())],
            "flags": {"ngl": 99, "turbo_quant": True, "port": 8080},
        }
        save_config(default)
        return default

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)


def get_binary_path(binary_name="llama-server"):
    config = get_config()
    bin_path_str = config.get("bin_path", "").strip()

    if bin_path_str:
        # Expand '~' and get absolute path
        p = Path(bin_path_str).expanduser().resolve()

        # Scenario A: User pointed directly to the binary file
        if p.is_file() and p.name in ["llama-server", "server"]:
            return str(p)

        # Scenario B: User pointed to the folder
        if p.is_dir():
            for name in ["llama-server", "server"]:
                target = p / name
                if target.exists() and target.is_file():
                    return str(target)

        print(f"⚠️  Warning: Could not resolve llama-server in {bin_path_str}")

    return binary_name
