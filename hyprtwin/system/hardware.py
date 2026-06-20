import json
import os
import subprocess

from gguf import GGUFReader

# --- Improvement 6: Dynamic CPU Thread Limiting ---


def get_safe_thread_count() -> int:
    """Returns a safe thread count for llama-server, leaving cores for the OS.

    Subtracts 2 cores from the total to prevent CPU pegging and thermal
    throttling on low-core laptops. Minimum of 1 thread.
    """
    total = os.cpu_count() or 2
    return max(1, total - 2)


def get_system_ram_info() -> dict:
    """Reads native Linux memory info to return total and available RAM in MB."""
    ram_info = {"total_mb": 0, "free_mb": 0}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    kb = int(line.split()[1])
                    ram_info["total_mb"] = kb // 1024
                elif "MemAvailable" in line:
                    kb = int(line.split()[1])
                    ram_info["free_mb"] = kb // 1024
    except Exception:
        pass
    return ram_info


def get_cpu_model() -> str:
    """Extracts the exact CPU model name from the Linux kernel."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
    except Exception:
        pass
    return "Unknown CPU"


def get_gpu_status() -> dict:
    """Cascading check for NVIDIA, AMD, and CPU-only VRAM states."""
    # Step 1: NVIDIA
    try:
        result = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            text=True,
        )
        primary_gpu_string = result.strip().split("\n")[0]
        total, free = map(int, primary_gpu_string.split(","))
        return {"type": "NVIDIA", "total_vram_mb": total, "free_vram_mb": free}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Step 2: AMD Fallback (rocm-smi)
    try:
        result = subprocess.check_output(
            ["rocm-smi", "--showmeminfo", "vram", "--json"], text=True
        )
        data = json.loads(result)

        # Grab the first GPU card dynamically (usually 'card0')
        card_key = list(data.keys())[0]
        card_data = data[card_key]

        total_bytes = int(card_data.get("VRAM Total Memory (B)", 0))
        used_bytes = int(card_data.get("VRAM Total Used Memory (B)", 0))

        total_mb = total_bytes // (1024 * 1024)
        used_mb = used_bytes // (1024 * 1024)
        free_mb = total_mb - used_mb

        return {"type": "AMD", "total_vram_mb": total_mb, "free_vram_mb": free_mb}
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        json.JSONDecodeError,
        KeyError,
        IndexError,
    ):
        pass

    # Step 3: CPU Fallback
    return {"type": "CPU", "total_vram_mb": 0, "free_vram_mb": 0}


def calculate_safe_context(model_path: str, model_size_mb: int) -> dict:
    gpu = get_gpu_status()
    ram = get_system_ram_info()

    if gpu["type"] in ["NVIDIA", "AMD"]:
        free_memory = gpu["free_vram_mb"]
    else:
        free_memory = ram["free_mb"]

    headroom_mb = free_memory - model_size_mb - 200  # 200MB safety buffer

    if headroom_mb <= 0:
        return {"headroom_mb": 0, "max_tokens": 0}

    try:
        # 🧠 DYNAMIC GGUF PARSING

        reader = GGUFReader(model_path)

        # Extract the model's specific architecture (e.g., 'llama', 'qwen2', 'phi3')
        arch = reader.fields["general.architecture"].parts[-1].tobytes().decode()

        # Dynamically pull the exact hardware constraints
        n_layer = int(reader.fields[f"{arch}.block_count"].parts[-1][0])
        n_head = int(reader.fields[f"{arch}.attention.head_count"].parts[-1][0])
        n_head_kv = int(reader.fields[f"{arch}.attention.head_count_kv"].parts[-1][0])
        n_embd = int(reader.fields[f"{arch}.embedding_length"].parts[-1][0])

        # Head Dimension
        d_head = n_embd / n_head

        # ⚙️ TURBO-QUANT MATH
        # turbo4 (Keys) = 0.5 bytes per parameter. turbo3 (Values) = 0.375 bytes per parameter.
        bytes_per_token = n_layer * n_head_kv * d_head * (0.5 + 0.375)
        mb_per_token = bytes_per_token / (1024 * 1024)

        max_tokens = int(headroom_mb / mb_per_token)

    except Exception as e:
        # Failsafe fallback just in case the .gguf file is corrupted or weirdly formatted
        max_tokens = int(headroom_mb / 0.008)

    return {"headroom_mb": max(0, headroom_mb), "max_tokens": max(0, max_tokens)}
