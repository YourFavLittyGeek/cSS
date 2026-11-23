"""tools/bench_transfer.py - Benchmark transfer mechanisms on macOS Apple Silicon.

Benchmarks:
1. shutil.copyfile (native macOS _fcopyfile)
2. shutil.copy2
3. /bin/cp
4. /bin/cp -c (APFS clone)
5. Custom bounded streaming (64KB, 256KB, 1MB, 4MB, 8MB) with in-flight SHA-256
6. rsync -a

Measures: elapsed time, MB/s throughput, peak RSS memory, CPU time.
"""

import os
import sys
import time
import shutil
import hashlib
import resource
import subprocess
from typing import Dict, Any, List


def get_peak_rss_mb() -> float:
    # On macOS, ru_maxrss is in bytes
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    return rusage.ru_maxrss / (1024 * 1024)


def time_block(fn):
    rss_before = get_peak_rss_mb()
    t0 = time.perf_counter()
    c0 = time.process_time()
    fn()
    t_elapsed = time.perf_counter() - t0
    c_elapsed = time.process_time() - c0
    rss_after = get_peak_rss_mb()
    return t_elapsed, c_elapsed, (rss_after - rss_before)


def run_benchmark():
    print("=" * 70)
    print("PERCIVAL TRANSFER BENCHMARK UTILITY (macOS Apple Silicon)")
    print("=" * 70)

    work_dir = os.path.expanduser("~/Percival_project/app_data/scratch/benchmarks")
    os.makedirs(work_dir, exist_ok=True)
    src_dir = os.path.join(work_dir, "src")
    dst_dir = os.path.join(work_dir, "dst")
    os.makedirs(src_dir, exist_ok=True)
    os.makedirs(dst_dir, exist_ok=True)

    # 1. Prepare test datasets
    # Dataset A: Large NIfTI-sized file (50 MB)
    large_file = os.path.join(src_dir, "volume_50mb.nii")
    with open(large_file, "wb") as f:
        f.write(os.urandom(50 * 1024 * 1024))
    large_mb = 50.0

    # Dataset B: 200 small DICOM-like files (250 KB each, total 50 MB)
    dicom_dir = os.path.join(src_dir, "dicom_series")
    os.makedirs(dicom_dir, exist_ok=True)
    for i in range(200):
        with open(os.path.join(dicom_dir, f"slice_{i:04d}.dcm"), "wb") as f:
            f.write(os.urandom(250 * 1024))
    dicom_mb = 200 * 250 / 1024

    results = []

    def bench_large(name, copy_fn):
        tgt = os.path.join(dst_dir, "test_large.bin")
        if os.path.exists(tgt):
            os.remove(tgt)
        t, c, delta_rss = time_block(lambda: copy_fn(large_file, tgt))
        rate = large_mb / t if t > 0 else 0.0
        results.append({"workload": "Large NIfTI (50MB)", "method": name, "time_s": t, "rate_mbs": rate, "cpu_s": c})
        print(f"  [Large NIfTI] {name:<35}: {t:8.4f}s ({rate:7.1f} MB/s) | CPU: {c:6.3f}s")
        if os.path.exists(tgt):
            os.remove(tgt)

    print("\n--- 1. Large NIfTI Workload (50 MB) ---")
    bench_large("shutil.copyfile (_fcopyfile)", shutil.copyfile)
    bench_large("shutil.copy2", shutil.copy2)
    bench_large("/bin/cp", lambda s, d: subprocess.run(["/bin/cp", s, d], check=True))
    bench_large("/bin/cp -c (APFS clone)", lambda s, d: subprocess.run(["/bin/cp", "-c", s, d], check=True))

    for buf_kb, buf_label in [(64, "64 KiB"), (256, "256 KiB"), (1024, "1 MiB"), (4096, "4 MiB"), (8192, "8 MiB")]:
        buf_size = buf_kb * 1024
        def stream_copy(s, d, bsize=buf_size):
            h = hashlib.sha256()
            with open(s, "rb") as fin, open(d, "wb") as fout:
                while chunk := fin.read(bsize):
                    h.update(chunk)
                    fout.write(chunk)
            return h.hexdigest()
        bench_large(f"Streaming {buf_label} + in-flight SHA-256", stream_copy)

    bench_large("rsync -a", lambda s, d: subprocess.run(["rsync", "-a", s, d], check=True))

    # Clean up benchmark scratch
    shutil.rmtree(work_dir, ignore_errors=True)
    print("\nBenchmark completed cleanly.")
    return results


if __name__ == "__main__":
    run_benchmark()
