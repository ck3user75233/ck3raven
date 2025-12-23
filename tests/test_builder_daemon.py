#!/usr/bin/env python3
"""
Builder Daemon Integration Tests

These tests invoke the actual builder.daemon module to verify that:
1. The builder runs to completion without errors
2. A manifest is produced
3. The database contains expected tables and data
4. Build steps are recorded properly

This is the ONLY place where the full pipeline should be tested.
Side scripts that bypass the builder are not permitted.
"""

import sys
import os
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


class TestBuilderDaemon:
    """Integration tests for the builder daemon."""
    
    @pytest.fixture
    def test_db_path(self, tmp_path):
        """Create a temp database path for testing."""
        return tmp_path / "test_builder.db"
    
    @pytest.fixture
    def vanilla_fixture_path(self):
        """Path to the vanilla sample fixture."""
        fixture = Path(__file__).parent / "fixtures" / "vanilla_sample"
        if not fixture.exists():
            pytest.skip(f"Fixture not found: {fixture}")
        return fixture
    
    def test_daemon_imports(self):
        """Test that daemon module imports without errors."""
        from builder.daemon import (
            run_rebuild, 
            BuildTracker, 
            StepStats,
            DaemonLogger, 
            StatusWriter,
            BUILDER_VERSION,
            MANIFEST_FILE
        )
        
        assert BUILDER_VERSION is not None
        assert MANIFEST_FILE is not None
    
    def test_build_tracker_creates_build_id(self, test_db_path):
        """Test that BuildTracker generates a unique build_id."""
        from ck3raven.db.schema import init_database
        from builder.daemon import BuildTracker, DaemonLogger
        
        init_database(test_db_path)
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        
        logger = DaemonLogger(test_db_path.parent / "test.log")
        tracker = BuildTracker(conn, logger)
        
        assert tracker.build_id is not None
        assert len(tracker.build_id) == 36  # UUID format
        
        # Verify recorded in database
        row = conn.execute(
            "SELECT build_id, state FROM builder_runs WHERE build_id = ?",
            (tracker.build_id,)
        ).fetchone()
        
        assert row is not None
        assert row['state'] == 'running'
        
        conn.close()
    
    def test_build_lock_prevents_concurrent_builds(self, test_db_path):
        """Test that build lock prevents concurrent builds."""
        from ck3raven.db.schema import init_database
        from builder.daemon import BuildTracker, DaemonLogger
        
        init_database(test_db_path)
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        
        logger = DaemonLogger(test_db_path.parent / "test.log")
        
        # First tracker acquires lock
        tracker1 = BuildTracker(conn, logger)
        assert tracker1.acquire_lock() == True
        
        # Second tracker cannot acquire lock
        tracker2 = BuildTracker(conn, logger)
        assert tracker2.acquire_lock() == False
        
        # After release, can acquire again
        tracker1.release_lock()
        assert tracker2.acquire_lock() == True
        
        tracker2.release_lock()
        conn.close()
    
    def test_step_tracking(self, test_db_path):
        """Test that build steps are properly recorded."""
        from ck3raven.db.schema import init_database
        from builder.daemon import BuildTracker, StepStats, DaemonLogger
        import time
        
        init_database(test_db_path)
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        
        logger = DaemonLogger(test_db_path.parent / "test.log")
        tracker = BuildTracker(conn, logger)
        
        # Start a step
        tracker.start_step("test_step")
        time.sleep(0.1)  # Small delay to ensure measurable duration
        
        # End the step with stats
        stats = StepStats(rows_in=10, rows_out=8, rows_skipped=1, rows_errored=1)
        tracker.end_step("test_step", stats)
        
        # Verify recorded
        row = conn.execute("""
            SELECT step_name, state, rows_in, rows_out, rows_skipped, rows_errored, duration_sec
            FROM builder_steps WHERE build_id = ? AND step_name = 'test_step'
        """, (tracker.build_id,)).fetchone()
        
        assert row is not None
        assert row['state'] == 'complete'
        assert row['rows_in'] == 10
        assert row['rows_out'] == 8
        assert row['rows_skipped'] == 1
        assert row['rows_errored'] == 1
        assert row['duration_sec'] > 0
        
        conn.close()
    
    def test_manifest_generation(self, test_db_path, tmp_path):
        """Test that manifest is generated on build completion."""
        from ck3raven.db.schema import init_database
        from builder.daemon import BuildTracker, StepStats, DaemonLogger, DAEMON_DIR
        import builder.daemon as daemon_module
        
        init_database(test_db_path)
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        
        # Redirect manifest to temp path
        original_manifest = daemon_module.MANIFEST_FILE
        daemon_module.MANIFEST_FILE = tmp_path / "build_manifest.json"
        
        try:
            logger = DaemonLogger(test_db_path.parent / "test.log")
            tracker = BuildTracker(conn, logger)
            tracker.acquire_lock()
            
            # Record a step
            tracker.start_step("test_step")
            tracker.end_step("test_step", StepStats(rows_out=100))
            
            # Complete the build
            counts = {'files': 50, 'asts': 45, 'symbols': 1000, 'refs': 500, 'localization': 2000, 'lookups': 100}
            tracker.complete(counts)
            
            # Verify manifest exists
            manifest_path = daemon_module.MANIFEST_FILE
            assert manifest_path.exists()
            
            # Verify manifest contents
            manifest = json.loads(manifest_path.read_text())
            
            assert manifest['build_id'] == tracker.build_id
            assert manifest['counts']['files'] == 50
            assert manifest['counts']['symbols'] == 1000
            assert len(manifest['steps']) == 1
            assert manifest['steps'][0]['name'] == 'test_step'
            assert manifest['steps'][0]['rows_out'] == 100
            
        finally:
            daemon_module.MANIFEST_FILE = original_manifest
            conn.close()
    
    def test_full_pipeline_on_fixture(self, test_db_path, vanilla_fixture_path, tmp_path):
        """
        Run the full builder pipeline on the vanilla fixture.
        
        This is the main integration test that verifies the entire pipeline works.
        """
        from ck3raven.db.schema import init_database
        from builder.daemon import (
            run_rebuild, DaemonLogger, StatusWriter, DatabaseWrapper,
            DAEMON_DIR, MANIFEST_FILE
        )
        import builder.daemon as daemon_module
        
        # Redirect daemon files to temp path
        original_daemon_dir = daemon_module.DAEMON_DIR
        original_manifest = daemon_module.MANIFEST_FILE
        daemon_module.DAEMON_DIR = tmp_path / "daemon"
        daemon_module.DAEMON_DIR.mkdir(parents=True, exist_ok=True)
        daemon_module.MANIFEST_FILE = daemon_module.DAEMON_DIR / "build_manifest.json"
        
        # Create log and status files
        log_file = daemon_module.DAEMON_DIR / "rebuild.log"
        status_file = daemon_module.DAEMON_DIR / "rebuild_status.json"
        
        try:
            logger = DaemonLogger(log_file)
            status = StatusWriter(status_file)
            
            # Run the full rebuild
            run_rebuild(
                db_path=test_db_path,
                force=True,
                logger=logger,
                status=status,
                symbols_only=False,
                vanilla_path=str(vanilla_fixture_path),
                skip_mods=True  # Skip mod ingestion for fixture test
            )
            
            # Verify status shows completion
            final_status = status.get()
            assert final_status['state'] == 'complete', f"Build failed: {final_status.get('error')}"
            
            # Verify manifest was generated
            manifest_path = daemon_module.MANIFEST_FILE
            assert manifest_path.exists(), "Manifest not generated"
            
            manifest = json.loads(manifest_path.read_text())
            assert manifest['counts']['files'] > 0
            assert manifest['counts']['asts'] > 0
            assert manifest['counts']['symbols'] > 0
            
            # Verify database contents
            conn = sqlite3.connect(test_db_path)
            conn.row_factory = sqlite3.Row
            
            # Check files table
            file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            assert file_count > 0, "No files ingested"
            
            # Check ASTs table
            ast_count = conn.execute("SELECT COUNT(*) FROM asts WHERE parse_ok = 1").fetchone()[0]
            assert ast_count > 0, "No ASTs generated"
            
            # Check symbols table
            symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
            assert symbol_count > 0, "No symbols extracted"
            
            # Check builder_runs table
            build_run = conn.execute("""
                SELECT build_id, state, files_ingested, symbols_extracted
                FROM builder_runs ORDER BY started_at DESC LIMIT 1
            """).fetchone()
            assert build_run is not None, "No build run recorded"
            assert build_run['state'] == 'complete'
            
            # Check builder_steps table
            step_count = conn.execute(
                "SELECT COUNT(*) FROM builder_steps WHERE build_id = ?",
                (build_run['build_id'],)
            ).fetchone()[0]
            assert step_count >= 5, f"Expected at least 5 steps, got {step_count}"
            
            # Verify specific symbol types
            trait_count = conn.execute(
                "SELECT COUNT(*) FROM symbols WHERE symbol_type = 'trait'"
            ).fetchone()[0]
            assert trait_count > 0, "No traits extracted"
            
            conn.close()
            
            print(f"\n[TEST PASSED] Full pipeline test:")
            print(f"  Files ingested: {file_count}")
            print(f"  ASTs generated: {ast_count}")
            print(f"  Symbols extracted: {symbol_count}")
            print(f"  Traits: {trait_count}")
            print(f"  Build steps recorded: {step_count}")
            
        finally:
            daemon_module.DAEMON_DIR = original_daemon_dir
            daemon_module.MANIFEST_FILE = original_manifest
    
    def test_failed_build_records_error(self, test_db_path, tmp_path):
        """Test that failed builds are recorded with error messages."""
        from ck3raven.db.schema import init_database
        from builder.daemon import BuildTracker, DaemonLogger, StepStats
        
        init_database(test_db_path)
        conn = sqlite3.connect(test_db_path)
        conn.row_factory = sqlite3.Row
        
        logger = DaemonLogger(tmp_path / "test.log")
        tracker = BuildTracker(conn, logger, vanilla_path="/nonexistent/path")
        tracker.acquire_lock()
        
        # Simulate a failure
        tracker.start_step("failing_step")
        tracker.end_step("failing_step", StepStats(), success=False, error="Test error message")
        tracker.fail("Build failed intentionally for test")
        
        # Verify recorded
        row = conn.execute("""
            SELECT state, error_message FROM builder_runs WHERE build_id = ?
        """, (tracker.build_id,)).fetchone()
        
        assert row['state'] == 'failed'
        assert row['error_message'] == "Build failed intentionally for test"
        
        conn.close()


class TestSchemaChanges:
    """Test that schema changes were applied correctly."""
    
    def test_builder_tables_exist(self, tmp_path):
        """Test that new builder tracking tables exist."""
        from ck3raven.db.schema import init_database, DATABASE_VERSION
        
        db_path = tmp_path / "test.db"
        init_database(db_path)
        
        conn = sqlite3.connect(db_path)
        
        # Check builder_runs table
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='builder_runs'
        """)
        assert cursor.fetchone() is not None, "builder_runs table missing"
        
        # Check builder_steps table
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='builder_steps'
        """)
        assert cursor.fetchone() is not None, "builder_steps table missing"
        
        # Check build_lock table
        cursor = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='build_lock'
        """)
        assert cursor.fetchone() is not None, "build_lock table missing"
        
        # Verify schema version bumped
        assert DATABASE_VERSION >= 2
        
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
