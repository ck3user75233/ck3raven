"""Archive ck3_conflicts tool from server.py."""
import pathlib

server_path = pathlib.Path('tools/ck3lens_mcp/server.py')
content = server_path.read_text(encoding='utf-8')

# Find the ck3_conflicts tool section
start_marker = '@mcp.tool()\ndef ck3_conflicts('
end_marker = '# ============================================================================\n# Unified File Operations'

start_idx = content.find(start_marker)
end_idx = content.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print(f'ERROR: Could not find ck3_conflicts section')
    exit(1)

# Replace with tombstone
tombstone = '''# ============================================================================
# ck3_conflicts - ARCHIVED 2025-01-02
# ============================================================================
#
# The ck3_conflicts MCP tool was archived because it used BANNED playset_id.
# See: archive/conflict_analysis_jan2026/
#
# Will be rebuilt with simple approach using session.mods[] cvids directly.
# No playset_id needed - conflicts are between mods in the active playset.
# ============================================================================


'''

new_content = content[:start_idx] + tombstone + content[end_idx:]
server_path.write_text(new_content, encoding='utf-8')

old_lines = len(content.split('\n'))
new_lines = len(new_content.split('\n'))
print(f'Archived ck3_conflicts from server.py')
print(f'Lines: {old_lines} -> {new_lines} (removed {old_lines - new_lines})')
