#!/usr/bin/env python3
"""Initialize the contribution/conflict tables in the database."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection
from ck3raven.resolver.contributions import init_contribution_schema

def main():
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    print(f"Database: {db_path}")
    
    conn = get_connection(db_path)
    
    print("Creating contribution/conflict tables...")
    init_contribution_schema(conn)
    print("Tables created!")
    
    # Verify
    tables = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND (
            name LIKE 'contrib%' 
            OR name LIKE 'conflict%' 
            OR name LIKE 'resolution%'
        )
    """).fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
    
    conn.close()

if __name__ == "__main__":
    main()
