"""Fix resolver/__init__.py to remove archived ContributionsManager imports."""
import pathlib

init_path = pathlib.Path('src/ck3raven/resolver/__init__.py')
content = init_path.read_text(encoding='utf-8')

# Remove the ContributionsManager import block
old_imports = '''# Contributions Manager (LIFECYCLE-AWARE)
from ck3raven.resolver.manager import (
    ContributionsManager,
    RefreshResult,
    ConflictSummary,
)'''

new_imports = '''# Contributions Manager (ARCHIVED - used banned playset_id)
# See archive/conflict_analysis_jan2026/manager.py
# Will be rebuilt with simple cvids-based approach
# from ck3raven.resolver.manager import (
#     ContributionsManager,
#     RefreshResult,
#     ConflictSummary,
# )'''

content = content.replace(old_imports, new_imports)

# Remove from __all__
old_all = '''    # Contributions Manager (LIFECYCLE-AWARE)
    "ContributionsManager",
    "RefreshResult",
    "ConflictSummary",'''

new_all = '''    # Contributions Manager (ARCHIVED - will be rebuilt)
    # "ContributionsManager",
    # "RefreshResult",
    # "ConflictSummary",'''

content = content.replace(old_all, new_all)

init_path.write_text(content, encoding='utf-8')
print('Fixed resolver/__init__.py - removed archived ContributionsManager imports')
