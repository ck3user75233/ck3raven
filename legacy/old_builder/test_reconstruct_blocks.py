#!/usr/bin/env python3
"""Test the unified log_phase_delta function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
from builder.daemon import BuildTracker

db_path = Path.home() / '.ck3raven' / 'test_block_logging.db'
conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row

class QuietLogger:
    def info(self, msg): print(f'INFO: {msg}')
    def debug(self, msg): pass
    def warning(self, msg): print(f'WARN: {msg}')
    def error(self, msg): print(f'ERROR: {msg}')

tracker = BuildTracker(conn, QuietLogger(), force=False)
print(f'Build ID: {tracker.build_id[:8]}...')

# Test unified log_phase_delta for all configured phases
for phase in ['ast_generation', 'symbol_extraction', 'ref_extraction', 
              'localization_parsing', 'lookup_extraction']:
    logged = tracker.log_phase_delta(phase)
    print(f'{phase}: logged {logged} files')
    
    if logged > 0:
        blocks = tracker.reconstruct_blocks(phase)
        print(f'  -> created {blocks} blocks')

# Test that invalid phase raises error
try:
    tracker.log_phase_delta("invalid_phase")
    print("ERROR: Should have raised ValueError!")
except ValueError as e:
    print(f"\nCorrectly raised ValueError for invalid phase: {str(e)[:80]}...")

conn.close()
print('\nUnified log_phase_delta() works correctly!')
