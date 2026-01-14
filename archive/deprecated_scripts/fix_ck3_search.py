"""Fix ck3_search function to remove BANNED params and use world.normalize()."""
import pathlib

path = pathlib.Path('tools/ck3lens_mcp/server.py')
content = path.read_text(encoding='utf-8')
lines = content.split('\n')

changes = 0
new_lines = []
skip_next = 0

for i, line in enumerate(lines):
    if skip_next > 0:
        skip_next -= 1
        continue
        
    # Skip banned param declarations
    if 'source_filter: Optional[str]' in line:
        changes += 1
        continue
    if 'mod_filter: Optional[list[str]]' in line:
        changes += 1
        continue
    if 'no_lens: bool = False' in line:
        changes += 1
        continue
    
    # Skip banned docstring lines
    if 'source_filter: Filter by source' in line:
        changes += 1
        continue
    if 'mod_filter: List of mod names' in line:
        changes += 1
        continue
    if 'no_lens: If True, search ALL content' in line:
        changes += 1
        continue
        
    # Fix path normalization (replace inline with world.normalize)
    if 'folder = game_folder.replace' in line and '.strip("/")' in line:
        new_lines.append('        # Use canonical path normalization via WorldAdapter')
        new_lines.append('        folder = world.normalize(game_folder)')
        changes += 1
        continue
        
    # Remove effective_source assignment
    if 'effective_source = source_filter' in line:
        changes += 1
        continue
    if '# Note: mod_filter is handled' in line:
        changes += 1
        continue
        
    # Remove source_filter from db.unified_search call
    if 'source_filter=effective_source,' in line:
        changes += 1
        continue
        
    # Fix guidance for truncated results
    if 'if not mod_filter and not source_filter:' in line:
        changes += 1
        continue
    if "To narrow: use mod_filter" in line:
        changes += 1
        continue
        
    # Remove from trace.log
    if '"mod_filter": mod_filter,' in line:
        changes += 1
        continue
    if '"no_lens": no_lens' in line:
        changes += 1
        continue
        
    new_lines.append(line)

content = '\n'.join(new_lines)
path.write_text(content, encoding='utf-8')
print(f'SUCCESS: Made {changes} changes to ck3_search function')
print(f'File now has {len(new_lines)} lines (was {len(lines)} lines)')
