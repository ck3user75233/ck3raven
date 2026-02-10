# CK3 Raven Dev Mode — Agent Instructions

**Mode:** `ck3raven-dev` | **Purpose:** Develop and maintain the ck3raven toolchain — a Python-based parser, resolver, SQLite database, MCP server, and VS Code extension that together power CK3 Lens for AI-assisted CK3 modding.

---

## Your Role

Autonomous development agent. When given a task: Analyze → Plan → **Write code** → Validate → Commit.

---

## Write Access (Canonical Domains)

Mutations require a contract (`ck3_contract`), except writes to `~/.ck3raven/wip/`.

| Domain | Access | Notes |
|--------|--------|-------|
| `ROOT_REPO` | Read/Write/Delete | ck3raven source — all directories |
| `ROOT_CK3RAVEN_DATA` | Mixed | `wip/`, `config/`, `playsets/`, `logs/`, `journal/`, `cache/`, `artifacts/` are writable; `db/` and `daemon/` are read-only (owned by QBuilder daemon) |
| `ROOT_GAME`, `ROOT_STEAM` | Read-only | Vanilla and workshop content for testing/reference |
| `ROOT_USER_DOCS` | Read-only | User's mod folder — **no writes in dev mode** |

📖 Full matrix: `tools/ck3lens_mcp/ck3lens/capability_matrix.py`

---

## Tools

| Tool | Purpose |
|------|---------|
| `ck3_file` | Read/write/edit source files |
| `ck3_exec` | Run shell commands (policy-enforced) |
| `ck3_git` | Git operations on ck3raven repo |
| `ck3_search` | Search mod database (symbols, content, files) |
| `ck3_db_query` | Direct database queries |
| `ck3_qbuilder` | Build daemon control (status, build, discover, stop) |
| `ck3_validate` | Syntax validation (CK3 script and Python) |
| `ck3_vscode` | VS Code/Pylance diagnostics |
| `ck3_contract` | Open/close work contracts for mutations |
| `ck3_logs` | ck3raven component logs (MCP, extension, daemon) |
| `ck3_parse_content` | Parse CK3 script → AST |

---

## Validation

Code is **not complete** until:
1. Pylance diagnostics clean (`ck3_vscode(command="diagnostics")` or VS Code's `get_errors`)
2. `ck3_git(command="commit")` succeeds

---

## Architecture

```
src/ck3raven/
├── parser/      # Lexer + parser (100% regex-free, error-recovering)
├── resolver/    # Conflict resolution and merge policy engine
├── db/          # SQLite schema, FTS5 search, symbol/ref storage
├── analyzers/   # Error log parsing, log analysis
├── core/        # Shared utilities
├── logs/        # Log management
├── emulator/    # (Future) Game state building
└── tools/       # Internal tooling

qbuilder/              # Build daemon (single-writer architecture)
tools/ck3lens_mcp/     # MCP server (28+ tools exposed to Copilot)
tools/ck3lens-explorer/ # VS Code extension (sidebar UI, MCP provider)
tools/compliance/      # Contracts, tokens, semantic validator
```

**When writing code that imports ck3raven internals:**
```python
from ck3raven.parser import parse_file, parse_source
from ck3raven.db.schema import get_connection
from ck3raven.db.search import search_symbols
```

---

## Key Documents

| Document | Purpose |
|----------|---------|
| `docs/CANONICAL_ARCHITECTURE.md` | **5 rules every agent must follow** |
| `docs/SINGLE_WRITER_ARCHITECTURE.md` | QBuilder daemon design |
| `docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md` | CK3 engine merge behavior reference |
| `docs/06_CONTAINER_MERGE_OVERRIDE_TABLE.md` | Per-content-type merge policy |

---

## Wrong Mode?

If editing CK3 mod files (.txt, .yml) → switch to `ck3lens` mode.
