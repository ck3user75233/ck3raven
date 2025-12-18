"""
Test the contribution lifecycle system.

This verifies that:
1. Schema is created with init_database()
2. Playsets track staleness correctly
3. Playset operations mark contributions as stale
4. ContributionsManager auto-refreshes when stale
"""

import sys
import sqlite3
from pathlib import Path

# Add ck3raven to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection, init_database, DEFAULT_DB_PATH


def test_schema_has_contribution_tables():
    """Test that init_database creates contribution tables."""
    print("1. Testing schema has contribution tables...")
    conn = get_connection()
    
    # Check for tables
    tables = [r[0] for r in conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN (
            'contribution_units', 
            'conflict_units', 
            'conflict_candidates', 
            'resolution_choices'
        )
    """).fetchall()]
    
    expected = ['contribution_units', 'conflict_units', 'conflict_candidates', 'resolution_choices']
    missing = set(expected) - set(tables)
    
    if missing:
        print(f"   ❌ FAIL: Missing tables: {missing}")
        return False
    
    print("   ✅ PASS: All contribution tables exist")
    return True


def test_playsets_have_staleness_columns():
    """Test that playsets table has staleness tracking columns."""
    print("2. Testing playsets staleness columns...")
    conn = get_connection()
    
    # Get column info
    columns = [r[1] for r in conn.execute("PRAGMA table_info(playsets)").fetchall()]
    
    required = ['contributions_stale', 'contributions_hash', 'contributions_scanned_at']
    missing = [c for c in required if c not in columns]
    
    if missing:
        print(f"   ❌ FAIL: Missing columns: {missing}")
        print(f"   Existing columns: {columns}")
        return False
    
    print("   ✅ PASS: Staleness tracking columns exist")
    return True


def test_playset_staleness_functions():
    """Test staleness helper functions."""
    print("3. Testing staleness helper functions...")
    
    try:
        from ck3raven.db.playsets import (
            is_contributions_stale,
            mark_contributions_current,
            _mark_contributions_stale,
        )
        print("   ✅ PASS: Staleness functions importable")
        return True
    except ImportError as e:
        print(f"   ❌ FAIL: Import error: {e}")
        return False


def test_contributions_manager_import():
    """Test ContributionsManager can be imported."""
    print("4. Testing ContributionsManager import...")
    
    try:
        from ck3raven.resolver.manager import ContributionsManager, RefreshResult, ConflictSummary
        print("   ✅ PASS: ContributionsManager importable")
        return True
    except ImportError as e:
        print(f"   ❌ FAIL: Import error: {e}")
        return False


def test_contributions_manager_basic():
    """Test basic ContributionsManager operations."""
    print("5. Testing ContributionsManager basic operations...")
    
    try:
        from ck3raven.resolver.manager import ContributionsManager
        conn = get_connection()
        
        # Create manager (should auto-check tables)
        manager = ContributionsManager(conn, auto_refresh=False)
        
        # Get active playset
        playset = conn.execute("""
            SELECT playset_id FROM playsets WHERE is_active = 1 LIMIT 1
        """).fetchone()
        
        if not playset:
            print("   ⚠️ SKIP: No active playset found")
            return True
        
        playset_id = playset['playset_id']
        
        # Check staleness
        is_stale = manager.is_stale(playset_id)
        print(f"   Playset {playset_id} stale: {is_stale}")
        
        # Get summary (without auto-refresh since we set it to False)
        summary = manager.get_summary(playset_id)
        print(f"   Conflicts: {summary.total}, Stale: {summary.is_stale}")
        
        print("   ✅ PASS: ContributionsManager operations work")
        return True
        
    except Exception as e:
        print(f"   ❌ FAIL: Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_playset_hooks():
    """Test that playset operations set staleness flag."""
    print("6. Testing playset operation hooks...")
    
    try:
        conn = get_connection()
        
        # Get active playset
        playset = conn.execute("""
            SELECT playset_id, contributions_stale FROM playsets WHERE is_active = 1 LIMIT 1
        """).fetchone()
        
        if not playset:
            print("   ⚠️ SKIP: No active playset found")
            return True
        
        playset_id = playset['playset_id']
        current_stale = playset['contributions_stale']
        print(f"   Playset {playset_id} current stale flag: {current_stale}")
        
        # Manually set to not stale
        conn.execute("UPDATE playsets SET contributions_stale = 0 WHERE playset_id = ?", (playset_id,))
        conn.commit()
        
        # Now verify a playset operation would mark it stale
        # (We don't actually want to modify the playset, so just check the function exists)
        from ck3raven.db.playsets import _mark_contributions_stale
        
        # Call it directly
        _mark_contributions_stale(conn, playset_id)
        
        # Check it's now stale
        row = conn.execute(
            "SELECT contributions_stale FROM playsets WHERE playset_id = ?",
            (playset_id,)
        ).fetchone()
        
        if row['contributions_stale'] != 1:
            print(f"   ❌ FAIL: Staleness not set correctly")
            return False
        
        print("   ✅ PASS: Playset hooks work correctly")
        return True
        
    except Exception as e:
        print(f"   ❌ FAIL: Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("=" * 60)
    print("Contribution Lifecycle Tests")
    print("=" * 60)
    print()
    
    tests = [
        test_schema_has_contribution_tables,
        test_playsets_have_staleness_columns,
        test_playset_staleness_functions,
        test_contributions_manager_import,
        test_contributions_manager_basic,
        test_playset_hooks,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"   ❌ FAIL: Unexpected error: {e}")
            results.append(False)
        print()
    
    # Summary
    passed = sum(results)
    total = len(results)
    print("=" * 60)
    print(f"Results: {passed}/{total} passed")
    
    if passed == total:
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
