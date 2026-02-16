"""
QBuilder Performance Diagnostic - Prove Where Time Is Going

Run this from the ck3raven repo root:
    python scripts/qbuilder_diagnostic.py

This script measures:
A) Pure process spawn overhead (baseline)
B) Subprocess import/parse/serialize timing breakdown
C) Code path verification (__file__ locations)
D) Call graph for _run_parse_subprocess
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean, quantiles

# Ensure we're in repo root
REPO_ROOT = Path(__file__).parent.parent
os.chdir(REPO_ROOT)
sys.path.insert(0, str(REPO_ROOT / "src"))

PYTHON_EXE = sys.executable

print("=" * 70)
print("QBUILDER PERFORMANCE DIAGNOSTIC")
print("=" * 70)
print(f"Python executable: {PYTHON_EXE}")
print(f"Repo root: {REPO_ROOT}")
print(f"Working directory: {os.getcwd()}")
print()

# =============================================================================
# STEP A: Pure spawn overhead benchmark
# =============================================================================
print("STEP A: Pure Process Spawn Overhead (100 spawns of 'pass')")
print("-" * 70)

spawn_times = []
for i in range(100):
    start = time.perf_counter()
    proc = subprocess.run(
        [PYTHON_EXE, "-c", "pass"],
        capture_output=True,
        text=True,
    )
    elapsed = time.perf_counter() - start
    spawn_times.append(elapsed * 1000)  # ms
    if i % 20 == 0:
        print(f"  Progress: {i}/100...")

avg_spawn = mean(spawn_times)
p50, p95, p99 = quantiles(spawn_times, n=100)[49], quantiles(spawn_times, n=100)[94], quantiles(spawn_times, n=100)[98]

print(f"\nResults (100 spawns of 'python -c pass'):")
print(f"  Average:  {avg_spawn:.1f} ms")
print(f"  P50:      {p50:.1f} ms")
print(f"  P95:      {p95:.1f} ms")
print(f"  P99:      {p99:.1f} ms")
print(f"  Min:      {min(spawn_times):.1f} ms")
print(f"  Max:      {max(spawn_times):.1f} ms")
print()

# =============================================================================
# STEP B: Subprocess import/parse/serialize timing breakdown
# =============================================================================
print("STEP B: Subprocess Import/Parse/Serialize Timing Breakdown")
print("-" * 70)

# Find 5 test files (mix of small and large)
import sqlite3
db_path = Path.home() / ".ck3raven" / "ck3raven.db"
conn = sqlite3.connect(str(db_path))

# Get 5 files: 2 small, 2 medium, 1 large (by file size)
# Need to join files -> content_versions to get source_path
test_files = conn.execute("""
    SELECT f.file_id, f.relpath, cv.source_path, f.file_size
    FROM files f
    JOIN content_versions cv ON f.content_version_id = cv.content_version_id
    WHERE (f.relpath LIKE 'common/traits/%.txt'
       OR f.relpath LIKE 'common/scripted_effects/%.txt')
       AND f.deleted = 0
       AND f.file_size IS NOT NULL
    ORDER BY f.file_size
    LIMIT 5
