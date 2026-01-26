# ARCH-LINT TEST: relative import
from ..db.symbols import symbols_table

def load():
    return symbols_table
