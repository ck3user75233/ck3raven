#!/usr/bin/env python3
"""
Populate Symbols Table

Extracts symbols from files already in the database.
Run after build_database.py to fill the symbols table.
"""

import sys
import logging
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ck3raven.db.schema import get_connection, DEFAULT_DB_PATH
from ck3raven.parser import parse_source
from ck3raven.db.symbols import extract_symbols_from_ast, extract_refs_from_ast

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def main():
    conn = get_connection(DEFAULT_DB_PATH)
    conn.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    
    # Count files
    row = conn.execute("SELECT COUNT(*) as cnt FROM files WHERE deleted = 0").fetchone()
    total_files = row['cnt']
    logger.info(f"Total files in database: {total_files}")
    
    # Get files with parseable extensions
    cursor = conn.execute("""
        SELECT f.file_id, f.relpath, f.content_hash, f.content_version_id
        FROM files f
        WHERE f.deleted = 0
        AND (
            f.relpath LIKE '%.txt'
            OR f.relpath LIKE 'events/%.txt'
        )
        ORDER BY f.file_id
    """)
    
    files = cursor.fetchall()
    logger.info(f"Parseable files to process: {len(files)}")
    
    total_symbols = 0
    total_refs = 0
    errors = 0
    
    for i, file_row in enumerate(files):
        file_id = file_row['file_id']
        relpath = file_row['relpath']
        content_hash = file_row['content_hash']
        content_version_id = file_row['content_version_id']
        
        if i > 0 and i % 1000 == 0:
            logger.info(f"  Progress: {i}/{len(files)} files, {total_symbols} symbols, {errors} errors")
        
        # Skip certain paths
        if relpath.startswith('localization/'):
            continue
        if relpath.startswith('gfx/'):
            continue
        if relpath.startswith('music/'):
            continue
        if relpath.endswith('.info'):
            continue
        
        # Get content
        content_row = conn.execute(
            "SELECT COALESCE(content_text, content_blob) as content FROM file_contents WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()
        
        if not content_row:
            continue
        
        content_bytes = content_row['content']
        if isinstance(content_bytes, bytes):
            content = content_bytes.decode('utf-8', errors='replace')
        else:
            content = content_bytes
        
        # Strip BOM (UTF-8 BOM and other BOMs that cause parse failures)
        if content.startswith('\ufeff'):
            content = content[1:]
        
        # Parse
        try:
            ast = parse_source(content, filename=relpath)
            ast_dict = ast.to_dict() if hasattr(ast, 'to_dict') else {}
        except Exception as e:
            errors += 1
            continue
        
        # Extract symbols
        try:
            symbols = list(extract_symbols_from_ast(ast_dict, relpath, content_hash))
            refs = list(extract_refs_from_ast(ast_dict, relpath, content_hash))
        except Exception as e:
            errors += 1
            continue
        
        # Store symbols
        if symbols:
            conn.execute("DELETE FROM symbols WHERE defining_file_id = ?", (file_id,))
            for sym in symbols:
                try:
                    conn.execute("""
                        INSERT INTO symbols (name, symbol_type, defining_file_id, content_version_id, line_number)
                        VALUES (?, ?, ?, ?, ?)
                    """, (sym.name, sym.kind, file_id, content_version_id, sym.line))
                    total_symbols += 1
                except Exception as e:
                    pass
        
        # Store refs
        if refs:
            conn.execute("DELETE FROM refs WHERE using_file_id = ?", (file_id,))
            for ref in refs:
                try:
                    conn.execute("""
                        INSERT INTO refs (name, ref_type, using_file_id, content_version_id, line_number, context)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (ref.name, ref.kind, file_id, content_version_id, ref.line, ref.context))
                    total_refs += 1
                except Exception as e:
                    pass
        
        if i % 100 == 0:
            conn.commit()
    
    conn.commit()
    
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Symbol Extraction Complete:")
    logger.info(f"  Files processed: {len(files)}")
    logger.info(f"  Symbols extracted: {total_symbols}")
    logger.info(f"  References extracted: {total_refs}")
    logger.info(f"  Errors: {errors}")
    logger.info("=" * 60)
    
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
