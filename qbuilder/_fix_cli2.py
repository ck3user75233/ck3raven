from pathlib import Path
content = Path('qbuilder/cli.py').read_text(encoding='utf-8')

# Add BuilderSession import after existing imports
old_import = "from .schema import init_qbuilder_schema, reset_qbuilder_tables, get_queue_counts"
new_import = """from .schema import init_qbuilder_schema, reset_qbuilder_tables, get_queue_counts
from ck3raven.db.schema import BuilderSession"""
content = content.replace(old_import, new_import)

Path('qbuilder/cli.py').write_text(content, encoding='utf-8')
print('Fixed cli.py import')
