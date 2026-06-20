#!/usr/bin/env bash
set -euo pipefail

echo "========================================================="
echo "🚀 Initializing HyprTwin V3.1 Bare-Metal Environment..."
echo "========================================================="

# 1. Python Version Check (Requires >= 3.10)
echo "[*] Checking Python version..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"; then
        echo "[+] Python $PYTHON_VERSION detected. (Passed)"
    else
        echo "[-] Error: Python 3.10 or higher is required. Found Python $PYTHON_VERSION."
        exit 1
    fi
else
    echo "[-] Error: Python 3 is not installed on this system."
    exit 1
fi

# 2. Check for python3-venv (common missing package on Debian/Ubuntu)
echo "[*] Checking for python3-venv module..."
if ! python3 -c "import venv" 2>/dev/null; then
    echo "[-] Error: The 'venv' module is missing."
    echo "[!] On Debian/Ubuntu, install it with:"
    echo "    sudo apt install python3-venv"
    echo "[!] On Fedora/RHEL:"
    echo "    sudo dnf install python3-libs"
    exit 1
fi
echo "[+] python3-venv module found."

# 3. System Dependency Check
echo "[*] Checking hardware telemetry tools..."
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[!] Warning: 'nvidia-smi' not found. The hardware governor will safely fallback to RAM calculations."
else
    echo "[+] nvidia-smi detected."
fi

# 4. Scaffold Project Directories (XDG compliant)
echo "[*] Scaffolding configuration and memory directories..."
mkdir -p ~/.config/twin
mkdir -p ~/.local/share/twin
mkdir -p ~/.local/state/twin
echo "[+] Ensured ~/.config/twin/ exists (Settings)"
echo "[+] Ensured ~/.local/share/twin/ exists (Logs & Memory)"
echo "[+] Ensured ~/.local/state/twin/ exists (PID state)"

# 5. Installation Method
echo ""
echo "========================================================="
echo "📦 Installation"
echo "========================================================="

if command -v pipx >/dev/null 2>&1; then
    echo "[+] 'pipx' detected — using pipx for isolated installation."
    pipx install --force .
    echo "[+] Installed 'twin' CLI via pipx. It is now available globally."
else
    echo "[!] 'pipx' not found. Falling back to venv installation."
    echo "[*] (Recommended: install pipx with 'pip install --user pipx' for cleaner CLI management)"
    echo ""

    # Virtual Environment Creation
    if [ ! -d ".venv" ]; then
        echo "[+] Creating Python virtual environment (.venv)..."
        python3 -m venv .venv
    else
        echo "[*] Virtual environment already exists. Skipping creation."
    fi

    # Package Installation
    echo "[+] Installing dependencies and linking CLI..."
    .venv/bin/pip install . --quiet

    # Dynamic Shell Detection for Activation
    USER_SHELL=$(basename "$SHELL")
    if [ "$USER_SHELL" = "fish" ]; then
        ACTIVATE_CMD="source .venv/bin/activate.fish"
    elif [ "$USER_SHELL" = "csh" ] || [ "$USER_SHELL" = "tcsh" ]; then
        ACTIVATE_CMD="source .venv/bin/activate.csh"
    else
        ACTIVATE_CMD="source .venv/bin/activate" # Standard for Bash/Zsh
    fi

    # Global CLI Link
    echo "[*] Setting up global terminal access..."
    mkdir -p ~/.local/bin
    ln -sf "$PWD/.venv/bin/twin" ~/.local/bin/twin
    echo "[+] Linked 'twin' to ~/.local/bin/twin so it works from anywhere."
fi

echo "========================================================="
echo "✅ SUCCESS: HyprTwin V3.1 installed safely."
echo "========================================================="
echo "[!] IMPORTANT: Ensure ~/.local/bin is in your PATH."
echo "    If 'twin' doesn't run globally, add this to your shell config:"
echo ""
echo "    # Bash/Zsh:"
echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
echo ""
echo "    # Fish:"
echo "    set -U fish_user_paths ~/.local/bin \$fish_user_paths"
echo "========================================================="
