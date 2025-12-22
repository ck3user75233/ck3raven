#!/usr/bin/env python3
"""
Builder Pipeline Test Harness

Tests the full database build pipeline against a controlled pseudo_vanilla directory.
Validates that each phase works correctly and skip rules are applied.

Expected behavior:
- common/traits/*.txt       -> parse, extract symbols (trait definitions)
- common/decisions/*.txt    -> parse, extract symbols (decision definitions)
- common/on_actions/*.txt   -> parse, extract symbols (on_action definitions)
- events/*.txt              -> parse, extract symbols (event definitions)
- gfx/**/*.txt              -> SKIP entirely (never parse)
- gui/*.txt                 -> parse, SKIP symbol extraction
- localization/**/*.yml     -> use localization parser, extract loc keys
- history/characters/*.txt  -> parse, SKIP symbol extraction
- common/coat_of_arms/**    -> parse, SKIP symbol extraction
"""

import sys
import os
import time
import sqlite3
import tempfile
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

from ck3raven.db.schema import init_database, get_connection
from ck3raven.db.skip_rules import (
    should_skip_for_ast,
    should_skip_for_symbols,
    should_skip_for_refs,
    should_skip_for_localization
)

@dataclass
class PhaseResult:
    name: str
    duration_ms: float
    input_count: int
    output_count: int
    skipped_count: int
    error_count: int
    details: Dict[str, Any]

