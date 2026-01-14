"""Fix the playset_path -> playset_file bug in daemon.py."""
import pathlib

daemon_path = pathlib.Path('builder/daemon.py')
content = daemon_path.read_text(encoding='utf-8')

# Fix the bug: playset_path should be playset_file
old = 'f"Playset {playset_path} missing required \'mods\' key - "'
new = 'f"Playset {playset_file} missing required \'mods\' key - "'

if old in content:
    content = content.replace(old, new)
    daemon_path.write_text(content, encoding='utf-8')
    print('Fixed playset_path -> playset_file bug on line 860')
else:
    print('Bug already fixed or pattern not found')
