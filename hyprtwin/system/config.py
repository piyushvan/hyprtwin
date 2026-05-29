import json
import os
from pathlib import Path

# Centralized Path Definitions
BASE_DIR = Path("~/.local/share/twin").expanduser()
DB_PATH = str(BASE_DIR / "history.db")
PROFILE_PATH = str(BASE_DIR / "profile.json")
CONFIG_DIR = Path("~/.config/twin").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"


def get_common_paths():
    """Returns a list of common locations where users install llama.cpp and models."""
    home = Path.home()
    return [
        home / "models",
        home / "llama.cpp",
        home / "llama.cpp/build/bin",
        home / ".local/bin",
        home / "Downloads",
    ]


def auto_discover(subdir=""):
    """Scans common paths for directories that exist."""
    potential = get_common_paths()
    found = []
    for p in potential:
        target = p / subdir if subdir else p
        if target.exists():
            found.append(str(target))
    return found


def get_config():
    """Loads user configuration or returns defaults."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        # Default configuration
        default_config = {
            "bin_path": "",
            "model_paths": [str(Path("~/models").expanduser())],
        }
        save_config(default_config)
        return default_config

    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def save_config(config):
    """Saves the current configuration."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)


def get_binary_path(binary_name: str) -> str:
    """Helper to find llama.cpp binaries based on user config."""
    config = get_config()
    bin_path = Path(config.get("bin_path", "")).expanduser()
    full_path = bin_path / binary_name

    if not full_path.exists():
        print(f"[-] Error: Could not find {binary_name} at {full_path}")
        print("[!] Please run 'twin init' to reconfigure your paths.")
        sys.exit(1)

    return str(full_path)
