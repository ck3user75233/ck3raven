# ARCH-LINT TEST: forbidden cross-layer import
from ck3raven.db.internal.connection import _get_raw_connection

def do_bad_thing():
    return _get_raw_connection()
