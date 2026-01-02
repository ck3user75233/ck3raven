"""Archive conflict functions from unified_tools.py."""
import pathlib

archive_dir = pathlib.Path('archive/conflict_analysis_jan2026')
archive_dir.mkdir(parents=True, exist_ok=True)

# Read unified_tools.py
unified_path = pathlib.Path('tools/ck3lens_mcp/ck3lens/unified_tools.py')
content = unified_path.read_text(encoding='utf-8')
lines = content.split('\n')

# Find the conflict section (starts at line ~350)
start_marker = '# ============================================================================\n# ck3_conflicts - Unified Conflict Tool'
end_marker = '# ============================================================================\n# ck3_file - Unified File Operations'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print(f'ERROR: Could not find conflict section markers')
    print(f'start_idx: {start_idx}, end_idx: {end_idx}')
    exit(1)

# Extract the conflict section for archiving
conflict_section = content[start_idx:end_idx]

# Save to archive
archive_file = archive_dir / 'unified_tools_conflict_functions.py'
archive_file.write_text(f'''"""
ARCHIVED 2025-01-02: Conflict functions from unified_tools.py

These used BANNED playset_id architecture. Will be rebuilt using:
- Input: mods[] cvids from session
- Simple symbol duplicate queries
- No playset_id needed

See docs/CANONICAL_ARCHITECTURE.md
"""

{conflict_section}
''', encoding='utf-8')
print(f'Archived conflict functions to: {archive_file}')

# Replace with tombstone
tombstone = '''# ============================================================================
# ck3_conflicts - ARCHIVED 2025-01-02
# ============================================================================
# 
# The conflict analysis functions were archived because they used BANNED
# playset_id architecture. See: archive/conflict_analysis_jan2026/
#
# Conflict analysis will be rebuilt with the simple approach:
#
# FILE-LEVEL CONFLICTS:
#   Same relpath across multiple content_version_ids in mods[]
#   SELECT relpath, GROUP_CONCAT(content_version_id)
#   FROM files WHERE content_version_id IN (cvids from mods[])
#   GROUP BY relpath HAVING COUNT(DISTINCT content_version_id) > 1
#
# SYMBOL-LEVEL CONFLICTS:
#   Same symbol name defined in multiple cvids
#   SELECT name, symbol_type, GROUP_CONCAT(content_version_id)
#   FROM symbols WHERE content_version_id IN (cvids from mods[])
#   GROUP BY name, symbol_type HAVING COUNT(DISTINCT content_version_id) > 1
#
# No playset_id needed - just use session.mods[] cvids directly.
# ============================================================================


'''

new_content = content[:start_idx] + tombstone + content[end_idx:]
unified_path.write_text(new_content, encoding='utf-8')
print(f'Replaced conflict section with tombstone in unified_tools.py')

# Count lines removed
old_lines = len(content.split('\n'))
new_lines = len(new_content.split('\n'))
print(f'Lines: {old_lines} -> {new_lines} (removed {old_lines - new_lines})')
