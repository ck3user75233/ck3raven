"""Clean up stray comment from ck3_search."""
import pathlib

p = pathlib.Path('tools/ck3lens_mcp/server.py')
c = p.read_text(encoding='utf-8')
c = c.replace('    # Build source filter from mod_filter if provided\n\n', '')
p.write_text(c, encoding='utf-8')
print('Cleaned up stray comment')
