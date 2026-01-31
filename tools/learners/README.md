# CK3 Learners

Infrastructure for comparing CK3 mod symbols against vanilla to learn what mods change.

## Quick Start

```bash
cd tools/learners

# Compare a single symbol
python learner_tool.py compare murder --mod "More Game Rules"

# Batch compare all MAA types, export to files
python learner_tool.py batch maa_type --mod KGD --export

# List what symbol types a mod contains
python learner_tool.py list "More Game Rules"
```

## Commands

### `compare` - Single Symbol Diff

Compare one symbol between vanilla and a mod.

```bash
python learner_tool.py compare <symbol> --mod <mod_name> [--type <type>] [--export]
```

| Argument | Description |
|----------|-------------|
| `symbol` | Symbol name (e.g., `murder`, `brave`, `heavy_infantry`) |
| `--mod`, `-m` | Mod to compare against vanilla (required) |
| `--type`, `-t` | Symbol type (auto-detected if not provided) |
| `--export`, `-e` | Write results to JSONL file |

**Example output:**
```json
{
  "symbol_name": "murder",
  "symbol_type": "scheme",
  "baseline": "Vanilla CK3",
  "compare": "More Game Rules",
  "change_count": 1,
  "changes": [
    {
      "json_path": "allow.mgr_can_murder",
      "old_value": null,
      "new_value": "yes",
      "change_type": "added"
    }
  ]
}
```

### `batch` - Batch Compare by Type

Compare all symbols of a type between vanilla and a mod.

```bash
python learner_tool.py batch <type> --mod <mod_name> [--limit N] [--export]
```

| Argument | Description |
|----------|-------------|
| `type` | Symbol type (`maa_type`, `building`, `trait`, `scheme`, etc.) |
| `--mod`, `-m` | Mod to compare against vanilla (required) |
| `--limit`, `-l` | Max symbols to process (default: 50) |
| `--export`, `-e` | Write JSONL + summary files |

**Example:**
```bash
python learner_tool.py batch scheme --mod "More Game Rules" --export
```

**Output:**
```json
{
  "symbol_type": "scheme",
  "baseline": "vanilla",
  "compare": "More Game Rules",
  "total_changed": 3,
  "symbols": [
    {"name": "courting", "change_count": 214},
    {"name": "murder", "change_count": 1},
    {"name": "seduce", "change_count": 433}
  ],
  "output_files": {
    "jsonl": "tools/learners/output/scheme_More_Game_Rules_20260131_143022.jsonl",
    "summary": "tools/learners/output/scheme_More_Game_Rules_summary_20260131_143022.txt"
  }
}
```

### `list` - Discover Mod Contents

List what symbol types a mod contains, or which symbols of a type it changes.

```bash
python learner_tool.py list <mod_name> [--type <type>] [--limit N]
```

| Argument | Description |
|----------|-------------|
| `mod_name` | Mod name (fuzzy match) |
| `--type`, `-t` | Filter to specific symbol type |
| `--limit`, `-l` | Max results (default: 100) |

**Without --type** (shows symbol type breakdown):
```json
{
  "mod": "More Game Rules",
  "symbol_types": [
    {"type": "game_rule", "count": 117},
    {"type": "modifier", "count": 33},
    {"type": "scripted_effect", "count": 22}
  ]
}
```

**With --type** (shows which symbols are changed):
```bash
python learner_tool.py list KGD --type maa_type
```

## Output Files

When using `--export`, files are written to `tools/learners/output/`:

| File | Format | Description |
|------|--------|-------------|
| `*_<timestamp>.jsonl` | JSONL | One JSON object per change, flat structure |
| `*_summary_<timestamp>.txt` | Text | Human-readable summary with statistics |

### JSONL Format

Each line is a change record:
```json
{"symbol_name": "heavy_infantry", "symbol_type": "maa_type", "json_path": "damage.0", "old_value": "25", "new_value": "30", "change_type": "modified"}
```

### Summary Format

```
Diff Summary: maa_type_KGD
============================================================

Symbols with changes: 47
Total changes: 892

By change type:
  added: 156
  modified: 623
  removed: 113

Top modified paths:
  damage: 94
  toughness: 87
  pursuit: 76
```

## Architecture

```
tools/learners/
├── learner_tool.py   # CLI entry point (this is what you run)
├── db_adapter.py     # Database access (LearnerDb class)
├── ast_diff.py       # AST structural differ
├── batch_differ.py   # Batch processing + export
├── output/           # Generated JSONL + summary files
└── README.md         # This file
```

## Symbol Types

Common symbol types you can query:

| Type | Description |
|------|-------------|
| `maa_type` | Men-at-arms unit definitions |
| `building` | Building definitions |
| `trait` | Character traits |
| `scheme` | Scheme definitions (murder, seduce, etc.) |
| `event` | Event definitions |
| `decision` | Decision definitions |
| `interaction` | Character interactions |
| `scripted_effect` | Reusable script effects |
| `scripted_trigger` | Reusable script triggers |
| `on_action` | Event hooks |
| `game_rule` | Game rule definitions |

## Future: MCP Integration

The functions in `learner_tool.py` (`compare_symbol`, `batch_compare`, `list_mod_changes`) are designed to be callable from MCP tools. A future `ck3_learner` MCP tool will expose these directly to agents.
