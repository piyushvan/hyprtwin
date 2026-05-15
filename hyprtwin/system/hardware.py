import os
import subprocess


def get_system_ram_mb() -> int:
    """Reads native Linux memory info to return available RAM in MB."""
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemAvailable" in line:
                    kb = int(line.split()[1])
                    return kb // 1024
    except Exception:
        pass
    return 0


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

    # Step 2: AMD Fallback
    try:
        subprocess.check_output(["rocm-smi"], text=True)
        # Placeholder: Further parsing needed for precise AMD VRAM
        return {"type": "AMD", "total_vram_mb": 0, "free_vram_mb": 0}
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # Step 3: CPU Fallback
    return {"type": "CPU", "total_vram_mb": 0, "free_vram_mb": 0}


def calculate_safe_context(model_size_mb: int) -> dict:
    gpu = get_gpu_status()

    # We default to NVIDIA math since you have a 3050
    free_vram = gpu["free_vram_mb"] if gpu["type"] == "NVIDIA" else get_system_ram_mb()

    headroom = free_vram - model_size_mb - 200  # 200MB safety buffer

    # Your exact fish script math: tokens = MiB / 0.008
    max_tokens = int(headroom / 0.008) if headroom > 0 else 0

    return {"headroom_mb": max(0, headroom), "max_tokens": max(0, max_tokens)}
