import os
import sys

# Ensure the script can find our local hyprtwin module
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from hyprtwin.system.hardware import (
    calculate_safe_context,
    get_cpu_model,
    get_gpu_status,
    get_system_ram_mb,
)

print("=== 🚀 HYPRTWIN V3.0: BARE-METAL TELEMETRY TEST ===")

cpu = get_cpu_model()
print(f"[+] CPU Model: {cpu}")

ram = get_system_ram_mb()
print(f"[+] System RAM: {ram} MB")

gpu = get_gpu_status()
print(f"[+] GPU Type: {gpu['type']}")
print(f"[+] GPU Total VRAM: {gpu['total_vram_mb']} MB")
print(f"[*] GPU Free VRAM: {gpu['free_vram_mb']} MB")

# Simulating booting Qwen 2.5 Coder 3B (~1900 MB)
model_size = 1900
safe_ctx = calculate_safe_context(model_size_mb=model_size)
print(f"[*] Safe Context Headroom for a {model_size}MB model: {safe_ctx} MB")
print("=========================================================")
