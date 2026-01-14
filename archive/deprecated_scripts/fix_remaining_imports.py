"""Fix remaining files that import from deleted playsets.py"""
import pathlib
import os

# 1. Delete scripts/create_playset.py - entire script is BANNED
create_playset_path = pathlib.Path('scripts/create_playset.py')
if create_playset_path.exists():
    tombstone = '''"""
EXPUNGED 2025-01-02

This script used BANNED database-based playset creation.
Playsets are now file-based JSON. See:
- playsets/*.json for playset definitions
- server.py ck3_playset for MCP tool
- docs/PLAYSET_ARCHITECTURE.md for architecture

The original create_playset.py created playsets in SQL tables (playsets, playset_mods).
That architecture is BANNED - see CANONICAL_ARCHITECTURE.md.
"""

raise NotImplementedError("This script is EXPUNGED. Use file-based playsets instead.")
'''
    create_playset_path.write_text(tombstone, encoding='utf-8')
    print('scripts/create_playset.py: replaced with tombstone')

# 2. Fix src/ck3raven/emulator/loader.py
loader_path = pathlib.Path('src/ck3raven/emulator/loader.py')
if loader_path.exists():
    c = loader_path.read_text(encoding='utf-8')
    # Replace import
    c = c.replace('''from ck3raven.db.playsets import (
    get_playset, get_playset_load_order, get_playset_mods
)''', '''# EXPUNGED 2025-01-02: playsets.py deleted - file-based now
# Loader needs to be updated to work with file-based playsets
# For now, stub functions that raise NotImplementedError

def get_playset(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_load_order(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_mods(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")''')
    loader_path.write_text(c, encoding='utf-8')
    print('src/ck3raven/emulator/loader.py: stubbed out banned imports')

# 3. Fix src/ck3raven/resolver/manager.py
manager_path = pathlib.Path('src/ck3raven/resolver/manager.py')
if manager_path.exists():
    c = manager_path.read_text(encoding='utf-8')
    # Replace import
    c = c.replace('''from ck3raven.db.playsets import (
    get_playset,
    get_playset_mods,
    get_playset_load_order,
    is_contributions_stale,
    mark_contributions_current,
    compute_load_order_hash,
)''', '''# EXPUNGED 2025-01-02: playsets.py deleted - file-based now
# ContributionsManager needs to be updated to work with file-based playsets
# For now, stub functions that raise NotImplementedError

def get_playset(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_mods(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def get_playset_load_order(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def is_contributions_stale(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def mark_contributions_current(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")

def compute_load_order_hash(*args, **kwargs):
    raise NotImplementedError("Database playsets EXPUNGED - use file-based playsets")''')
    manager_path.write_text(c, encoding='utf-8')
    print('src/ck3raven/resolver/manager.py: stubbed out banned imports')

print('Done fixing imports')
