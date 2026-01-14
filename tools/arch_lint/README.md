# arch_lint v2.35

Modular architecture linter for ck3raven. Detects violations of canonical architecture.

## Quick Start

```bash
# Lint entire repo
python -m tools.arch_lint

# Lint specific directory
python -m tools.arch_lint src/

# JSON output
python -m tools.arch_lint --json

# Errors only (no warnings)
python -m tools.arch_lint --errors-only

# Daemon mode (continuous watch)
python -m tools.arch_lint --daemon
```

## Features

### v2.35 Capabilities

1. **Direct Term Scanning** — Detects banned terms using Python tokenizer (skips strings/comments)
2. **Composite Pattern Matching** — `active%local%mods` matches tokens in order with gaps
3. **Near-Window Detection** — Flags required tokens appearing within N positions
4. **Comment Intelligence** — Flags `# hack`, `# workaround`, `# fixme`, `# fallback`, `# legacy`
5. **Forbidden Filenames** — Catches duplicate policy engines (`*gates*.py`, `*approval*.py`)
6. **Path API Enforcement** — Flags `.relative_to()`, `Path.resolve()` outside WorldAdapter
7. **Enforcement Call-Sites** — Flags `enforce_policy()` outside boundary modules
8. **I/O & Mutator Detection** — Flags raw I/O and SQL/file/subprocess mutations
9. **Oracle Pattern Detection** — AST-based detection of `can_write`, `is_allowed`, etc.
10. **Fallback Pattern Detection** — Flags `else: ... visibility` patterns
11. **Concept Explosion** — Flags `Lens*`, `PlaysetLens`, `ScopeWorld` nouns
12. **Unused Symbol Detection** — Heuristic unused function/class detection
13. **Daemon Mode** — Continuous file watching with priority queue

## Module Structure

```
tools/arch_lint/
├── __init__.py      # Package marker, version
├── __main__.py      # Entry point
├── config.py        # Runtime configuration, allowlists
├── patterns.py      # Pure data: all banned terms, patterns, rules
├── scanner.py       # File walking, source loading, tokenization
├── analysis.py      # AST parsing, ModuleIndex building
├── rules.py         # Rule checking logic (applies patterns)
├── reporting.py     # Finding dataclass, output formatting
├── runner.py        # CLI orchestration
├── daemon.py        # File watch daemon
└── README.md        # This file
```

### Key Separation

- **patterns.py** — Edit this to add/remove banned terms and patterns (pure data, no logic)
- **rules.py** — Edit this to change how patterns are checked (logic)
- **analysis.py** — AST mechanics (rarely needs changes)
- **scanner.py** — File I/O mechanics (rarely needs changes)

## Waiver

Suppress specific findings with inline comment:

```python
path.resolve()  # CK3RAVEN_OS_PATH_OK: needed for absolute path in builder
```

## CLI Options

| Flag | Description |
|------|-------------|
| `--json` | Output as JSON |
| `--errors-only` | Only show ERROR severity |
| `--no-unused` | Skip unused symbol detection |
| `--no-deprecated` | Skip deprecated symbol detection |
| `--no-comments` | Skip comment keyword detection |
| `--daemon` | Run in continuous watch mode |
| `--interval N` | Daemon poll interval in seconds (default: 0.75) |
| `--full-scan-mins N` | Daemon full scan interval in minutes (default: 45) |

## Output Formats

### Human-Readable (Default)

```
arch_lint v2.35
Errors: 3  Warnings: 1

ERROR BANNED_ORACLE discovery.py:45:5 — Oracle: can_write pattern
    if can_write(path):
    -> Route through enforcement.py
ERROR IO-01 worker.py:93:17 [open] — Raw I/O call 'open(...)' outside allowed modules.
    with open(routing_path, 'r', encoding='utf-8') as f:
    -> Route I/O through handles minted by WorldAdapter.
ERROR MUTATOR-01 api.py:294:0 — SQL mutator detected outside builder/write-handle modules.
    conn.execute("DELETE FROM build_queue WHERE file_id = ?", (file_id,))
    -> Route DB writes through builder handles only.
WARN  SUSPICIOUS_COMMENT utils.py:88:1 — Comment contains suspicious keyword: 'hack'
    # hack: workaround for upstream bug
```

### JSON Output (`--json`)

```json
[
  {
    "rule_id": "BANNED_ORACLE",
    "severity": "ERROR",
    "path": "discovery.py",
    "line": 45,
    "col": 5,
    "message": "Oracle: can_write pattern",
    "evidence": "if can_write(path):",
    "symbol": null,
    "suggested_fix": "Route through enforcement.py"
  }
]
```

### Output Destinations

