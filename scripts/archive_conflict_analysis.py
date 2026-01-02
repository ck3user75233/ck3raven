"""
MAJOR CLEANUP: Archive all conflict analysis code and banned playset_id architecture.

User directive: Focus on getting DB/builder working. Conflict analysis is simple once
the database is built - just query symbols table for duplicates across mods[].

Actions:
1. Archive loader.py (redundant with MCP tools)
2. Archive resolver/manager.py (uses banned playset_id)
3. Archive resolver/conflict_analyzer.py (uses banned playset_id)
4. Clean Session class - remove playset_id entirely
5. Clean unified_tools.py - remove conflict functions that use playset_id
"""
import pathlib
import shutil

archive_dir = pathlib.Path('archive/conflict_analysis_jan2026')
archive_dir.mkdir(parents=True, exist_ok=True)

files_to_archive = [
    'src/ck3raven/emulator/loader.py',
    'src/ck3raven/resolver/manager.py',
]

# Check if conflict_analyzer exists
conflict_analyzer = pathlib.Path('src/ck3raven/resolver/conflict_analyzer.py')
if conflict_analyzer.exists():
    files_to_archive.append(str(conflict_analyzer))

for file_path in files_to_archive:
    src = pathlib.Path(file_path)
    if src.exists():
        dst = archive_dir / src.name
        shutil.copy2(src, dst)
        print(f'Archived: {src} -> {dst}')
        
        # Replace with tombstone
        tombstone = f'''"""
ARCHIVED 2025-01-02: This module used BANNED playset_id architecture.

Original archived to: archive/conflict_analysis_jan2026/{src.name}

The conflict analysis system will be rebuilt using the simple approach:
- Input: mods[] cvids from session
- Query symbols table for duplicates across those cvids
- No playset_id needed

See docs/CANONICAL_ARCHITECTURE.md
"""

raise NotImplementedError("ARCHIVED: This module used banned playset_id. See archive/conflict_analysis_jan2026/")
'''
        src.write_text(tombstone, encoding='utf-8')
        print(f'Replaced with tombstone: {src}')

# Fix Session class - remove playset_id entirely
workspace_path = pathlib.Path('tools/ck3lens_mcp/ck3lens/workspace.py')
c = workspace_path.read_text(encoding='utf-8')

# Remove the playset_id field entirely
c = c.replace('    # EXPUNGED: playset_id - use playset_name and mods[] cvids instead\n    playset_id: Optional[int] = None  # TODO: Remove after conflict system migration\n', '')
c = c.replace('    playset_id: Optional[int] = None\n', '')

workspace_path.write_text(c, encoding='utf-8')
print('workspace.py: removed playset_id from Session class')

print('\\nDone archiving conflict analysis code')
