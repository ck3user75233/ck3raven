"""
Test script for the database layer.

Tests:
1. Database initialization
2. Content-addressed storage
3. Parser versioning
4. AST cache with deduplication
5. Symbol/reference extraction
"""

import sys
import tempfile
import os
from pathlib import Path

# Add source to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_database_init():
    """Test database initialization."""
    from ck3raven.db import init_database, get_connection, DATABASE_VERSION
    from ck3raven.db.schema import close_all_connections
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        conn = init_database(db_path)
        
        # Check version
        row = conn.execute("SELECT value FROM db_metadata WHERE key = 'schema_version'").fetchone()
        assert int(row['value']) == DATABASE_VERSION, f"Expected {DATABASE_VERSION}, got {row['value']}"
        
        # Check tables exist
        tables = conn.execute("""
            SELECT name FROM sqlite_master WHERE type='table' ORDER BY name
        """).fetchall()
        table_names = {r['name'] for r in tables}
        
        required_tables = {
            'db_metadata', 'content_versions',
            'file_contents', 'files', 'parsers', 'asts', 'symbols', 'refs',
            'builds', 'snapshots', 'snapshot_members',
            'exemplar_mods'
        }
        
        missing = required_tables - table_names
        assert not missing, f"Missing tables: {missing}"
        
        print("✓ Database initialization works")
        close_all_connections()


def test_content_hash():
    """Test content-addressed storage."""
    from ck3raven.db import compute_content_hash, compute_root_hash
    
    # Test content hashing
    content1 = b"test content"
    content2 = b"test content"
    content3 = b"different content"
    
    hash1 = compute_content_hash(content1)
    hash2 = compute_content_hash(content2)
    hash3 = compute_content_hash(content3)
    
    assert hash1 == hash2, "Same content should produce same hash"
    assert hash1 != hash3, "Different content should produce different hash"
    assert len(hash1) == 64, "SHA256 should be 64 hex chars"
    
    # Test root hash
    files1 = [("a.txt", "abc123"), ("b.txt", "def456")]
    files2 = [("b.txt", "def456"), ("a.txt", "abc123")]  # Different order
    files3 = [("a.txt", "abc123"), ("c.txt", "ghi789")]
    
    root1 = compute_root_hash(files1)
    root2 = compute_root_hash(files2)
    root3 = compute_root_hash(files3)
    
    assert root1 == root2, "Order shouldn't affect root hash"
    assert root1 != root3, "Different files should produce different root hash"
    
    print("✓ Content hashing works")


def test_parser_version():
    """Test parser versioning."""
    from ck3raven.db import (
        init_database, get_connection, 
        get_or_create_parser_version, PARSER_VERSION, get_current_parser_version
    )
    from ck3raven.db.schema import close_all_connections
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_database(db_path)
        conn = get_connection(db_path)
        
        # Create parser version
        pv1 = get_or_create_parser_version(conn)
        assert pv1.version_string == PARSER_VERSION
        assert pv1.parser_version_id is not None
        
        # Get again - should return same
        pv2 = get_or_create_parser_version(conn)
        assert pv1.parser_version_id == pv2.parser_version_id
        
        # Current parser version
        pv3 = get_current_parser_version(conn)
        assert pv3.parser_version_id == pv1.parser_version_id
        
        print("✓ Parser versioning works")
        close_all_connections()


def test_ast_cache():
    """Test AST caching."""
    from ck3raven.db import (
        init_database, get_connection,
        get_or_create_parser_version, compute_content_hash,
        store_ast, get_cached_ast, serialize_ast, deserialize_ast
    )
    from ck3raven.db.schema import close_all_connections
    from ck3raven.parser.parser import parse_source
    
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_database(db_path)
        conn = get_connection(db_path)
        
        # Ensure parser version exists
        pv = get_or_create_parser_version(conn)
        
        # Parse some CK3 content
        source = """
        test_event = {
            type = character_event
            title = "Test Event"
            trigger = { always = yes }
        }
        """
        
        content_hash = compute_content_hash(source.encode('utf-8'))
        ast = parse_source(source, "test.txt")
        
        # Store AST
        record = store_ast(conn, content_hash, ast, pv.parser_version_id)
        assert record.parse_ok == True
        assert record.node_count > 0
        
        # Retrieve AST
        cached = get_cached_ast(conn, content_hash, pv.parser_version_id)
        assert cached is not None
        assert cached.ast_id == record.ast_id
        
        # Different content - no cache
        other_hash = compute_content_hash(b"different content")
        not_cached = get_cached_ast(conn, other_hash, pv.parser_version_id)
        assert not_cached is None
        
        print("✓ AST caching works")
        close_all_connections()


def test_symbol_extraction():
    """Test symbol and reference extraction."""
    from ck3raven.db import (
        init_database, get_connection,
        serialize_ast, deserialize_ast,
        extract_symbols_from_ast, extract_refs_from_ast
    )
    from ck3raven.parser.parser import parse_source
    
    # Parse an event file
    source = """
    test_event.0001 = {
        type = character_event
        title = "Test Event"
        desc = "A test description"
        
        trigger = {
            has_trait = brave
        }
        
        option = {
            name = "OK"
            add_trait = ambitious
            trigger_event = test_event.0002
        }
    }
    """
    
    ast = parse_source(source, "events/test_events.txt")
    ast_dict = deserialize_ast(serialize_ast(ast))
    
    # Extract symbols (this is an event file)
    symbols = list(extract_symbols_from_ast(ast_dict, "events/test_events.txt", "hash123"))
    assert len(symbols) == 1
    assert symbols[0].name == "test_event.0001"
    assert symbols[0].kind == "event"
    
    # Extract references
    refs = list(extract_refs_from_ast(ast_dict, "events/test_events.txt", "hash123"))
    ref_names = {r.name for r in refs}
    assert "brave" in ref_names  # has_trait = brave
    assert "ambitious" in ref_names  # add_trait = ambitious
    assert "test_event.0002" in ref_names  # trigger_event
    
    print("✓ Symbol/reference extraction works")


def test_file_scan():
    """Test directory scanning."""
    from ck3raven.db import scan_directory, compute_content_hash
    
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        
        # Create test files
        (root / "common").mkdir()
        (root / "common" / "test.txt").write_text("content1")
        (root / "events").mkdir()
        (root / "events" / "event.txt").write_text("content2")
        (root / "gfx").mkdir()
        (root / "gfx" / "image.dds").write_bytes(b"DDS fake")
        
        # Scan
        files = list(scan_directory(root))
        
        assert len(files) >= 3
        
        relpaths = {f.relpath for f in files}
        assert "common/test.txt" in relpaths
        assert "events/event.txt" in relpaths
        
        print("✓ Directory scanning works")


def run_all_tests():
    """Run all tests."""
    print("\n=== ck3raven Database Layer Tests ===\n")
    
    test_database_init()
    test_content_hash()
    test_parser_version()
    test_ast_cache()
    test_symbol_extraction()
    test_file_scan()
    
    print("\n=== All tests passed! ===\n")


if __name__ == "__main__":
    run_all_tests()
