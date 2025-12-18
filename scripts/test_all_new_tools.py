#!/usr/bin/env python3
"""Final comprehensive test of all new tools."""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "ck3lens_mcp"))

print("="*70)
print("CK3RAVEN NEW TOOLS TEST SUITE")
print("="*70)

passed = 0
failed = 0

# Test 1: DB connection
try:
    from ck3raven.db.schema import get_connection
    db_path = Path.home() / '.ck3raven' / 'ck3raven.db'
    conn = get_connection(db_path)
    print("✅ Test 1: Database connection OK")
    passed += 1
except Exception as e:
    print(f"❌ Test 1: Database connection FAILED: {e}")
    failed += 1

# Test 2: Contribution tables exist
try:
    tables = conn.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name IN 
        ('contribution_units', 'conflict_units', 'conflict_candidates', 'resolution_choices')
    """).fetchall()
    assert len(tables) == 4, f"Expected 4 tables, got {len(tables)}"
    print("✅ Test 2: Contribution/conflict tables exist")
    passed += 1
except Exception as e:
    print(f"❌ Test 2: Tables check FAILED: {e}")
    failed += 1

# Test 3: DBQueries imports
try:
    from ck3lens.db_queries import DBQueries
    db = DBQueries(db_path)
    print("✅ Test 3: DBQueries imports OK")
    passed += 1
except Exception as e:
    print(f"❌ Test 3: DBQueries import FAILED: {e}")
    failed += 1

# Test 4: search_symbols
try:
    result = db.search_symbols(1, "brave", limit=5)
    assert len(result['results']) > 0, "No results"
    print("✅ Test 4: search_symbols works")
    passed += 1
except Exception as e:
    print(f"❌ Test 4: search_symbols FAILED: {e}")
    failed += 1

# Test 5: search_files
try:
    files = db.search_files(1, "%trait%", limit=5)
    assert len(files) > 0, "No files found"
    print("✅ Test 5: search_files works")
    passed += 1
except Exception as e:
    print(f"❌ Test 5: search_files FAILED: {e}")
    failed += 1

# Test 6: search_content
try:
    results = db.search_content(1, "brave", limit=5)
    assert len(results) > 0, "No content matches"
    print("✅ Test 6: search_content works")
    passed += 1
except Exception as e:
    print(f"❌ Test 6: search_content FAILED: {e}")
    failed += 1

# Test 7: confirm_not_exists
try:
    result = db.confirm_not_exists(1, "fake_nonexistent_symbol_12345")
    assert result['can_claim_not_exists'], "Should be able to claim not exists"
    print("✅ Test 7: confirm_not_exists works")
    passed += 1
except Exception as e:
    print(f"❌ Test 7: confirm_not_exists FAILED: {e}")
    failed += 1

# Test 8: Report generator
try:
    from ck3raven.resolver.report import ConflictsReportGenerator
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    gen = ConflictsReportGenerator(conn)
    report = gen.generate(1, paths_filter="common/on_action%", min_candidates=2)
    assert report.summary.file_conflicts > 0, "No file conflicts found"
    print(f"✅ Test 8: Report generator works ({report.summary.file_conflicts} file conflicts)")
    passed += 1
except Exception as e:
    print(f"❌ Test 8: Report generator FAILED: {e}")
    failed += 1

# Test 9: Report JSON export
try:
    from ck3raven.resolver.report import report_summary_cli
    json_out = report.to_json()
    assert '"schema": "ck3raven.conflicts.v1"' in json_out, "Invalid JSON schema"
    cli_out = report_summary_cli(report)
    assert "CK3Raven Conflicts Report" in cli_out, "Invalid CLI output"
    print("✅ Test 9: Report export (JSON/CLI) works")
    passed += 1
except Exception as e:
    print(f"❌ Test 9: Report export FAILED: {e}")
    failed += 1

# Test 10: get_file
try:
    file_result = db.get_file(1, relpath="common/traits/00_traits.txt")
    assert file_result is not None, "File not found"
    assert "brave" in file_result.get("content", ""), "Content doesn't contain expected text"
    print("✅ Test 10: get_file works")
    passed += 1
except Exception as e:
    print(f"❌ Test 10: get_file FAILED: {e}")
    failed += 1

# Summary
print("\n" + "="*70)
print(f"RESULTS: {passed} passed, {failed} failed")
print("="*70)

if failed == 0:
    print("\n🎉 ALL TESTS PASSED! Ready to restart VS Code.")
else:
    print(f"\n⚠️  {failed} test(s) failed. Please fix before restarting.")

conn.close()
