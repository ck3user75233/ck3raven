#!/usr/bin/env python
"""Reset ASTs and rebuild to test new serialization."""
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path.home() / '.ck3raven' / 'ck3raven.db')

# Clear the old broken ASTs
conn.execute('DELETE FROM asts')
print('Cleared ASTs')

# Reset the completed builds back to pending so they rebuild
conn.execute("UPDATE build_queue SET status = 'pending' WHERE status = 'completed'")
conn.commit()
print('Reset completed builds to pending')

print(f'Total changes: {conn.total_changes}')
conn.close()