| Mode | Destination |
|------|-------------|
| Normal | stdout |
| `--json` | stdout (JSON array) |
| `--daemon` | stdout (real-time) + JSON log file |

Daemon mode writes to: `~/.ck3raven/logs/arch_lint/arch_lint_YYYYMMDD_HHMMSS.json`

## Daemon Mode

Requires `watchdog`:

```bash
pip install watchdog
# or
pip install -r tools/arch_lint/requirements.txt
```

Run:

```bash
python -m tools.arch_lint --daemon
```

### How Daemon Mode Works

1. **Startup**: Prints banner and begins watching the directory tree
   ```
   [arch_lint_daemon] watching C:\Users\dev\ck3raven
   [arch_lint_daemon] interval=0.75s debounce=2.0s full_scan=45m
   ```

2. **Real-time Linting**: When you save a `.py` file, errors appear in the terminal:
   ```
   [arch_lint_daemon] lint src/foo.py (queue=0)
   ERROR BANNED_ORACLE src/foo.py:12:4 — Oracle: can_write pattern
       if can_write(path):
   ```

3. **Periodic Full Scan**: Every 45 minutes (configurable), runs a complete scan:
   ```
   [arch_lint_daemon] full scan starting...
   arch_lint v2.35
   Errors: 5  Warnings: 12
   ...
   [arch_lint_daemon] full scan finished rc=1
   ```

4. **Stop**: Press `Ctrl+C` to stop the daemon

### Daemon Behavior

| Feature | Description |
|---------|-------------|
| **JSON Log File** | All findings written to `~/.ck3raven/logs/arch_lint/` |
| **Priority Queue** | Recently edited files are linted first |
| **Debouncing** | Rapid saves within 2 seconds are consolidated |
| **Skip Directories** | `.git`, `__pycache__`, `.venv`, `node_modules`, `.wip`, `archive` |
| **Full Scan** | Periodic complete scan (default every 45 min) |
| **Warning Limit** | Max 50 warnings shown per file in console |

### Log File Format

Each daemon session creates a timestamped JSON file:

```json
[
  {
    "type": "session_start",
    "timestamp": "2026-01-14T10:30:00.123456",
    "version": "2.35"
  },
  {
    "type": "lint_result",
    "timestamp": "2026-01-14T10:30:15.789012",
    "file": "src/foo.py",
    "error_count": 2,
    "warning_count": 1,
    "findings": [
      {
        "rule_id": "BANNED_ORACLE",
        "severity": "ERROR",
        "path": "src/foo.py",
        "line": 12,
        "col": 4,
        "message": "Oracle: can_write pattern"
      }
    ]
  },
  {
    "type": "full_scan",
    "timestamp": "2026-01-14T11:15:00.000000",
    "error_count": 5,
    "warning_count": 12
  }
]
```

## Adding New Rules

1. **Add pattern to `patterns.py`** — Add banned term, composite rule, or keyword
2. **Update `rules.py`** if new check type needed — Add new `check_*` function
3. **Call from `runner.py`** — Add to the main `run()` function

Example: Adding a banned term:

```python
# In patterns.py
BANNED_DIRECT_TERMS = {
    ...
    "my_new_banned_term",  # Add here
}
```

Example: Adding a composite pattern:

```python
# In patterns.py
COMPOSITE_RULES = [
    ...
    ("ERROR", "BANNED_COMPOSITE", "my%pattern%here", "Description of violation"),
]
```

## Rule Reference

### Error Rules

| Rule ID | Description | Remediation |
|---------|-------------|-------------|
| `BANNED_TERM` | Direct banned term in token stream | Remove/rename the term |
| `BANNED_ORACLE` | Oracle-style term (`can_write`, `is_allowed`, etc.) | Route through `enforcement.py` |
| `BANNED_PARALLEL` | Parallel authority structure (`local_mods`, `editable_mods`) | Use `mods[]` only |
| `BANNED_COMPOSITE` | Composite pattern match (tokens in order with gaps) | Refactor pattern |
| `BANNED_NEAR` | Near-window match (tokens within N positions) | Refactor pattern |
| `FORBIDDEN_FILENAME` | Banned filename pattern (`*gates*.py`, `*approval*.py`) | Rename file |
| `FORBIDDEN_PATH_API` | Path API outside WorldAdapter (`.relative_to()`, etc.) | Route through WorldAdapter |
| `FORBIDDEN_ENFORCE_CALL` | `enforce_policy()` call outside boundary modules | Move to enforcement boundary |
| `ORACLE-01` | AST-detected oracle function/variable | Remove capability oracle |
| `ORACLE-02` | Permission branching in if-condition | Remove permission pre-check |
| `TRUTH-01` | Parallel truth symbol | Use single source of truth |
| `CONCEPT-03` | Lens concept explosion (`PlaysetLens`, `ScopeWorld`) | Use canonical naming |
| `IO-01` | Raw I/O call outside allowed modules | Route through handles |
| `MUTATOR-01` | SQL mutator outside builder/write-handle | Route through builder |
| `MUTATOR-02` | Filesystem write outside builder/write-handle | Route through builder |
| `MUTATOR-03` | Subprocess/system call outside builder | Route through builder |
| `DANGEROUS_IO` | Dangerous I/O (`eval`, `subprocess.Popen`) | Use builder/tools only |
| `FALLBACK-01` | Fallback pattern (`else: ... visibility`) | Remove visibility fallback |

