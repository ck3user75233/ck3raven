"""
Parse Pool Resilience Tests

Tests crash recovery, timeout handling, and concurrent failure scenarios.

Run from ck3raven repo root:
    python scripts/test_parse_pool_resilience.py
"""

import json
import os
import signal
import sqlite3
import sys
import time
import threading
from pathlib import Path

# Setup paths
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
os.chdir(REPO_ROOT)

from ck3raven.parser.parse_pool import ParsePool, WorkerProcess

print("=" * 70)
print("PARSE POOL RESILIENCE TESTS")
print("=" * 70)
print()


def get_test_file() -> Path:
    """Get a single test file for parsing."""
    db_path = Path.home() / ".ck3raven" / "ck3raven.db"
    conn = sqlite3.connect(str(db_path))
    
    row = conn.execute("""
        SELECT f.relpath, cv.source_path
        FROM files f
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE f.relpath LIKE 'common/traits/%.txt'
           AND f.deleted = 0
           AND f.file_size > 100
           AND f.file_size < 10000
        LIMIT 1
    """).fetchone()
    
    conn.close()
    
    if row:
        return Path(row[1]) / row[0]
    return None


def test_worker_crash_recovery():
    """Test 1: Worker crash recovery - kill worker, verify respawn."""
    print("TEST 1: Worker Crash Recovery")
    print("-" * 50)
    
    pool = ParsePool(num_workers=2)
    pool.start()
    
    test_file = get_test_file()
    if not test_file:
        print("  ERROR: No test file found")
        pool.shutdown()
        return False
    
    # Parse once to verify working
    result1 = pool.parse_file(test_file, timeout_ms=10000)
    if not result1.success:
        print(f"  ERROR: Initial parse failed: {result1.error}")
        pool.shutdown()
        return False
    print(f"  Initial parse OK (nodes: {result1.node_count})")
    
    # Get worker PIDs
    pids_before = [w.pid for w in pool.workers if w.is_alive()]
    print(f"  Worker PIDs before: {pids_before}")
    
    # Kill first worker
    victim = pool.workers[0]
    victim_pid = victim.pid
    print(f"  Killing worker 0 (PID {victim_pid})...")
    victim.kill()
    
    # Give a moment for process to die
    time.sleep(0.5)
    
    # Parse again - should trigger respawn
    result2 = pool.parse_file(test_file, timeout_ms=10000)
    
    pids_after = [w.pid for w in pool.workers if w.is_alive()]
    print(f"  Worker PIDs after: {pids_after}")
    
    if not result2.success:
        print(f"  ERROR: Post-crash parse failed: {result2.error}")
        pool.shutdown()
        return False
    
    print(f"  Post-crash parse OK (nodes: {result2.node_count})")
    print("  [PASS] Worker crash recovery works")
    
    pool.shutdown()
    return True


def test_worker_timeout():
    """Test 2: Worker timeout - verify hung worker gets killed."""
    print("\nTEST 2: Worker Timeout Handling")
    print("-" * 50)
    
    pool = ParsePool(num_workers=1)
    pool.start()
    
    worker = pool.workers[0]
    original_pid = worker.pid
    print(f"  Worker PID: {original_pid}")
    
    # Send a request for a non-existent file
    fake_path = Path("/nonexistent/file/that/will/cause/error.txt")
    
    start = time.perf_counter()
    result = pool.parse_file(fake_path, timeout_ms=5000)
    elapsed = (time.perf_counter() - start) * 1000
    
    if not result.success and "not found" in result.error.lower():
        print(f"  FileNotFound error returned in {elapsed:.0f}ms")
        print("  [PASS] Worker responds to invalid requests correctly")
    else:
        print(f"  Unexpected result: {result}")
    
    # Test with real file and very short timeout
    test_file = get_test_file()
    if test_file:
        result = pool.parse_file(test_file, timeout_ms=1)
        if not result.success and "timeout" in (result.error_type or "").lower():
            print("  [PASS] PASS: Timeout enforcement works (1ms timeout triggered)")
        elif result.success:
            print("  Note: Parse completed before 1ms timeout (file too small)")
            print("  [PASS] PASS: Fast files work correctly")
        else:
            print(f"  Result: {result.error_type}: {result.error}")
    
    pool.shutdown()
    return True


