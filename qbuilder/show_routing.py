#!/usr/bin/env python
"""Show 25-sample routing output proof."""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
ROUTING_PATH = Path(__file__).parent / "routing_table.json"

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Load routing table to get envelope_to_steps
    with open(ROUTING_PATH) as f:
        routing = json.load(f)
    
    envelope_to_steps = routing.get('envelope_steps', {})
    
    print("=" * 90)
    print("25-SAMPLE ROUTING OUTPUT (sourced from routing_table.json)")
    print("=" * 90)
    print(f"{'FILE':50} | {'TYPE':12} | {'ENVELOPE':10} | STEPS")
    print("-" * 90)
    
    rows = conn.execute('''
        SELECT b.envelope, f.relpath, f.file_type 
        FROM build_queue b
        JOIN files f ON b.file_id = f.file_id
        ORDER BY b.build_id
        LIMIT 25
    ''').fetchall()
    
    for r in rows:
        relpath = r['relpath'][:48] + ".." if len(r['relpath']) > 50 else r['relpath']
        file_type = r['file_type'] or 'unknown'
        envelope = r['envelope']
        steps = envelope_to_steps.get(envelope, [])
        print(f"{relpath:50} | {file_type:12} | {envelope:10} | {steps}")
    
    conn.close()

if __name__ == "__main__":
    main()
