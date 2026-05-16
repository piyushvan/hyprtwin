#!/usr/bin/env bash

echo "========================================================="
echo "🚀 Initializing HyprTwin V3.0 Bare-Metal Environment..."
echo "========================================================="

# 1. Python Version Check (Requires >= 3.10)
echo "[*] Checking Python version..."
if command -v python3 >/dev/null 2>&1; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    if $(python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"); then
        echo "[+] Python $PYTHON_VERSION detected. (Passed)"
    else
        echo "[-] Error: Python 3.10 or higher is required. Found Python $PYTHON_VERSION."
        exit 1
    fi
else
    echo "[-] Error: Python 3 is not installed on this system."
    exit 1
fi

# 2. System Dependency Check
echo "[*] Checking hardware telemetry tools..."
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "[!] Warning: 'nvidia-smi' not found. The hardware governor will safely fallback to RAM calculations."
else
    echo "[+] nvidia-smi detected."
fi

# 3. Scaffold Project Directories
echo "[*] Scaffolding configuration and memory directories..."
mkdir -p ~/.config/twin
mkdir -p ~/.local/share/twin
echo "[+] Ensured ~/.config/twin/ exists (Settings)"
echo "[+] Ensured ~/.local/share/twin/ exists (Logs & Memory)"

# 4. Virtual Environment Creation
if [ ! -d ".venv" ]; then
    echo "[+] Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "[*] Virtual environment already exists. Skipping creation."
fi

# 5. Package Installation
echo "[+] Installing dependencies and linking CLI..."
.venv/bin/pip install -e . --quiet

# 6. Dynamic Shell Detection for Activation
USER_SHELL=$(basename "$SHELL")
if [ "$USER_SHELL" = "fish" ]; then
    ACTIVATE_CMD="source .venv/bin/activate.fish"
elif [ "$USER_SHELL" = "csh" ] || [ "$USER_SHELL" = "tcsh" ]; then
    ACTIVATE_CMD="source .venv/bin/activate.csh"
else
    ACTIVATE_CMD="source .venv/bin/activate" # Standard for Bash/Zsh
fi

echo "========================================================="
echo "✅ SUCCESS: HyprTwin V3.0 installed safely."
echo "========================================================="
echo "[!] To start using the agent, run this command:"
echo "    $ACTIVATE_CMD"
echo ""
echo "[i] Then initialize your environment:"
echo "    twin init"
echo "========================================================="
