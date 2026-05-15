#!/usr/bin/env bash

echo "[*] Initializing HyprTwin V3.0 Bare-Metal Environment..."

# 1. Create the virtual environment
if [ ! -d ".venv" ]; then
    echo "[+] Creating Python virtual environment (.venv)..."
    python3 -m venv .venv
else
    echo "[*] Virtual environment already exists."
fi

# 2. Install dependencies and link the 'twin' command
echo "[+] Installing dependencies and linking CLI..."
.venv/bin/pip install -e .

echo "========================================================="
echo "[+] SUCCESS: HyprTwin V3.0 installed safely."
echo "[!] To start using the agent, activate the environment:"
echo "    source .venv/bin/activate.fish"
echo "    twin --help"
echo "========================================================="
