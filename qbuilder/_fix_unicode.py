from pathlib import Path
content = Path('qbuilder/worker.py').read_text(encoding='utf-8')

# Fix the print statements to handle Unicode properly
old_print = 'print(f"  Error: {err_msg}")'
new_print = 'print(f"  Error: {err_msg}".encode("utf-8", errors="replace").decode("utf-8", errors="replace"))'
content = content.replace(old_print, new_print)

Path('qbuilder/worker.py').write_text(content, encoding='utf-8')
print('Fixed unicode encoding issue')