""").fetchall()

if not test_files:
    # Fallback: any .txt files from vanilla
    test_files = conn.execute("""
        SELECT f.file_id, f.relpath, cv.source_path, f.file_size
        FROM files f
        JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE f.relpath LIKE 'common/%.txt'
           AND f.deleted = 0
           AND f.file_size IS NOT NULL
           AND cv.workshop_id IS NULL
        ORDER BY f.file_size
        LIMIT 5
    """).fetchall()

# Construct abspath from source_path + relpath
test_files_with_abspath = []
for file_id, relpath, source_path, file_size in test_files:
    abspath = str(Path(source_path) / relpath)
    test_files_with_abspath.append((file_id, relpath, abspath, file_size or 0))
test_files = test_files_with_abspath

conn.close()

# Instrumented subprocess code
INSTRUMENTED_CODE = '''
import json
import sys
import os
import time
from pathlib import Path

# Timing markers
t0 = time.perf_counter()

filepath = Path(sys.argv[1])

# Add src to path
repo_root = Path(os.environ.get("CK3RAVEN_ROOT", "."))
sys.path.insert(0, str(repo_root / "src"))

t_path_setup = time.perf_counter()

# Import parser
from ck3raven.parser.parser import parse_file as _parse_file
t_import_parser = time.perf_counter()

# Import serialization
from ck3raven.parser.ast_serde import serialize_ast, count_ast_nodes, deserialize_ast
t_import_serde = time.perf_counter()

# Verify code paths
import ck3raven
import ck3raven.parser
code_paths = {
    "ck3raven.__file__": ck3raven.__file__,
    "ck3raven.parser.__file__": ck3raven.parser.__file__,
}

# Check if db is imported (it shouldn't be!)
db_imported = "ck3raven.db" in sys.modules
if db_imported:
    import ck3raven.db
    code_paths["ck3raven.db.__file__"] = ck3raven.db.__file__

t_verify = time.perf_counter()

# Parse
ast_node = _parse_file(str(filepath))
t_parse = time.perf_counter()

# Serialize
ast_blob = serialize_ast(ast_node)
t_serialize = time.perf_counter()

# Deserialize + count (as done in production)
ast_dict = deserialize_ast(ast_blob)
node_count = count_ast_nodes(ast_dict)
t_count = time.perf_counter()

# Final JSON output
ast_str = ast_blob.decode('utf-8') if isinstance(ast_blob, bytes) else ast_blob
t_final = time.perf_counter()

result = {
    "success": True,
    "node_count": node_count,
    "timings_ms": {
        "path_setup": (t_path_setup - t0) * 1000,
        "import_parser": (t_import_parser - t_path_setup) * 1000,
        "import_serde": (t_import_serde - t_import_parser) * 1000,
        "verify_paths": (t_verify - t_import_serde) * 1000,
        "parse": (t_parse - t_verify) * 1000,
        "serialize": (t_serialize - t_parse) * 1000,
        "deserialize_count": (t_count - t_serialize) * 1000,
        "json_prep": (t_final - t_count) * 1000,
        "TOTAL_IN_SUBPROCESS": (t_final - t0) * 1000,
    },
    "code_paths": code_paths,
    "db_imported": db_imported,
    "sys_executable": sys.executable,
    "sys_path_0_3": sys.path[0:3],
}
print(json.dumps(result))
'''

print(f"Testing with {len(test_files)} files:\n")

all_timings = []
for file_id, relpath, abspath, file_size in test_files:
    print(f"File: {relpath}")
    print(f"  Size: {file_size:,} bytes")
    
    # Measure total wall time including spawn
    t_start = time.perf_counter()
    
    proc = subprocess.run(
        [PYTHON_EXE, "-c", INSTRUMENTED_CODE, abspath],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "CK3RAVEN_ROOT": str(REPO_ROOT)},
        cwd=str(REPO_ROOT),
    )
    
    t_end = time.perf_counter()
    total_wall_ms = (t_end - t_start) * 1000
    
    if proc.returncode != 0:
        print(f"  ERROR: {proc.stderr[:200]}")
        continue
    
    try:
        result = json.loads(proc.stdout.strip())
    except json.JSONDecodeError:
        print(f"  ERROR parsing output: {proc.stdout[:200]}")
        continue
    
    timings = result["timings_ms"]
    subprocess_total = timings["TOTAL_IN_SUBPROCESS"]
    spawn_overhead = total_wall_ms - subprocess_total
    
    print(f"  Timings (ms):")
    print(f"    Spawn overhead:     {spawn_overhead:8.1f} ms  (wall - subprocess)")
    print(f"    Path setup:         {timings['path_setup']:8.1f} ms")
    print(f"    Import parser:      {timings['import_parser']:8.1f} ms")
    print(f"    Import serde:       {timings['import_serde']:8.1f} ms")
    print(f"    Parse:              {timings['parse']:8.1f} ms")
    print(f"    Serialize:          {timings['serialize']:8.1f} ms")
    print(f"    Deserialize+count:  {timings['deserialize_count']:8.1f} ms")
    print(f"    -----------------------------------")
    print(f"    Subprocess total:   {subprocess_total:8.1f} ms")
    print(f"    WALL TOTAL:         {total_wall_ms:8.1f} ms")
    print(f"  Node count: {result['node_count']}")
    print(f"  DB imported: {result['db_imported']}")
    print()
    
    all_timings.append({
        "file": relpath,
        "size": file_size,
        "spawn_overhead_ms": spawn_overhead,
        "subprocess_total_ms": subprocess_total,
        "wall_total_ms": total_wall_ms,
        **timings,
    })

# =============================================================================
# STEP C: Code Path Verification
# =============================================================================
print("STEP C: Code Path Verification")
print("-" * 70)

if all_timings:
    # Use result from last file
    print(f"Code paths from subprocess:")
    for key, path in result["code_paths"].items():
        print(f"  {key}: {path}")
    print(f"\nDB module imported in subprocess: {result['db_imported']}")
    print(f"sys.executable: {result['sys_executable']}")
    print(f"sys.path[0:3]: {result['sys_path_0_3']}")
print()

# =============================================================================
# STEP D: Call graph for _run_parse_subprocess
# =============================================================================
print("STEP D: Where _run_parse_subprocess() Is Called")
print("-" * 70)

# grep for _run_parse_subprocess in repo
print("Searching for _run_parse_subprocess usage...")
grep_result = subprocess.run(
    ["git", "grep", "-n", "_run_parse_subprocess"],
    capture_output=True,
    text=True,
    cwd=str(REPO_ROOT),
)
print(grep_result.stdout if grep_result.stdout else "(no matches)")

print("\nSearching for parse_file/parse_text calls in qbuilder...")
grep_result2 = subprocess.run(
    ["git", "grep", "-n", "from.*runtime import\\|parse_file\\|parse_text"],
    capture_output=True,
    text=True,
    cwd=str(REPO_ROOT),
)
for line in grep_result2.stdout.split("\n"):
    if "qbuilder" in line or "worker" in line:
        print(f"  {line}")

# =============================================================================
# SUMMARY
# =============================================================================
print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"\nA) Pure spawn overhead (no imports): {avg_spawn:.1f} ms avg, {p95:.1f} ms p95")

if all_timings:
    avg_import = mean([t["import_parser"] + t["import_serde"] for t in all_timings])
    avg_parse = mean([t["parse"] for t in all_timings])
    avg_wall = mean([t["wall_total_ms"] for t in all_timings])
    avg_spawn_overhead = mean([t["spawn_overhead_ms"] for t in all_timings])
    
    print(f"B) Per-file breakdown (avg of {len(all_timings)} files):")
    print(f"   Spawn overhead:   {avg_spawn_overhead:6.1f} ms")
    print(f"   Import time:      {avg_import:6.1f} ms")
    print(f"   Parse time:       {avg_parse:6.1f} ms")
    print(f"   Wall total:       {avg_wall:6.1f} ms")
    
    print(f"\nC) Code path verification:")
    print(f"   Running from repo: {'YES' if 'ck3raven' in str(result.get('code_paths', {}).get('ck3raven.__file__', '')) else 'UNKNOWN'}")
    print(f"   DB imported:       {'NO (good!)' if not result.get('db_imported') else 'YES (bad!)'}")

print(f"\nD) Call graph: see above")

# Projection
print(f"\n{'='*70}")
print("PROJECTION FOR 25,000 FILES")
print("=" * 70)
if all_timings:
    files_25k_hours = (25000 * avg_wall / 1000) / 3600
    files_92k_hours = (92000 * avg_wall / 1000) / 3600
    print(f"At {avg_wall:.0f} ms/file:")
    print(f"  25,000 files: {files_25k_hours:.1f} hours")
    print(f"  92,000 files: {files_92k_hours:.1f} hours")
    
    # If we eliminated spawn overhead
    no_spawn_ms = avg_wall - avg_spawn_overhead
    files_25k_no_spawn = (25000 * no_spawn_ms / 1000) / 3600
    print(f"\nIf spawn overhead eliminated ({avg_spawn_overhead:.0f} ms saved/file):")
    print(f"  25,000 files: {files_25k_no_spawn:.1f} hours")
