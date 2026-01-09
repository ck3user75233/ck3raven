#!/usr/bin/env python3
"Fix WIP scope domain bug in enforcement.py"
from pathlib import Path
import re

p = Path('tools/ck3lens_mcp/ck3lens/policy/enforcement.py')
content = p.read_text(encoding='utf-8')

# The pattern we're looking for
old_pattern = r( for path in paths_to_check:\n if path:\n)( # Extract relative path from canonical address)

new_code = r'''\1                # Check if canonical address type directly matches a repo domain
                # e.g., wip:/test.txt with wip in repo_domains -> auto-allow
                if ':/' in path and not path[1:3] == ':\\\\':
                    addr_type = path.split(':/', 1)[0]
                    if addr_type in repo_domains:
                        continue  # Address type matches domain, skip pattern check
                
                \2'''

result = re.sub(old_pattern, new_code, content)

if result != content:
    p.write_text(result, encoding='utf-8')
    print('SUCCESS: Applied WIP scope fix')
else:
    print('ERROR: Pattern not found')
