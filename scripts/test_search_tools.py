#!/usr/bin/env python3
"""Test the search tools in DBQueries."""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "ck3lens_mcp"))

from ck3lens.db_queries import DBQueries

def main():
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    print(f"Database: {db_path}")
    
    db = DBQueries(db_path)
    
    # Get active playset
    playset = db.conn.execute("SELECT playset_id, name FROM playsets WHERE is_active = 1").fetchone()
    playset_id = playset[0]
    print(f"Playset: {playset_id} - {playset[1]}")
    
    # Test 1: search_symbols
    print("\n" + "="*60)
    print("TEST 1: search_symbols('brave')")
    print("="*60)
    result = db.search_symbols(playset_id, "brave", limit=5)
    print(f"Exact matches: {len(result['results'])}")
    print(f"Adjacencies: {len(result['adjacencies'])}")
    if result['results']:
        print(f"First result: {result['results'][0]}")
    
    # Test 2: search_files
    print("\n" + "="*60)
    print("TEST 2: search_files('%on_action%')")
    print("="*60)
    files = db.search_files(playset_id, "%on_action%", limit=5)
    print(f"Files found: {len(files)}")
    for f in files[:3]:
        print(f"  - {f['relpath']} ({f['source_name']})")
    
    # Test 3: search_content
    print("\n" + "="*60)
    print("TEST 3: search_content('on_yearly_pulse')")
    print("="*60)
    results = db.search_content(playset_id, "on_yearly_pulse", limit=5)
    print(f"Results found: {len(results)}")
    for r in results[:3]:
        print(f"  - {r['relpath']} ({r['source_name']}) - {r['match_count']} matches")
    
    # Test 4: confirm_not_exists
    print("\n" + "="*60)
    print("TEST 4: confirm_not_exists('totally_fake_trait_xyz')")
    print("="*60)
    result = db.confirm_not_exists(playset_id, "totally_fake_trait_xyz")
    print(f"Can claim not exists: {result['can_claim_not_exists']}")
    
    print("\n✅ All search tests passed!")
    db.close()

if __name__ == "__main__":
    main()
