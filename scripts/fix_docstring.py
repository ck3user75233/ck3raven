"""Fix docstring example with banned mod_filter param."""
import pathlib

p = pathlib.Path('tools/ck3lens_mcp/server.py')
c = p.read_text(encoding='utf-8')
c = c.replace('ck3_search("brave", mod_filter=["MSC"])  # Only in MSC mod', 'ck3_search("brave", game_folder="common/traits")  # Only trait files')
p.write_text(c, encoding='utf-8')
print('Fixed docstring example')
