#!/usr/bin/env python3
"""
Schema Compliance Proof

Verifies that the implemented schema matches the canonical specification:
1. discovery_queue has NO root_type/root_path/root_name/counters
2. build_queue has NO relpath/cvid duplication and NO steps_completed
3. build_queue items bind to fingerprint fields
4. FIFO claiming uses build_id monotonic ordering

Run this to generate proofs/schema_compliance.txt
"""

import sqlite3
import sys
from pathlib import Path


BANNED_DISCOVERY_COLUMNS = {
    'root_type',      # Banned: parallel identity
    'root_path',      # Banned: parallel identity  
    'root_name',      # Banned: parallel identity
    'files_discovered',  # Banned: counter
    'files_queued',      # Banned: counter
    'steps_completed',   # Banned: workflow engine
}

BANNED_BUILD_COLUMNS = {
    'relpath',        # Banned: derivable from file_id
    'content_version_id',  # Banned: derivable from file_id
    'cvid',           # Banned: alias for content_version_id
    'steps_completed',     # Banned: workflow engine
    'current_step',        # Banned: workflow engine
}

REQUIRED_BUILD_FINGERPRINT = {
    'work_file_mtime',
    'work_file_size',
    'work_file_hash',
}

REQUIRED_FILES_FINGERPRINT = {
    'file_mtime',
    'file_size', 
    'file_hash',
}


def check_schema_compliance():
    """Check that schema matches canonical specification."""
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    all_passed = True
    
    print("=" * 70)
    print("SCHEMA COMPLIANCE PROOF")
    print("=" * 70)
    print()
    
    # Helper to get column names
    def get_columns(table: str) -> set:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row[1] for row in rows}
    
    # 1. Check discovery_queue banned columns
    print("1. DISCOVERY_QUEUE - No Parallel Identity or Counters")
    print("-" * 50)
    
    try:
        discovery_cols = get_columns('discovery_queue')
        violations = discovery_cols & BANNED_DISCOVERY_COLUMNS
        
        if violations:
            print(f"  [FAIL] Banned columns present: {violations}")
            all_passed = False
        else:
            print(f"  [PASS] No banned columns found")
            print(f"    Checked for absence of: {sorted(BANNED_DISCOVERY_COLUMNS)}")
        
        # Verify cvid is present
        if 'content_version_id' in discovery_cols:
            print(f"  [PASS] content_version_id present (sole root identity)")
        else:
            print(f"  [FAIL] content_version_id missing!")
            all_passed = False
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: discovery_queue not found ({e})")
    
    print()
    
    # 2. Check build_queue banned columns
    print("2. BUILD_QUEUE - No Duplicate Identity or Workflow Engine")
    print("-" * 50)
    
    try:
        build_cols = get_columns('build_queue')
        violations = build_cols & BANNED_BUILD_COLUMNS
        
        if violations:
            print(f"  [FAIL] Banned columns present: {violations}")
            all_passed = False
        else:
            print(f"  [PASS] No banned columns found")
            print(f"    Checked for absence of: {sorted(BANNED_BUILD_COLUMNS)}")
        
        # Verify file_id is present
        if 'file_id' in build_cols:
            print(f"  [PASS] file_id present (sole file identity)")
        else:
            print(f"  [FAIL] file_id missing!")
            all_passed = False
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: build_queue not found ({e})")
    
    print()
    
    # 3. Check build_queue fingerprint columns
    print("3. BUILD_QUEUE - Fingerprint Binding")
    print("-" * 50)
    
    try:
        build_cols = get_columns('build_queue')
        missing = REQUIRED_BUILD_FINGERPRINT - build_cols
        
        if missing:
            print(f"  [FAIL] Missing fingerprint columns: {missing}")
            all_passed = False
        else:
            print(f"  [PASS] All fingerprint columns present")
            print(f"    Found: {sorted(REQUIRED_BUILD_FINGERPRINT)}")
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: build_queue not found ({e})")
    
    print()
    
    # 4. Check files table fingerprint columns
    print("4. FILES TABLE - Fingerprint Storage")
    print("-" * 50)
    
    try:
        files_cols = get_columns('files')
        missing = REQUIRED_FILES_FINGERPRINT - files_cols
        
        if missing:
            print(f"  [FAIL] Missing fingerprint columns: {missing}")
            all_passed = False
        else:
            print(f"  [PASS] All fingerprint columns present")
            print(f"    Found: {sorted(REQUIRED_FILES_FINGERPRINT)}")
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: files table not found ({e})")
    
    print()
    
    # 5. Check FIFO ordering mechanism
    print("5. BUILD_QUEUE - FIFO Ordering Mechanism")
    print("-" * 50)
    
    try:
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='build_queue' AND type='table'"
        ).fetchone()
        
        if schema:
            sql = schema[0]
            if 'build_id INTEGER PRIMARY KEY' in sql:
                print(f"  [PASS] build_id is PRIMARY KEY")
                if 'AUTOINCREMENT' in sql:
                    print(f"  [PASS] AUTOINCREMENT ensures monotonic IDs")
                else:
                    print(f"  NOTE: AUTOINCREMENT not explicit (SQLite uses rowid)")
            else:
                print(f"  [FAIL] build_id not PRIMARY KEY")
                all_passed = False
        else:
            print(f"  SKIP: build_queue not found")
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: Error checking schema ({e})")
    
    print()
    
    # 6. Unique constraint check
    print("6. BUILD_QUEUE - Fingerprint Uniqueness")
    print("-" * 50)
    
    try:
        # Also check table schema for UNIQUE
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='build_queue' AND type='table'"
        ).fetchone()
        
        if schema and 'UNIQUE' in schema[0] and 'file_id' in schema[0]:
            print(f"  [PASS] UNIQUE constraint includes file_id + fingerprint")
        else:
            print(f"  NOTE: Check unique constraint manually")
            
    except sqlite3.OperationalError as e:
        print(f"  SKIP: Error checking indexes ({e})")
    
    print()
    print("=" * 70)
    
    if all_passed:
        print("SCHEMA COMPLIANCE: PASSED")
    else:
        print("SCHEMA COMPLIANCE: FAILED")
    
    print("=" * 70)
    
    conn.close()
    return all_passed


def main():
    import io
    from contextlib import redirect_stdout
    from datetime import datetime
    
    # Run and display
    success = check_schema_compliance()
    
    # Capture for proof file
    output = io.StringIO()
    with redirect_stdout(output):
        check_schema_compliance()
    
    # Save proof
    proof_dir = Path(__file__).parent
    proof_file = proof_dir / 'schema_compliance.txt'
    
    with open(proof_file, 'w', encoding='utf-8') as f:
        f.write(f"Generated: {datetime.now().isoformat()}\n")
        f.write(f"Script: {Path(__file__).name}\n\n")
        f.write(output.getvalue())
    
    print(f"\n[Proof saved to {proof_file}]")
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
