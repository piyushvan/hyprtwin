import json
import os
import subprocess


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
        total, free = map(int, result.strip().split(","))
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


def calculate_safe_context(model_size_mb: int) -> dict:
    gpu = get_gpu_status()
    ram = get_system_ram_info()

    # Use GPU VRAM if available, otherwise fallback to System RAM
    if gpu["type"] in ["NVIDIA", "AMD"]:
        free_memory = gpu["free_vram_mb"]
    else:
        free_memory = ram["free_mb"]

    headroom = free_memory - model_size_mb - 200  # 200MB safety buffer

    # Tokens = MiB / 0.008
    max_tokens = int(headroom / 0.008) if headroom > 0 else 0

    return {"headroom_mb": max(0, headroom), "max_tokens": max(0, max_tokens)}
