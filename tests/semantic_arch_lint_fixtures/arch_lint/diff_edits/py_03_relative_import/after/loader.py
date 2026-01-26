from ck3raven.db.symbols import SymbolsRepo
# SUBSET EDIT: relative import (should be forbidden)
from ..runtime.core import get_runtime

def load_symbols(repo: SymbolsRepo) -> int:
    _ = get_runtime()
    return repo.count()