class PipelineTestHarness:
    def __init__(self, pseudo_vanilla_path: Path, db_path: Path = None):
        self.pseudo_vanilla = pseudo_vanilla_path
        self.db_path = db_path or Path(tempfile.mktemp(suffix='.db'))
        self.conn = None
        self.results: List[PhaseResult] = []
        
    def log(self, msg: str):
        print(f"[HARNESS] {msg}")
        
    def run_all_phases(self):
        """Run all pipeline phases with detailed logging."""
        self.log(f"Starting pipeline test with pseudo_vanilla: {self.pseudo_vanilla}")
        self.log(f"Database: {self.db_path}")
        
        # Phase 0: Initialize database
        self._run_phase_0_init()
        
        # Phase 1: File discovery and skip rule validation
        self._run_phase_1_discovery()
        
        # Phase 2: File ingestion
        self._run_phase_2_ingest()
        
        # Phase 3: AST generation
        self._run_phase_3_ast()
        
        # Phase 4: Symbol extraction
        self._run_phase_4_symbols()
        
        # Phase 5: Reference extraction
        self._run_phase_5_refs()
        
        # Phase 6: Localization (if applicable)
        self._run_phase_6_localization()
        
        # Summary
        self._print_summary()
        
        return self.results
    
    def _run_phase_0_init(self):
        """Initialize database schema."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 0: Database Initialization")
        self.log("="*60)
        
        init_database(self.db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        
        # Count tables
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        
        duration = (time.time() - start) * 1000
        self.log(f"  Created {len(tables)} tables in {duration:.1f}ms")
        
        self.results.append(PhaseResult(
            name="init",
            duration_ms=duration,
            input_count=0,
            output_count=len(tables),
            skipped_count=0,
            error_count=0,
            details={"tables": [t[0] for t in tables]}
        ))
    
    def _run_phase_1_discovery(self):
        """Discover files and validate skip rules."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 1: File Discovery & Skip Rule Validation")
        self.log("="*60)
        
        all_files = []
        for path in self.pseudo_vanilla.rglob('*'):
            if path.is_file():
                relpath = str(path.relative_to(self.pseudo_vanilla)).replace('\\', '/')
                all_files.append(relpath)
        
        self.log(f"  Found {len(all_files)} files")
        
        # Categorize by skip rules
        categories = {
            'parse_and_symbols': [],
            'parse_skip_symbols': [],
            'skip_entirely': [],
            'localization': [],
        }
        
        for relpath in all_files:
            skip_ast = should_skip_for_ast(relpath)[0]
            skip_sym = should_skip_for_symbols(relpath)[0]
            is_loc = relpath.startswith('localization/') and relpath.endswith('.yml')
            
            if is_loc:
                categories['localization'].append(relpath)
            elif skip_ast:
                categories['skip_entirely'].append(relpath)
            elif skip_sym:
                categories['parse_skip_symbols'].append(relpath)
            else:
                categories['parse_and_symbols'].append(relpath)
            
            self.log(f"    {relpath}")
            self.log(f"      skip_ast={skip_ast}, skip_symbols={skip_sym}, is_loc={is_loc}")
        
        duration = (time.time() - start) * 1000
        
        self.log(f"\n  Categories:")
        for cat, files in categories.items():
            self.log(f"    {cat}: {len(files)} files")
        
        self.results.append(PhaseResult(
            name="discovery",
            duration_ms=duration,
            input_count=len(all_files),
            output_count=len(all_files),
            skipped_count=0,
            error_count=0,
            details=categories
        ))
    
    def _run_phase_2_ingest(self):
        """Ingest files into database."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 2: File Ingestion")
        self.log("="*60)
        
        from ck3raven.db.content import ingest_content_version
        
        result = ingest_content_version(
            self.conn,
            content_root=self.pseudo_vanilla,
            source_type='vanilla',
            source_name='pseudo_vanilla'
        )
        
        duration = (time.time() - start) * 1000
        
        files_count = self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        content_count = self.conn.execute("SELECT COUNT(*) FROM file_contents").fetchone()[0]
        
        self.log(f"  Ingested {files_count} files, {content_count} unique contents")
        self.log(f"  Duration: {duration:.1f}ms")
        
        self.results.append(PhaseResult(
            name="ingest",
            duration_ms=duration,
            input_count=files_count,
            output_count=content_count,
            skipped_count=0,
            error_count=len(result.errors) if hasattr(result, 'errors') else 0,
            details={"files": files_count, "contents": content_count}
        ))
    
    def _run_phase_3_ast(self):
        """Generate ASTs."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 3: AST Generation")
        self.log("="*60)
        
        from ck3raven.parser import parse_source
        import json
        
        # Get files that should have ASTs generated
        files = self.conn.execute("""
            SELECT f.file_id, f.relpath, fc.content_hash, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0
        """).fetchall()
        
        parsed = 0
        skipped = 0
        errors = 0
        
        for row in files:
            file_id, relpath, content_hash, content = row
            
            if should_skip_for_ast(relpath)[0]:
                self.log(f"  SKIP AST: {relpath}")
                skipped += 1
                continue
            
            if relpath.startswith('localization/') and relpath.endswith('.yml'):
                self.log(f"  SKIP AST (loc): {relpath}")
                skipped += 1
                continue
            
            try:
                ast = parse_source(content, relpath)
                if ast:
                    # Store AST
                    ast_blob = json.dumps(ast).encode('utf-8')
                    self.conn.execute("""
                        INSERT OR REPLACE INTO asts 
                        (content_hash, parser_version_id, ast_blob, parse_ok, node_count)
                        VALUES (?, 1, ?, 1, ?)
                    """, (content_hash, ast_blob, len(str(ast))))
                    parsed += 1
                    self.log(f"  PARSED: {relpath} ({len(ast_blob)} bytes)")
                else:
                    errors += 1
                    self.log(f"  PARSE FAILED: {relpath}")
            except Exception as e:
                errors += 1
                self.log(f"  PARSE ERROR: {relpath}: {e}")
        
        self.conn.commit()
        duration = (time.time() - start) * 1000
        
        self.log(f"\n  Parsed: {parsed}, Skipped: {skipped}, Errors: {errors}")
        self.log(f"  Duration: {duration:.1f}ms")
        
        self.results.append(PhaseResult(
            name="ast",
            duration_ms=duration,
            input_count=len(files),
            output_count=parsed,
            skipped_count=skipped,
            error_count=errors,
            details={"parsed": parsed, "skipped": skipped, "errors": errors}
        ))
    
    def _run_phase_4_symbols(self):
        """Extract symbols from ASTs."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 4: Symbol Extraction")
        self.log("="*60)
        
        from ck3raven.db.symbols import extract_symbols_from_ast
        import json
        
        # Get ASTs
        asts = self.conn.execute("""
            SELECT a.ast_id, a.content_hash, a.ast_blob, f.file_id, f.relpath
            FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE a.parse_ok = 1 AND f.deleted = 0
        """).fetchall()
        
        extracted = 0
        skipped = 0
        total_symbols = 0
        
        for row in asts:
            ast_id, content_hash, ast_blob, file_id, relpath = row
            
            if should_skip_for_symbols(relpath)[0]:
                self.log(f"  SKIP SYMBOLS: {relpath}")
                skipped += 1
                continue
            
            try:
                ast_dict = json.loads(ast_blob.decode('utf-8'))
                symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
                
                for sym in symbols:
                    self.conn.execute("""
                        INSERT OR IGNORE INTO symbols
                        (symbol_type, name, scope, defining_ast_id, defining_file_id,
                         content_version_id, line_number)
                        VALUES (?, ?, ?, ?, ?, 
                                (SELECT content_version_id FROM files WHERE file_id = ?), ?)
                    """, (sym.kind, sym.name, getattr(sym, 'scope', None), 
                          ast_id, file_id, file_id, sym.line))
                
                total_symbols += len(symbols)
                extracted += 1
                self.log(f"  EXTRACTED: {relpath} -> {len(symbols)} symbols")
                for sym in symbols:
                    self.log(f"      {sym.kind}: {sym.name}")
                    
            except Exception as e:
                self.log(f"  SYMBOL ERROR: {relpath}: {e}")
        
        self.conn.commit()
        duration = (time.time() - start) * 1000
        
        self.log(f"\n  Extracted from: {extracted} files, Skipped: {skipped}, Total symbols: {total_symbols}")
        self.log(f"  Duration: {duration:.1f}ms")
        
        self.results.append(PhaseResult(
            name="symbols",
            duration_ms=duration,
            input_count=len(asts),
            output_count=total_symbols,
            skipped_count=skipped,
            error_count=0,
            details={"files_processed": extracted, "symbols": total_symbols}
        ))
    
    def _run_phase_5_refs(self):
        """Extract references from ASTs."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 5: Reference Extraction")
        self.log("="*60)
        
        # Simplified - just count what would be processed
        asts = self.conn.execute("""
            SELECT COUNT(*) FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE a.parse_ok = 1 AND f.deleted = 0
        """).fetchone()[0]
        
        duration = (time.time() - start) * 1000
        self.log(f"  Would process {asts} ASTs for references")
        self.log(f"  (Skipping actual ref extraction for test)")
        
        self.results.append(PhaseResult(
            name="refs",
            duration_ms=duration,
            input_count=asts,
            output_count=0,
            skipped_count=0,
            error_count=0,
            details={"note": "skipped for test"}
        ))
    
    def _run_phase_6_localization(self):
        """Process localization files."""
        start = time.time()
        self.log("\n" + "="*60)
        self.log("PHASE 6: Localization")
        self.log("="*60)
        
        loc_files = self.conn.execute("""
            SELECT f.file_id, f.relpath, fc.content_text
            FROM files f
            JOIN file_contents fc ON f.content_hash = fc.content_hash
            WHERE f.deleted = 0 AND f.relpath LIKE 'localization/%'
        """).fetchall()
        
        self.log(f"  Found {len(loc_files)} localization files")
        for row in loc_files:
            self.log(f"    {row[1]}")
        
        duration = (time.time() - start) * 1000
        
        self.results.append(PhaseResult(
            name="localization",
            duration_ms=duration,
            input_count=len(loc_files),
            output_count=0,
            skipped_count=0,
            error_count=0,
            details={"files": [r[1] for r in loc_files]}
        ))
    
    def _print_summary(self):
        """Print final summary."""
        self.log("\n" + "="*60)
        self.log("PIPELINE SUMMARY")
        self.log("="*60)
        
        total_time = sum(r.duration_ms for r in self.results)
        
        self.log(f"\n{'Phase':<15} {'Time (ms)':<12} {'Input':<10} {'Output':<10} {'Skipped':<10} {'Errors':<10}")
        self.log("-" * 70)
        
        for r in self.results:
            self.log(f"{r.name:<15} {r.duration_ms:<12.1f} {r.input_count:<10} {r.output_count:<10} {r.skipped_count:<10} {r.error_count:<10}")
        
        self.log("-" * 70)
        self.log(f"{'TOTAL':<15} {total_time:<12.1f}")
        
        # Final DB stats
        self.log("\n" + "="*60)
        self.log("FINAL DATABASE STATE")
        self.log("="*60)
        
        stats = {
            'files': self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
            'file_contents': self.conn.execute("SELECT COUNT(*) FROM file_contents").fetchone()[0],
            'asts': self.conn.execute("SELECT COUNT(*) FROM asts WHERE parse_ok=1").fetchone()[0],
            'symbols': self.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0],
        }
        
        for k, v in stats.items():
            self.log(f"  {k}: {v}")
        
        # Validate expectations
        self.log("\n" + "="*60)
        self.log("VALIDATION")
        self.log("="*60)
        
        # Check that gfx was skipped
        gfx_asts = self.conn.execute("""
            SELECT COUNT(*) FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE f.relpath LIKE 'gfx/%'
        """).fetchone()[0]
        
        if gfx_asts == 0:
            self.log("   gfx/ files correctly skipped for AST")
        else:
            self.log(f"   FAIL: gfx/ has {gfx_asts} ASTs (should be 0)")
        
        # Check that traits have symbols
        trait_symbols = self.conn.execute("""
            SELECT COUNT(*) FROM symbols WHERE symbol_type = 'trait'
        """).fetchone()[0]
        
        if trait_symbols >= 3:
            self.log(f"   Trait symbols extracted: {trait_symbols}")
        else:
            self.log(f"   FAIL: Only {trait_symbols} trait symbols (expected >= 3)")
        
        # Check that gui was parsed but no symbols
        gui_asts = self.conn.execute("""
            SELECT COUNT(*) FROM asts a
            JOIN files f ON a.content_hash = f.content_hash
            WHERE f.relpath LIKE 'gui/%'
        """).fetchone()[0]
        
        gui_symbols = self.conn.execute("""
            SELECT COUNT(*) FROM symbols s
            JOIN files f ON s.defining_file_id = f.file_id
            WHERE f.relpath LIKE 'gui/%'
        """).fetchone()[0]
        
        if gui_asts > 0 and gui_symbols == 0:
            self.log(f"   gui/ parsed ({gui_asts} ASTs) but no symbols extracted")
        else:
            self.log(f"   FAIL: gui/ has {gui_asts} ASTs and {gui_symbols} symbols")


if __name__ == "__main__":
    # Find pseudo_vanilla
    script_dir = Path(__file__).parent
    pseudo_vanilla = script_dir / "fixtures" / "pseudo_vanilla"
    
    if not pseudo_vanilla.exists():
        print(f"ERROR: pseudo_vanilla not found at {pseudo_vanilla}")
        sys.exit(1)
    
    # Use temp database
    import tempfile
    db_path = Path(tempfile.mktemp(suffix='_test.db'))
    
    try:
        harness = PipelineTestHarness(pseudo_vanilla, db_path)
        harness.run_all_phases()
    finally:
        # Cleanup
        if db_path.exists():
            db_path.unlink()
            print(f"\nCleaned up test database: {db_path}")

