import ctypes
import sys
import time


def get_cuda_runtime():
    lib_names = ["libcudart.so", "libcudart.so.12", "libcudart.so.11.0"]
    for lib in lib_names:
        try:
            return ctypes.CDLL(lib)
        except OSError:
            continue
    print("[-] Error: Could not find libcudart.so.")
    sys.exit(1)


cudart = get_cuda_runtime()
cudart.cudaMalloc.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_size_t]
cudart.cudaMalloc.restype = ctypes.c_int
cudart.cudaFree.argtypes = [ctypes.c_void_p]
cudart.cudaFree.restype = ctypes.c_int

print("🦹 BARE-METAL VRAM THIEF ONLINE 🦹")

target_mb = 2500
chunk_size = 100 * 1024 * 1024  # 100 MB chunks to avoid contiguous memory fragmentation
pointers = []

print(f"[*] Attempting to steal {target_mb} MB of VRAM in 100MB chunks...")

for i in range(target_mb // 100):
    ptr = ctypes.c_void_p()
    result = cudart.cudaMalloc(ctypes.byref(ptr), chunk_size)
    if result == 0:
        pointers.append(ptr)
    else:
        print(
            f"[-] OOM hit! Managed to steal {i * 100} MB before running out of contiguous blocks."
        )
        break

print(f"\n[+] Success! Holding {len(pointers) * 100} MB of VRAM hostage.")
print("[!] Open a new terminal and run 'twin up'. It should block you!")
print("[!] Press Ctrl+C to release the memory.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[*] Releasing VRAM...")
    for ptr in pointers:
        cudart.cudaFree(ptr)
    print("[+] VRAM freed. Exiting.")
