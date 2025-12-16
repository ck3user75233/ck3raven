# ck3raven 🪶

**CK3 Game State Emulator** - A Python toolkit for parsing, merging, and resolving mod conflicts in Crusader Kings III.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## What is ck3raven?

ck3raven is a modding tool that:

1. **Parses** CK3/Paradox script files into an AST (100% regex-free lexer/parser)
2. **Resolves** conflicts between vanilla and mod files using accurate merge rules
3. **Emulates** the game's final state for any playset combination
4. **Generates** compatibility patches and conflict reports

Think of it as "what does the game actually see?" - crucial for compatch authors and complex mod setups.

## Features

- 🔍 **Pure Python Parser** - No regex, handles all CK3 syntax including edge cases
- 📦 **Accurate Merge Rules** - Implements LIOS/FIOS, container merging, on_action special rules
- 🗂️ **Content Type Aware** - Knows traditions override, on_actions merge, GUI uses FIOS, etc.
- 📊 **Conflict Detection** - Identifies which mods override which keys
- 🔄 **Virtual Merge** - See vanilla vs mod vs final state side-by-side

## Installation

```bash
# Clone the repository
git clone https://github.com/ck3user75233/ck3raven.git
cd ck3raven

# Install in development mode
pip install -e .

# Or install with dev dependencies for testing
pip install -e ".[dev]"
```

## Quick Start

### Parse a CK3 File

```python
from ck3raven.parser import parse_file, parse_source

# Parse a file
ast = parse_file("path/to/traditions.txt")

# Get all tradition blocks
for block in ast.get_blocks("tradition_"):
    print(f"Found tradition: {block.name}")

# Parse a string
ast = parse_source('''
tradition_mountain_homes = {
    category = regional
    parameters = { mountain_trait_bonuses = yes }
}
''')
```

### Resolve Tradition Conflicts

```python
from ck3raven.resolver import TraditionResolver

resolver = TraditionResolver(
    vanilla_path="path/to/game/common/culture/traditions",
    mod_paths=["path/to/mod1", "path/to/mod2"]
)

# Get final state
final_traditions = resolver.resolve()

# Get conflict report
conflicts = resolver.get_conflicts()
for key, sources in conflicts.items():
    print(f"{key}: defined in {len(sources)} sources")
```

## Project Structure

```
ck3raven/
├── src/ck3raven/
│   ├── parser/          # Lexer + Parser (AST generation)
│   ├── resolver/        # Merge/override resolution logic
│   └── emulator/        # Full game state building
├── docs/                # Design documentation
├── tests/               # Test suite
└── scripts/             # CLI tools
```

## Documentation

See the `docs/` folder for detailed documentation:

- [Merge/Override Rules](docs/05_ACCURATE_MERGE_OVERRIDE_RULES.md) - How CK3 handles conflicts
- [Content Type Table](docs/06_CONTAINER_MERGE_OVERRIDE_TABLE.md) - Rules for every folder
- [Virtual Merge Explained](docs/04_VIRTUAL_MERGE_EXPLAINED.md) - Multi-source comparison

## Key Concepts

### Merge Policies

ck3raven implements the same merge rules as the CK3 engine:

| Policy | Behavior | Used By |
|--------|----------|---------|
| **OVERRIDE** | Last definition wins | ~95% of content (traditions, events, decisions...) |
| **CONTAINER_MERGE** | Container merges, sublists append | on_actions |
| **PER_KEY_OVERRIDE** | Each key independent | localization, defines |
| **FIOS** | First definition wins | GUI types/templates |

### File-Level Behavior

- **Same filename** = Complete file replacement
- **Different filename** = Key-level merge with policies above

## Credits

Inspired by:
- [ck3tiger](https://github.com/amtep/ck3tiger) - The excellent CK3 validator
- [Gambo's Super Compatch](https://steamcommunity.com/sharedfiles/filedetails/?id=2941627704) - Compatch patterns reference
- [Paradox Wiki Modding Guide](https://ck3.paradoxwikis.com/Modding) - Official documentation

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

Contributions welcome! Please read the docs first to understand CK3's merge behavior.

---

*ck3raven is not affiliated with Paradox Interactive.*
