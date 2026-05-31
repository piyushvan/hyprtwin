import json
import logging
import shutil
import subprocess
from pathlib import Path

from gguf import GGUFReader

# Configure logging (single instance)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def get_system_ram_info() -> dict:
    ram_info = {"total_mb": 0, "free_mb": 0}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if "MemTotal" in line:
                    ram_info["total_mb"] = int(line.split()[1]) // 1024
                elif "MemAvailable" in line:
                    ram_info["free_mb"] = int(line.split()[1]) // 1024
    except Exception as e:
        logging.warning(f"Could not read /proc/meminfo: {e}")
    return ram_info


def get_cpu_model() -> str:
    """Extracts CPU model name."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if "model name" in line:
                    return line.split(":")[1].strip()
    except Exception:
        pass
    return "Unknown CPU"


def get_gpu_status() -> dict:
    """Profiles GPU VRAM using NVIDIA or AMD tools, falls back to system RAM."""
    nvidia_smi = shutil.which("nvidia-smi")
    rocm_smi = shutil.which("rocm-smi")

    # NVIDIA path
    if nvidia_smi:
        try:
            mem_cmd = [
                nvidia_smi,
                "--query-gpu=memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ]
            mem_output = subprocess.check_output(mem_cmd, text=True).strip().split(",")
            total_mb = int(mem_output[0].strip())
            free_mb = int(mem_output[1].strip())

            processes = []
            try:
                app_cmd = [
                    nvidia_smi,
                    "--query-compute-apps=process_name,used_memory",
                    "--format=csv,noheader,nounits",
                ]
                app_output = (
                    subprocess.check_output(app_cmd, text=True).strip().split("\n")
                )
                for line in app_output:
                    parts = line.split(",")
                    if len(parts) >= 2:
                        processes.append(
                            {"name": parts[0].strip(), "used": parts[1].strip()}
                        )
            except subprocess.CalledProcessError:
                pass

            return {
                "type": "NVIDIA",
                "total_vram_mb": total_mb,
                "free_vram_mb": free_mb,
                "top_processes": processes,
            }
        except Exception as e:
            logging.error(f"Error querying NVIDIA GPU: {e}")

    # AMD ROCm path
    if rocm_smi:
        try:
            cmd = [rocm_smi, "--showmeminfo", "vram", "--json"]
            output = subprocess.check_output(cmd, text=True)
            data = json.loads(output)
            # Typical ROCm JSON structure: {"card0": {"VRAM Total (MB)": ..., "VRAM Used (MB)": ...}}
            total_mb = 0
            free_mb = 0
            for card in data.values():
                total_mb += int(card.get("VRAM Total (MB)", 0))
                used = int(card.get("VRAM Used (MB)", 0))
                free_mb += total_mb - used
            return {
                "type": "AMD",
                "total_vram_mb": total_mb,
                "free_vram_mb": free_mb,
                "top_processes": [],
            }
        except Exception as e:
            logging.error(f"Error querying AMD GPU: {e}")

    # Fallback to system RAM
    ram = get_system_ram_info()
    return {
        "type": "CPU",
        "total_vram_mb": 0,
        "free_vram_mb": ram["free_mb"],
        "top_processes": [],
    }


def calculate_safe_context(model_path: str, model_size_mb: int) -> dict:
    """
    Analyzes GGUF metadata to calculate precise VRAM cost per token.
    Uses the actual KV cache quantization settings from engine.py:
    - cache-type-k: turbo4 (4-bit -> 0.5 bytes per element)
    - cache-type-v: turbo3 (3-bit -> 0.375 bytes per element)
    """
    gpu = get_gpu_status()
    # Use free VRAM if discrete GPU, otherwise fallback to system RAM
    free_memory = (
        gpu["free_vram_mb"]
        if gpu["type"] in ("NVIDIA", "AMD")
        else get_system_ram_info()["free_mb"]
    )

    # 256 MB safety buffer for OS + compute scratchpad
    headroom_mb = free_memory - model_size_mb - 256

    if headroom_mb <= 0:
        return {"headroom_mb": 0, "max_tokens": 0}

    try:
        reader = GGUFReader(model_path)
        # Identify architecture (llama, qwen2, phi3, etc.)
        arch_bytes = reader.fields.get("general.architecture")
        if arch_bytes:
            arch = arch_bytes.parts[-1].tobytes().decode()
        else:
            raise ValueError("Could not determine model architecture")

        # Pull precise model parameters
        n_layer = int(reader.fields[f"{arch}.block_count"].parts[-1][0])
        n_head_kv = int(reader.fields[f"{arch}.attention.head_count_kv"].parts[-1][0])
        n_embd = int(reader.fields[f"{arch}.embedding_length"].parts[-1][0])
        n_head = int(reader.fields[f"{arch}.attention.head_count"].parts[-1][0])

        head_dim = n_embd // n_head

        # KV cache size in bytes per token:
        # K: 4-bit = 0.5 bytes, V: 3-bit = 0.375 bytes. Total 0.875 bytes per element.
        # Elements per token: n_layer * n_head_kv * head_dim (for K) + same for V.
        # But our formula already multiplies by 2 implicitly? Let's be explicit:
        # bytes_per_token = n_layer * n_head_kv * head_dim * (0.5 + 0.375)
        bytes_per_token = n_layer * n_head_kv * head_dim * 0.875
        # Add 10% safety margin for alignment and tensor overhead
        bytes_per_token *= 1.10
        mb_per_token = bytes_per_token / (1024 * 1024)

        max_tokens = int(headroom_mb / mb_per_token)

        logging.info(
            f"Model architecture '{arch}' detected. Max tokens: {max_tokens} (headroom: {headroom_mb} MB)"
        )
        return {"headroom_mb": max(0, headroom_mb), "max_tokens": max(0, max_tokens)}

    except Exception as e:
        logging.warning(
            f"Precise metadata calculation failed: {e}. Falling back to safe heuristic."
        )
        # Heuristic: ~0.008 MB per token (typical for 7B models). For 3.8B it's ~0.004, but safe overestimate.
        heuristic_mb_per_token = 0.008
        return {
            "headroom_mb": max(0, headroom_mb),
            "max_tokens": int(headroom_mb / heuristic_mb_per_token),
        }
