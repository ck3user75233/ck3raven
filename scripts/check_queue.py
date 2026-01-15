#!/usr/bin/env python
"""Check build queue status."""
import sqlite3
from pathlib import Path

db = Path.home() / '.ck3raven' / 'ck3raven.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row

# Check build queue status breakdown
print("Build queue by status:")
for row in conn.execute('''
    SELECT status, COUNT(*) as cnt, MIN(build_id) as min_id, MAX(build_id) as max_id
    FROM build_queue GROUP BY status ORDER BY status
'''):
    print(f"  {row['status']}: {row['cnt']} (build_id {row['min_id']}-{row['max_id']})")

# Check if there are any items marked completed
completed = conn.execute('SELECT COUNT(*) FROM build_queue WHERE status = "completed"').fetchone()[0]
print(f"\nCompleted in queue: {completed}")

# Check for items with file_id <= 132 (the last one processed in logs)
processed_range = conn.execute('''
    SELECT status, COUNT(*) FROM build_queue WHERE file_id <= 132 GROUP BY status
''').fetchall()
print(f"\nItems with file_id <= 132:")
for row in processed_range:
    print(f"  {row[0]}: {row[1]}")
