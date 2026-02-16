"""
A/B Throughput Benchmark: Legacy subprocess vs Persistent Pool

This script compares:
- Legacy: subprocess.run() per file (current default)
- Pool: Persistent worker pool with JSON line protocol

Run from ck3raven repo root:
    python scripts/benchmark_parse_pool.py

Expected results:
- Legacy: ~120-180ms per file (spawn + import dominated)
- Pool: ~5-30ms per file (pure parse time)
"""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from statistics import mean, stdev, quantiles

# Setup paths
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
os.chdir(REPO_ROOT)

print("=" * 70)
print("PARSE POOL A/B BENCHMARK")
print("=" * 70)
print(f"Repo root: {REPO_ROOT}")
print()


def get_test_files(n: int = 100) -> list:
    """Get N test files from database."""
    db_path = Path.home() / ".ck3raven" / "ck3raven.db"
    conn = sqlite3.connect(str(db_path))
    
    # Get files from any content version
    rows = conn.execute("""
        SELECT f.file_id, f.relpath, cv.source_path, f.file_size
        FROM files f
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE f.relpath LIKE 'common/%.txt'
           AND f.deleted = 0
           AND f.file_size IS NOT NULL
           AND f.file_size > 100
           AND f.file_size < 50000
        ORDER BY RANDOM()
        LIMIT ?
    """, (n,)).fetchall()
    
    conn.close()
    
    result = []
    for file_id, relpath, source_path, file_size in rows:
        abspath = Path(source_path) / relpath
        if abspath.exists():
            result.append({
                "file_id": file_id,
                "relpath": relpath,
                "abspath": abspath,
                "size": file_size,
            })
    
    return result


def benchmark_legacy(files: list) -> dict:
    """Benchmark legacy subprocess-per-file parsing."""
    from ck3raven.parser.runtime import parse_file, DEFAULT_PARSE_TIMEOUT
    
    times = []
    errors = 0
    
    print(f"[Legacy] Parsing {len(files)} files...")
    start_total = time.perf_counter()
    
    for i, f in enumerate(files):
        start = time.perf_counter()
        try:
            result = parse_file(f["abspath"], timeout=DEFAULT_PARSE_TIMEOUT)
            if not result.success:
                errors += 1
        except Exception:
            errors += 1
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        
        if (i + 1) % 25 == 0:
            print(f"  Progress: {i + 1}/{len(files)}")
    
    total_time = time.perf_counter() - start_total
    
    return {
        "method": "legacy",
        "files": len(files),
        "errors": errors,
        "total_sec": total_time,
        "files_per_sec": len(files) / total_time,
        "avg_ms": mean(times),
        "stdev_ms": stdev(times) if len(times) > 1 else 0,
        "p50_ms": quantiles(times, n=100)[49] if len(times) >= 100 else mean(times),
        "p95_ms": quantiles(times, n=100)[94] if len(times) >= 100 else max(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def benchmark_pool(files: list) -> dict:
    """Benchmark persistent worker pool parsing."""
    from ck3raven.parser.parse_pool import ParsePool
    
    pool = ParsePool(num_workers=4)
    pool.start()
    
    times = []
    errors = 0
    
    print(f"[Pool] Parsing {len(files)} files...")
    start_total = time.perf_counter()
    
    for i, f in enumerate(files):
        start = time.perf_counter()
        try:
            result = pool.parse_file(f["abspath"], timeout_ms=30000)
            if not result.success:
                errors += 1
        except Exception:
            errors += 1
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
        
        if (i + 1) % 25 == 0:
            print(f"  Progress: {i + 1}/{len(files)}")
    
    total_time = time.perf_counter() - start_total
    
    pool.shutdown()
    
    return {
        "method": "pool",
        "files": len(files),
        "errors": errors,
        "total_sec": total_time,
        "files_per_sec": len(files) / total_time,
        "avg_ms": mean(times),
        "stdev_ms": stdev(times) if len(times) > 1 else 0,
        "p50_ms": quantiles(times, n=100)[49] if len(times) >= 100 else mean(times),
        "p95_ms": quantiles(times, n=100)[94] if len(times) >= 100 else max(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def print_results(legacy: dict, pool: dict):
    """Print comparison results."""
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    print(f"\n{'Metric':<25} {'Legacy':<20} {'Pool':<20} {'Speedup':<15}")
    print("-" * 80)
    
    def row(name, l_val, p_val, fmt=".1f", suffix=""):
        if isinstance(l_val, (int, float)) and isinstance(p_val, (int, float)) and p_val > 0:
            speedup = l_val / p_val
            speedup_str = f"{speedup:.2f}x"
        else:
            speedup_str = "-"
        print(f"{name:<25} {l_val:{fmt}}{suffix:<10} {p_val:{fmt}}{suffix:<10} {speedup_str:<15}")
    
    row("Total time", legacy["total_sec"], pool["total_sec"], ".2f", " sec")
    row("Files/second", legacy["files_per_sec"], pool["files_per_sec"], ".1f", "")
    row("Avg ms/file", legacy["avg_ms"], pool["avg_ms"], ".1f", " ms")
    row("P50 ms/file", legacy["p50_ms"], pool["p50_ms"], ".1f", " ms")
    row("P95 ms/file", legacy["p95_ms"], pool["p95_ms"], ".1f", " ms")
    row("Min ms/file", legacy["min_ms"], pool["min_ms"], ".1f", " ms")
    row("Max ms/file", legacy["max_ms"], pool["max_ms"], ".1f", " ms")
    
    print(f"\nErrors: Legacy={legacy['errors']}, Pool={pool['errors']}")
    
    # Projection
    speedup = legacy["avg_ms"] / pool["avg_ms"] if pool["avg_ms"] > 0 else 0
    print(f"\n{'='*70}")
    print("PROJECTION FOR FULL BUILD")
    print("=" * 70)
    
    for n_files in [25000, 92000]:
        legacy_hours = (n_files * legacy["avg_ms"] / 1000) / 3600
        pool_hours = (n_files * pool["avg_ms"] / 1000) / 3600
        print(f"{n_files:,} files:")
        print(f"  Legacy: {legacy_hours:.1f} hours")
        print(f"  Pool:   {pool_hours:.1f} hours ({speedup:.1f}x faster)")


def main():
    # Get test files
    print("Loading test files from database...")
    files = get_test_files(100)
    print(f"Found {len(files)} test files")
    
    if len(files) < 50:
        print("ERROR: Not enough test files found")
        return
    
    total_size = sum(f["size"] for f in files)
    print(f"Total size: {total_size:,} bytes")
    print()
    
    # Run benchmarks
    legacy_results = benchmark_legacy(files)
    print()
    pool_results = benchmark_pool(files)
    
    # Print comparison
    print_results(legacy_results, pool_results)


if __name__ == "__main__":
    main()
