import json
import logging
import sys
from functools import lru_cache  # NEW
from pathlib import Path
from typing import List

from pydantic import BaseModel, ValidationError

# Centralized Path Definitions
BASE_DIR = Path("~/.local/share/twin").expanduser()
DB_PATH = str(BASE_DIR / "history.db")
PROFILE_PATH = str(BASE_DIR / "profile.json")
CONFIG_DIR = Path("~/.config/twin").expanduser()
CONFIG_FILE = CONFIG_DIR / "config.json"

# Configure Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


class HyprTwinConfig(BaseModel):
    bin_path: str = ""
    model_paths: List[str] = [str(Path("~/models").expanduser())]


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


# NEW: Cache auto_discover results to avoid repeated filesystem scans
@lru_cache(maxsize=1)
def auto_discover(subdir=""):
    """Scans common paths for directories that exist. Results cached."""
    potential = get_common_paths()
    found = []
    for p in potential:
        target = p / subdir if subdir else p
        if target.exists():
            found.append(str(target))
    return found


def get_config() -> HyprTwinConfig:
    """Loads and validates configuration using Pydantic V2."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CONFIG_FILE.exists():
        default = HyprTwinConfig()
        save_config(default)
        return default

    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
            # Pydantic V2 uses model_validate
            return HyprTwinConfig.model_validate(data)
    except (ValidationError, json.JSONDecodeError, TypeError) as e:
        logging.error(f"Config corruption detected: {e}. Resetting to defaults.")
        default = HyprTwinConfig()
        save_config(default)
        return default


def save_config(config: HyprTwinConfig):
    """Saves the current configuration using V2's model_dump."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config.model_dump(), f, indent=4)


def get_binary_path(binary_name: str) -> str:
    """Helper to find llama.cpp binaries based on user config."""
    config = get_config()
    bin_path = Path(config.bin_path).expanduser()
    full_path = bin_path / binary_name

    if not full_path.exists():
        print(f"[-] Error: Could not find {binary_name} at {full_path}")
        print("[!] Please run 'twin init' to reconfigure your paths.")
        sys.exit(1)

    return str(full_path)
