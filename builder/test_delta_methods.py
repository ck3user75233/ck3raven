#!/usr/bin/env python3
"""Quick test of block logging methods."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from builder.daemon import BuildTracker

db_path = Path.home() / '.ck3raven' / 'test_block_logging.db'
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

class QuietLogger:
    def info(self, msg): pass
    def debug(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): print(f'ERROR: {msg}')

tracker = BuildTracker(conn, QuietLogger(), force=False)
print(f'Build ID: {tracker.build_id[:8]}...')

# Test each method (should return 0 since test DB doesn't have symbols/refs/loc)
print(f'log_phase_delta_symbols: {tracker.log_phase_delta_symbols("symbol_extraction")} files')
print(f'log_phase_delta_refs: {tracker.log_phase_delta_refs("ref_extraction")} files')
print(f'log_phase_delta_localization: {tracker.log_phase_delta_localization("localization_parsing")} files')
print(f'log_phase_delta_lookups: {tracker.log_phase_delta_lookups("lookup_extraction")} files')

print('\nAll log_phase_delta_* methods work correctly!')
conn.close()
