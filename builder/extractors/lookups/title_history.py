"""
Title History Extractor - DEPRECATED

This file is deprecated. history/titles/ files are now routed to SCRIPT (AST)
without a lookup extractor because they contain too many effect blocks.

The files have 1,700+ effect blocks - too much scripting for simple lookup.
If title history lookup is needed in the future, it would require full
AST-based extraction similar to events, not lightweight tokenizing.

Kept for backwards compatibility - the function returns a no-op result.
"""

import sqlite3
from typing import Dict
import warnings


def extract_title_history(
    conn: sqlite3.Connection,
    content_version_id: int,
    progress_callback=None,
) -> Dict[str, int]:
    """
    DEPRECATED: Title history extraction is not implemented.
    
    history/titles/ files are now routed to SCRIPT (AST) without extraction.
    They contain too many effect blocks for simple lookup extraction.
    
    Returns:
        {'inserted': 0, 'skipped': 0, 'errors': 0, 'status': 'deprecated'}
    """
    warnings.warn(
        "extract_title_history is deprecated. history/titles/ is now SCRIPT route with no extractor.",
        DeprecationWarning,
        stacklevel=2
    )
    
    return {
        'inserted': 0,
        'skipped': 0,
        'errors': 0,
        'status': 'deprecated'
    }