### Warning Rules

| Rule ID | Description |
|---------|-------------|
| `SUSPICIOUS_COMMENT` | Comment with `hack`, `fixme`, `workaround`, `legacy`, `fallback` |
| `UNUSED_SYMBOL` | Potentially unused function/class (heuristic) |
| `DEPRECATED_IMPORT` | Import of deprecated module |

## Banned Terms Reference

### Direct Terms (Exact Match)

These terms are banned when they appear as tokens (not in strings/comments):

```
mod_roots, is_writable, is_editable, is_allowed, is_path_allowed,
is_path_writable, writable_mod, editable_mod, whitelist, blacklist,
mod_whitelist, mod_blacklist, lens_cache, _lens_cache, invalidate_lens_cache,
_validate_visibility, _build_cv_filter, _derive_cvid, visible_cvids,
_load_legacy_playset, active_mod_paths
```

### Permission Oracles (Function/Variable Names)

Prefixes banned in function/variable names:

```
can_write, can_edit, can_delete, may_write, may_edit, may_delete,
is_writable, is_editable, is_deletable
```

### Parallel Authority Structures

Terms indicating parallel truth sources:

```
local_mods, editable_mods, writable_mods, live_mods, list_live_mods,
getLiveMods, LiveModInfo, no_lens
```

### Composite Patterns

Format: `token1%token2%token3` (matches tokens in order with gaps)

| Pattern | Violation |
|---------|-----------|
| `active%local%mods` | Parallel mod list |
| `mod%root` | Path oracle: mod root |
| `may%write` | Oracle: may_write pattern |
| `scope%visible` | Visibility scope oracle |
| `filter%visible` | Visibility filter oracle |

### Near-Window Patterns

Flags when required tokens appear within N positions:

| Tokens | Window | Violation |
|--------|--------|-----------|
| `['mod', 'root']` | 6 | Path oracle: mod root |
| `['is', 'visible']` | 4 | Visibility oracle |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | No errors (warnings allowed) |
| `1` | One or more errors found |
| `2` | Configuration or runtime error |

## Integration

### Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: arch-lint
        name: arch_lint
        entry: python -m tools.arch_lint --errors-only
        language: python
        types: [python]
        pass_filenames: false
```

### CI/CD

```yaml
# GitHub Actions example
- name: Architecture Lint
  run: python -m tools.arch_lint --errors-only --json > arch_lint_results.json
  
- name: Check for violations
  run: |
    if [ -s arch_lint_results.json ]; then
      echo "Architecture violations found"
      cat arch_lint_results.json
      exit 1
    fi
```

### VS Code Task

Add to `.vscode/tasks.json`:

```json
{
  "label": "arch_lint",
  "type": "shell",
  "command": "python",
  "args": ["-m", "tools.arch_lint", "--errors-only"],
  "problemMatcher": {
    "owner": "arch_lint",
    "pattern": {
      "regexp": "^(ERROR|WARN)\\s+(\\S+)\\s+(\\S+):(\\d+):(\\d+)\\s+—\\s+(.*)$",
      "severity": 1,
      "code": 2,
      "file": 3,
      "line": 4,
      "column": 5,
      "message": 6
    }
  }
}
```

## Architecture Context

This linter enforces the ck3raven canonical architecture documented in:

- [CANONICAL_ARCHITECTURE.md](../../docs/CANONICAL_ARCHITECTURE.md) — The 5 rules every agent must follow
- [CK3LENS_POLICY_ARCHITECTURE.md](../../docs/CK3LENS_POLICY_ARCHITECTURE.md) — Policy enforcement details

Key principles enforced:

1. **ONE enforcement boundary** — Only `enforcement.py` may deny operations
2. **NO permission oracles** — Never ask "am I allowed?" outside enforcement
3. **mods[] is THE mod list** — No parallel lists like `local_mods[]`
4. **WorldAdapter = resolution** — Resolves paths, NOT permission decisions
5. **Enforcement = decisions** — Decides allow/deny at execution time only
