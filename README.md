# 🚀 HyprTwin V3.0

A bare-metal, mathematically-governed local AI built specifically for Linux laptops with strict 4GB VRAM limits (like the RTX 3050).

HyprTwin intercepts your terminal pipes, profiles your hardware in real-time, calculates exact KV Cache and Compute Buffer constraints, and safely boots a local AI socket without ever hitting a "CUDA Out of Memory" crash.

## 🧠 Under the Hood

* **Engine:** Powered by the [llama.cpp TurboQuant fork](https://github.com/ggerganov/llama.cpp) (using `--cache-type-k turbo4` and Flash Attention).
* **Recommended Model:** `Qwen2.5-Coder-3B-Instruct` (Q8 or Q5_K_M).
* **Memory:** Features a local SQLite memory database to remember terminal context between commands.
* **Shell Agnostic:** Works flawlessly on Fish.

## ⚡ Core Commands (The CLI)

HyprTwin is controlled entirely through the `twin` command.

* **`twin init`**: Links your `llama-server` binary and your model directory to the engine. Run this once after installation.
* **`twin scan`**: Runs a bare-metal scan to see exactly how much VRAM your OS is currently consuming.
* **`twin build`**: The core of HyprTwin. Calculates VRAM headroom, restricts the compute buffer (batch 512), enables Flash Attention, and boots the socket safely on `127.0.0.1:8080`.
* **`twin ask`**: Talk directly, or pipe terminal output into the model's brain. Retains short-term memory.
* *Example:* `ls -la | twin ask "Explain what these files are."`


* **`twin down`**: Violently kills the background C++ server and instantly frees up your VRAM.

## 🛠️ Installation & Setup

**Prerequisites:**

1. Python 3.10 or higher.
2. A compiled `llama-server` binary (TurboQuant fork highly recommended for 4GB GPUs).
3. Linux.

**Setup Instructions:**
Clone the repository and run the automated installer:

```bash
git clone https://github.com/YOUR_USERNAME/hyprtwin.git
cd hyprtwin
chmod +x scripts/install.sh
./scripts/install.sh

```

Activate the environment (use `.fish` for Fish, or leave blank for Bash/Zsh):

```bash
source .venv/bin/activate.fish

```

*Note: After activating, remember to run `twin init` to link your local models!*

---

## 🏗️ Development & Deployment

If you are forking or contributing to this project, please adhere to the deployment standards to prevent large files or sensitive data from being committed.

### `.gitignore` Reference

Ensure your root directory contains a `.gitignore` with the following rules to shield the repository from heavy binaries and databases:

```text
# Python Environments
.venv/
env/
__pycache__/
*.pyc
*.egg-info/
build/
dist/

# Local Memory & Logs
*.log
*.db
history.db

# OS / Editor Files
.DS_Store
.vscode/

# Models (Never upload these to GitHub)
*.gguf
*.bin

```

---

*Built for the terminal. Constrained by math. Powered by Open Source.*