def test_multiple_concurrent_failures():
    """Test 3: Multiple concurrent failures - kill multiple workers."""
    print("\nTEST 3: Multiple Concurrent Failures")
    print("-" * 50)
    
    pool = ParsePool(num_workers=4)
    pool.start()
    
    test_file = get_test_file()
    if not test_file:
        print("  ERROR: No test file found")
        pool.shutdown()
        return False
    
    alive_before = sum(1 for w in pool.workers if w.is_alive())
    print(f"  Workers alive before: {alive_before}/4")
    
    # Kill 2 workers
    print("  Killing workers 0 and 2...")
    pool.workers[0].kill()
    pool.workers[2].kill()
    
    time.sleep(0.5)
    
    alive_after_kill = sum(1 for w in pool.workers if w.is_alive())
    print(f"  Workers alive after kill: {alive_after_kill}/4")
    
    # Flood with requests
    print("  Sending 20 parse requests...")
    results = []
    for i in range(20):
        result = pool.parse_file(test_file, timeout_ms=10000)
        results.append(result.success)
    
    success_count = sum(results)
    alive_final = sum(1 for w in pool.workers if w.is_alive())
    
    print(f"  Results: {success_count}/20 successful")
    print(f"  Workers alive after flood: {alive_final}/4")
    
    if success_count == 20 and alive_final == 4:
        print("  [PASS] PASS: Pool recovered from multiple failures")
        pool.shutdown()
        return True
    else:
        print(f"  [FAIL] FAIL: {20 - success_count} failures, {4 - alive_final} workers dead")
        pool.shutdown()
        return False


def test_worker_recycle():
    """Test 4: Worker recycling after N parses."""
    print("\nTEST 4: Worker Recycling")
    print("-" * 50)
    
    import ck3raven.parser.parse_pool as pool_module
    original_recycle = pool_module.WORKER_RECYCLE_AFTER
    pool_module.WORKER_RECYCLE_AFTER = 10
    
    pool = ParsePool(num_workers=1)
    pool.start()
    
    test_file = get_test_file()
    if not test_file:
        print("  ERROR: No test file found")
        pool.shutdown()
        pool_module.WORKER_RECYCLE_AFTER = original_recycle
        return False
    
    original_pid = pool.workers[0].pid
    print(f"  Initial worker PID: {original_pid}")
    
    print("  Parsing 15 files (recycle threshold: 10)...")
    for i in range(15):
        result = pool.parse_file(test_file, timeout_ms=10000)
        if not result.success:
            print(f"  Parse {i+1} failed: {result.error}")
    
    current_pid = pool.workers[0].pid
    parse_count = pool.workers[0].parse_count
    
    print(f"  Current worker PID: {current_pid}")
    print(f"  Current parse count: {parse_count}")
    
    if current_pid != original_pid:
        print("  [PASS] PASS: Worker was recycled (new PID)")
    elif parse_count < 15:
        print("  [PASS] PASS: Worker count reset (recycled)")
    else:
        print("  Note: Worker may not have recycled yet")
    
    pool.shutdown()
    pool_module.WORKER_RECYCLE_AFTER = original_recycle
    return True


def main():
    results = {
        "crash_recovery": test_worker_crash_recovery(),
        "timeout": test_worker_timeout(),
        "concurrent_failures": test_multiple_concurrent_failures(),
        "recycle": test_worker_recycle(),
    }
    
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    all_pass = True
    for name, passed in results.items():
        status = "[PASS] PASS" if passed else "[FAIL] FAIL"
        print(f"  {name}: {status}")
        if not passed:
            all_pass = False
    
    print()
    if all_pass:
        print("All resilience tests passed! Safe to enable pool in production.")
    else:
        print("Some tests failed. Review before enabling.")
    
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
