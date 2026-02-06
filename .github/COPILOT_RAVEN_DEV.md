# CK3 Raven Dev Mode

**Mode:** `ck3raven-dev` | **Purpose:** Infrastructure development for CK3 Lens toolkit

---

## Your Role

You are an **autonomous development agent**. When given a task:
1. Analyze → Plan → **WRITE THE CODE** → Validate → Commit

Use `ck3_file(command="write/edit")` and `ck3_exec` to implement changes directly.

---

## Write Access

| Location | Access |
|----------|--------|
| `src/ck3raven/**`, `tools/**`, `qbuilder/**`, `scripts/**`, `tests/**`, `docs/**` | ✅ Write |
| `~/.ck3raven/wip/` | ✅ Write (no contract needed) |
| **ANY mod files** | ❌ **ABSOLUTE PROHIBITION** |

---

## Hard Rules

1. **No mod writes** - Cannot write to vanilla, workshop, or local mod files
2. **Use `ck3_exec`** - Not `run_in_terminal`
3. **Contracts required** - For writes outside WIP, open a contract first

---

## Key Tools

| Tool | Purpose |
|------|---------|
| `ck3_file(command="write/edit")` | Write/edit source files |
| `ck3_exec` | Run shell commands |
| `ck3_git` | Git operations |
| `ck3_search` | Search database |
| `ck3_qbuilder` | Build system control |

---

## Validation

Code is **NOT complete** until:
1. `get_errors` returns clean for modified files
2. `git commit` succeeds (pre-commit hook validates)

---

## Architecture Overview

```
src/ck3raven/
├── parser/      # Lexer + Parser (100% regex-free)
├── resolver/    # Conflict resolution (4 merge policies)
├── db/          # SQLite storage, FTS5 search
└── emulator/    # (Phase 2) Game state building

qbuilder/        # Build daemon (single-writer)
tools/ck3lens_mcp/  # MCP server (this)
tools/ck3lens-explorer/  # VS Code extension
```

**Key entry points:**
```python
from ck3raven.parser import parse_file, parse_source
from ck3raven.db.schema import get_connection
from ck3raven.db.playsets import create_playset
```

---

## Build System

```bash
# Check status
ck3_qbuilder(command="status")

# Start daemon
ck3_qbuilder(command="build")

# Fresh rebuild
python -m qbuilder daemon --fresh
```

---

## CK3 Merge Policies

| Policy | Behavior | Used By |
|--------|----------|---------|
| OVERRIDE | Last wins | ~95% of content |
| CONTAINER_MERGE | Lists append | on_action only |
| PER_KEY_OVERRIDE | Per-key last wins | localization |
| FIOS | First wins | GUI types |

---

## Wrong Mode?

If editing CK3 mod files (.txt, .yml) → switch to `ck3lens` mode.
