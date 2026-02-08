# QBuilder Benchmarks & Diagnostics

This folder contains testing and diagnostic tools for the QBuilder parse pool.
These are **NOT production code** - they are used to verify performance and diagnose issues.

## Files

### `benchmark_parse_pool.py`
A/B benchmark comparing legacy subprocess-per-file vs persistent parse pool.

**Usage:**
```bash
cd ck3raven
python tests/benchmarks/benchmark_parse_pool.py
```

**Expected Results:**
- Legacy: ~120-180ms per file (subprocess spawn + import dominated)
- Pool: ~5-30ms per file (pure parse time)
- Speedup: 4-10x depending on file complexity

### `test_parse_pool_resilience.py`
Tests pool crash recovery and worker replacement.

**Usage:**
```bash
python tests/benchmarks/test_parse_pool_resilience.py
```

**Tests:**
- Worker crashes are detected and workers are replaced
- Pool maintains throughput after worker failures
- Graceful shutdown works correctly

### `qbuilder_diagnostic.py`
Diagnostic tool for inspecting QBuilder state.

**Usage:**
```bash
python tests/benchmarks/qbuilder_diagnostic.py
```

**Shows:**
- Build queue status (pending, leased, failed)
- Worker pool health
- Recent parse errors
- Database statistics

## When to Use

- **Performance regression**: Run `benchmark_parse_pool.py` to verify pool is faster
- **Build failures**: Run `qbuilder_diagnostic.py` to see queue/worker status  
- **After changes to parse_pool.py**: Run resilience tests

## Note

These are standalone scripts, not pytest tests. They interact with the live database
and daemon, so run them in a development environment.
