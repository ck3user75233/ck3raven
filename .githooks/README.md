# Policy Enforcement Hooks

This directory contains git hooks for policy enforcement.

## Setup

Configure git to use these hooks:

```bash
git config core.hooksPath .githooks
```

Or manually copy/symlink to `.git/hooks/`:

```bash
# Unix
cp .githooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

# Windows (PowerShell)
Copy-Item .githooks\pre-commit .git\hooks\pre-commit
```

## Pre-Commit Hook

The pre-commit hook runs policy validation before every commit:

1. Reads the MCP trace log (`ck3lens_trace.jsonl`)
2. Validates all tool calls against policy rules
3. Blocks the commit if validation fails

### Environment Variables

- `CK3LENS_MODE` - Validation mode (default: `ck3raven-dev`)
- `CK3LENS_SKIP_VALIDATION` - Set to `1` to bypass (use with caution)

### Bypass (Emergency Only)

```bash
CK3LENS_SKIP_VALIDATION=1 git commit -m "emergency fix"
```

This is logged and should be reviewed.

## What Gets Validated

- **ck3raven-dev mode**:
  - Python files must pass syntax validation
  - New files must be in allowed paths
  - Bugfixes require tests
  - Schema changes must be declared

- **ck3lens mode**:
  - Database-first search required
  - Symbol resolution checks
  - Conflict alignment validation
