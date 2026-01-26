from ck3raven.db.symbols import SymbolsRepo

def load_symbols(repo: SymbolsRepo) -> int:
    return repo.count()
