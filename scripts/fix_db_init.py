"""Fix db/__init__.py - remove banned playsets imports and exports."""
import pathlib

p = pathlib.Path('src/ck3raven/db/__init__.py')
c = p.read_text(encoding='utf-8')

# Remove the playsets import block
c = c.replace('''from ck3raven.db.playsets import (
    MAX_ACTIVE_PLAYSETS,
    create_playset,
    get_playset,
    get_playset_by_name,
    list_playsets,
    update_playset,
    delete_playset,
    add_mod_to_playset,
    remove_mod_from_playset,
    set_mod_enabled,
    reorder_mods,
    get_playset_mods,
    get_playset_load_order,
    compute_load_order_hash,
    clone_playset,
)
''', '''# EXPUNGED 2025-01-02: Database-based playset functions removed.
# Playsets are now file-based JSON. See playsets/*.json and server.py ck3_playset.
''')

# Remove the playsets exports from __all__
c = c.replace('''    # Playsets
    "MAX_ACTIVE_PLAYSETS",
    "create_playset",
    "get_playset",
    "get_playset_by_name",
    "list_playsets",
    "update_playset",
    "delete_playset",
    "add_mod_to_playset",
    "remove_mod_from_playset",
    "set_mod_enabled",
    "reorder_mods",
    "get_playset_mods",
    "get_playset_load_order",
    "compute_load_order_hash",
    "clone_playset",''', '''    # EXPUNGED: Playsets functions removed (now file-based JSON)''')

# Also need to remove Playset, PlaysetMod from models import  
c = c.replace('''    Playset,
    PlaysetMod,
''', '''    # EXPUNGED: Playset, PlaysetMod models removed (now file-based JSON)
''')

# And from __all__
c = c.replace('''    "Playset",
    "PlaysetMod",
''', '')

p.write_text(c, encoding='utf-8')
print('Fixed db/__init__.py')
