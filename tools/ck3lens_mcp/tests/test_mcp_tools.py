"""
CK3 Lens MCP Tools Test Suite

Tests to validate:
1. All tools can be imported and called
2. Database connectivity and queries work
3. Active mods are in the database
4. Live mod operations work (sandboxed)
5. Validation tools work correctly

Run with: python -m pytest tests/test_mcp_tools.py -v
Or directly: python tests/test_mcp_tools.py
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from typing import Optional

# Add paths
TOOLS_ROOT = Path(__file__).parent.parent
CK3RAVEN_SRC = TOOLS_ROOT.parent.parent / "src"
sys.path.insert(0, str(TOOLS_ROOT))
sys.path.insert(0, str(CK3RAVEN_SRC))


# =============================================================================
# TEST CONFIGURATION
# =============================================================================

# Expected active mods (from playset_manifest.json)
EXPECTED_MODS = [
    "Mini Super Compatch",
    "CrashFixes", 
    "LocalizationPatch",
]

# Sample symbols we expect to find (adjust based on your database)
EXPECTED_SYMBOLS = [
    ("trait", "brave"),
    ("trait", "craven"),
    ("decision", None),  # Any decision
    ("on_action", None),  # Any on_action
]

# Sample CK3 script for validation tests
VALID_CK3_SCRIPT = """
test_trait = {
    index = 999
    desc = test_trait_desc
    icon = "gfx/test.dds"
    
    diplomacy = 5
    martial = -2
    
    opposite = opposite_test_trait
}
"""

INVALID_CK3_SCRIPT = """
test_trait = {
    index = 999
    desc = test_trait_desc
    # Missing closing brace
"""


# =============================================================================
# TEST UTILITIES
# =============================================================================

class TestResult:
    """Track test results."""
    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors: list[str] = []
    
    def ok(self, msg: str):
        self.passed += 1
        print(f"  ✓ {msg}")
    
    def fail(self, msg: str, error: str = ""):
        self.failed += 1
        self.errors.append(f"{msg}: {error}")
        print(f"  ✗ {msg}")
        if error:
            print(f"    Error: {error}")
    
    def skip(self, msg: str, reason: str = ""):
        self.skipped += 1
        print(f"  ⊘ {msg} (skipped: {reason})")
    
    def summary(self):
        total = self.passed + self.failed + self.skipped
        status = "PASS" if self.failed == 0 else "FAIL"
        print(f"\n{self.name}: {status} ({self.passed}/{total} passed, {self.skipped} skipped)")
        return self.failed == 0


def run_test_group(name: str, tests: list):
    """Run a group of tests and return results."""
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    
    result = TestResult(name)
    for test_fn in tests:
        try:
            test_fn(result)
        except Exception as e:
            result.fail(test_fn.__name__, str(e))
    
    return result


# =============================================================================
# TEST 1: MODULE IMPORTS
# =============================================================================

def test_import_server(r: TestResult):
    """Test that server module imports correctly."""
    try:
        from server import mcp
        r.ok("server.py imports")
    except Exception as e:
        r.fail("server.py imports", str(e))


def test_import_ck3lens_modules(r: TestResult):
    """Test that all ck3lens submodules import."""
    modules = [
        "ck3lens.workspace",
        "ck3lens.db_queries", 
        "ck3lens.local_mods",
        "ck3lens.git_ops",
        "ck3lens.validate",
        "ck3lens.contracts",
        "ck3lens.trace",
    ]
    for mod in modules:
        try:
            __import__(mod)
            r.ok(f"import {mod}")
        except Exception as e:
            r.fail(f"import {mod}", str(e))


def test_mcp_tools_registered(r: TestResult):
    """Test that all expected MCP tools are registered."""
    from server import mcp
    
    expected_tools = [
        "ck3_init_session",
        "ck3_search_symbols",
        "ck3_confirm_not_exists",
        "ck3_get_file",
        "ck3_qr_conflicts",
        "ck3_list_local_mods",
        "ck3_read_local_file",
        "ck3_write_file",
        "ck3_edit_file",
        "ck3_delete_file",
        "ck3_list_local_files",
        "ck3_parse_content",
        "ck3_validate_patchdraft",
        "ck3_git_status",
        "ck3_git_diff",
        "ck3_git_add",
        "ck3_git_commit",
        "ck3_git_push",
        "ck3_git_pull",
        "ck3_git_log",
    ]
    
    registered = list(mcp._tool_manager._tools.keys())
    
    for tool in expected_tools:
        if tool in registered:
            r.ok(f"tool registered: {tool}")
        else:
            r.fail(f"tool registered: {tool}", "not found in registry")


# =============================================================================
# TEST 2: DATABASE CONNECTION & QUERIES
# =============================================================================

def test_database_exists(r: TestResult):
    """Test that ck3raven database exists."""
    from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection
    
    # Try default path
    if DEFAULT_DB_PATH.exists():
        r.ok(f"database exists at {DEFAULT_DB_PATH}")
        return
    
    # Try workspace locations
    alt_paths = [
        Path(__file__).parent.parent.parent.parent / "ck3raven.db",
        Path.home() / ".ck3raven" / "ck3raven.db",
    ]
    
    for p in alt_paths:
        if p.exists():
            r.ok(f"database exists at {p}")
            return
    
    r.skip("database exists", "no database found - run indexer first")


def test_database_schema(r: TestResult):
    """Test that database has expected tables."""
    from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection
    
    if not DEFAULT_DB_PATH.exists():
        r.skip("database schema", "no database")
        return
    
    conn = get_connection(DEFAULT_DB_PATH)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    
    expected_tables = ["file_contents", "symbols", "content_versions", "file_versions"]
    
    for table in expected_tables:
        if table in tables:
            r.ok(f"table exists: {table}")
        else:
            r.fail(f"table exists: {table}", f"found tables: {tables}")


def test_database_has_content(r: TestResult):
    """Test that database has indexed content."""
    from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection
    
    if not DEFAULT_DB_PATH.exists():
        r.skip("database has content", "no database")
        return
    
    conn = get_connection(DEFAULT_DB_PATH)
    
    # Check file count
    cursor = conn.execute("SELECT COUNT(*) FROM file_contents")
    file_count = cursor.fetchone()[0]
    
    if file_count > 0:
        r.ok(f"database has {file_count} file contents")
    else:
        r.fail("database has content", "no files indexed")
    
    # Check symbol count
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM symbols")
        symbol_count = cursor.fetchone()[0]
        
        if symbol_count > 0:
            r.ok(f"database has {symbol_count} symbols")
        else:
            r.fail("database has symbols", "no symbols indexed")
    except Exception as e:
        r.skip("database has symbols", str(e))


def test_mods_in_database(r: TestResult):
    """Test that expected mods are in the database."""
    from ck3raven.db.schema import DEFAULT_DB_PATH, get_connection
    
    if not DEFAULT_DB_PATH.exists():
        r.skip("mods in database", "no database")
        return
    
    conn = get_connection(DEFAULT_DB_PATH)
    
    try:
        cursor = conn.execute("SELECT name FROM mod_packages")
        db_mods = [row[0] for row in cursor.fetchall()]
        
        for mod_name in EXPECTED_MODS:
            if any(mod_name.lower() in m.lower() for m in db_mods):
                r.ok(f"mod in database: {mod_name}")
            else:
                r.fail(f"mod in database: {mod_name}", f"found: {db_mods}")
    except Exception as e:
        r.skip("mods in database", str(e))


# =============================================================================
# TEST 3: SYMBOL SEARCH
# =============================================================================

def test_adjacency_pattern_expansion(r: TestResult):
    """Test that adjacency patterns expand correctly."""
    from ck3lens.db_queries import expand_query_patterns
    
    patterns = expand_query_patterns("combat_skill")
    pattern_types = [p[1] for p in patterns]
    
    if "exact" in pattern_types:
        r.ok("adjacency: exact pattern included")
    else:
        r.fail("adjacency: exact pattern", "not found")
    
    if "prefix" in pattern_types:
        r.ok("adjacency: prefix pattern included")
    else:
        r.fail("adjacency: prefix pattern", "not found")
    
    if len(patterns) >= 4:
        r.ok(f"adjacency: {len(patterns)} patterns generated")
    else:
        r.fail("adjacency: pattern count", f"only {len(patterns)} patterns")


def test_symbol_search_exact(r: TestResult):
    """Test exact symbol search."""
    from ck3raven.db.schema import DEFAULT_DB_PATH
    
    if not DEFAULT_DB_PATH.exists():
        r.skip("symbol search", "no database")
        return
    
    from ck3lens.db_queries import DBQueries
    
    try:
        db = DBQueries()
        results = db.search_symbols("brave", symbol_type="trait", adjacency="strict", limit=10)
        
        if results:
            r.ok(f"found trait 'brave': {len(results)} matches")
        else:
            r.skip("trait 'brave' search", "not in database (may need indexing)")
    except Exception as e:
        r.fail("symbol search", str(e))


def test_confirm_not_exists(r: TestResult):
    """Test confirm_not_exists for exhaustive search."""
    from ck3raven.db.schema import DEFAULT_DB_PATH
    
    if not DEFAULT_DB_PATH.exists():
        r.skip("confirm_not_exists", "no database")
        return
    
    from ck3lens.db_queries import DBQueries
    
    try:
        db = DBQueries()
        
        # Search for something that definitely doesn't exist
        result = db.confirm_not_exists("zzz_nonexistent_trait_xyzzy_12345")
        
        if result["can_claim_not_exists"]:
            r.ok("confirm_not_exists: correctly reports nonexistent symbol")
        else:
            r.fail("confirm_not_exists", f"found similar: {result['similar_matches']}")
    except Exception as e:
        r.fail("confirm_not_exists", str(e))


# =============================================================================
# TEST 4: LOCAL MOD OPERATIONS
# =============================================================================

def test_session_initialization(r: TestResult):
    """Test session can be initialized."""
    from ck3lens.workspace import Session
    
    try:
        session = Session()
        r.ok(f"session initialized with mod_root: {session.mod_root}")
        r.ok(f"local mods configured: {len(session.local_mods)}")
    except Exception as e:
        r.fail("session initialization", str(e))


def test_local_mods_discovery(r: TestResult):
    """Test that local mods are discovered on disk."""
    from ck3lens.workspace import Session
    from ck3lens.local_mods import list_local_mods
    
    try:
        session = Session()
        mods = list_local_mods(session)
        
        if mods:
            r.ok(f"discovered {len(mods)} local mods on disk")
            for mod in mods:
                r.ok(f"  - {mod['name']}")
        else:
            r.skip("local mods discovery", "no local mods configured")
    except Exception as e:
        r.fail("local mods discovery", str(e))


def test_local_file_listing(r: TestResult):
    """Test listing files in a local mod."""
    from ck3lens.workspace import Session
    from ck3lens.local_mods import list_local_mods, list_local_files
    
    try:
        session = Session()
        mods = list_local_mods(session)
        
        if not mods:
            r.skip("local file listing", "no local mods configured")
            return
        
        mod_name = mods[0]["name"]
        result = list_local_files(session, mod_name, path_prefix="common", pattern="*.txt")
        
        if result.get("success"):
            files = result.get("files", [])
            r.ok(f"listed {len(files)} .txt files in {mod_name}/common/")
        else:
            r.fail("local file listing", result.get("error", "unknown error"))
    except Exception as e:
        r.fail("local file listing", str(e))


def test_path_validation(r: TestResult):
    """Test that path traversal is blocked."""
    from ck3lens.workspace import Session
    
    session = Session()
    
    # Should be blocked
    bad_paths = [
        "../../etc/passwd",
        "/absolute/path",
        "C:\\Windows\\System32",
        "common\\..\\..\\secrets",
    ]
    
    for path in bad_paths:
        if not session.is_path_allowed(path, "AnyMod"):
            r.ok(f"blocked bad path: {path[:30]}...")
        else:
            r.fail(f"path validation", f"allowed bad path: {path}")


# =============================================================================
# TEST 5: VALIDATION TOOLS
# =============================================================================

def test_parse_valid_ck3_script(r: TestResult):
    """Test parsing valid CK3 script."""
    from ck3lens.validate import parse_content
    
    result = parse_content(VALID_CK3_SCRIPT, "test.txt")
    
    if result["success"]:
        r.ok("parsed valid CK3 script")
        if result.get("ast"):
            r.ok("AST returned")
    else:
        r.fail("parse valid script", str(result.get("errors")))


def test_parse_invalid_ck3_script(r: TestResult):
    """Test that invalid CK3 script returns errors."""
    from ck3lens.validate import parse_content
    
    result = parse_content(INVALID_CK3_SCRIPT, "test.txt")
    
    if not result["success"]:
        r.ok("correctly detected invalid CK3 script")
        if result.get("errors"):
            r.ok(f"returned {len(result['errors'])} error(s)")
    else:
        r.fail("detect invalid script", "parser did not catch syntax error")


def test_patchdraft_validation(r: TestResult):
    """Test PatchDraft validation."""
    from ck3lens.validate import validate_patchdraft
    from ck3lens.contracts import PatchDraft, PatchFile
    
    # Valid draft
    valid_draft = PatchDraft(
        message="Test patch",
        patches=[
            PatchFile(
                path="common/traits/zzz_test.txt",
                content=VALID_CK3_SCRIPT,
                format="ck3_script"
            )
        ]
    )
    
    report = validate_patchdraft(valid_draft)
    
    if report.ok:
        r.ok("valid PatchDraft passes validation")
    else:
        r.fail("valid PatchDraft", str(report.errors))
    
    # Invalid path
    invalid_path_draft = PatchDraft(
        message="Bad path",
        patches=[
            PatchFile(
                path="../escape/attempt.txt",
                content="test = yes",
                format="ck3_script"
            )
        ]
    )
    
    report = validate_patchdraft(invalid_path_draft)
    
    if not report.ok:
        r.ok("invalid path rejected")
    else:
        r.fail("invalid path detection", "path traversal not caught")


# =============================================================================
# TEST 6: GIT OPERATIONS
# =============================================================================

def test_git_status_no_crash(r: TestResult):
    """Test that git status doesn't crash (may not have git repo)."""
    from ck3lens.workspace import Session
    from ck3lens.git_ops import git_status
    from ck3lens.local_mods import list_local_mods
    
    try:
        session = Session()
        mods = list_local_mods(session)
        
        if not mods:
            r.skip("git status", "no local mods configured")
            return
        
        mod_name = mods[0]["name"]
        result = git_status(session, mod_name)
        
        # Just check it doesn't crash - may or may not be a git repo
        if result.get("success"):
            r.ok(f"git status succeeded for {mod_name}")
        else:
            if "not a git repository" in result.get("error", "").lower():
                r.skip("git status", f"{mod_name} is not a git repo")
            else:
                r.fail("git status", result.get("error"))
    except Exception as e:
        r.fail("git status", str(e))


# =============================================================================
# MAIN TEST RUNNER
# =============================================================================

def run_all_tests():
    """Run all test groups."""
    results = []
    
    # Test Group 1: Module Imports
    results.append(run_test_group("Module Imports", [
        test_import_server,
        test_import_ck3lens_modules,
        test_mcp_tools_registered,
    ]))
    
    # Test Group 2: Database
    results.append(run_test_group("Database Connection", [
        test_database_exists,
        test_database_schema,
        test_database_has_content,
        test_mods_in_database,
    ]))
    
    # Test Group 3: Symbol Search
    results.append(run_test_group("Symbol Search", [
        test_adjacency_pattern_expansion,
        test_symbol_search_exact,
        test_confirm_not_exists,
    ]))
    
    # Test Group 4: Local Mod Operations
    results.append(run_test_group("Local Mod Operations", [
        test_session_initialization,
        test_local_mods_discovery,
        test_local_file_listing,
        test_path_validation,
    ]))
    
    # Test Group 5: Validation
    results.append(run_test_group("Validation Tools", [
        test_parse_valid_ck3_script,
        test_parse_invalid_ck3_script,
        test_patchdraft_validation,
    ]))
    
    # Test Group 6: Git
    results.append(run_test_group("Git Operations", [
        test_git_status_no_crash,
    ]))
    
    # Summary
    print("\n" + "="*60)
    print("  SUMMARY")
    print("="*60)
    
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    total_skipped = sum(r.skipped for r in results)
    
    for r in results:
        status = "✓" if r.failed == 0 else "✗"
        print(f"  {status} {r.name}: {r.passed} passed, {r.failed} failed, {r.skipped} skipped")
    
    print(f"\nTotal: {total_passed} passed, {total_failed} failed, {total_skipped} skipped")
    
    if total_failed > 0:
        print("\n❌ SOME TESTS FAILED")
        return 1
    else:
        print("\n✅ ALL TESTS PASSED")
        return 0


if __name__ == "__main__":
    sys.exit(run_all_tests())
