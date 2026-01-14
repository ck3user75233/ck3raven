"""
Database API - The ONLY interface for MCP tools to access the database.

ARCHITECTURAL RULE: Tools MUST use this module. Direct DBQueries access is BANNED.

This module provides:
1. Single point of database access control
2. Enable/disable mechanism for maintenance operations  
3. Graceful error returns (never raises when disabled)
4. WAL mode release for file deletion

Usage in MCP tools:
    from ck3lens.db_api import db
    
    result = db.search(query="brave", ...)
    if "error" in result:
        return result  # Gracefully handle disabled state
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, FrozenSet, Optional

if TYPE_CHECKING:
    from ck3lens.db_queries import DBQueries


class DatabaseAPI:
    """
    Singleton database access controller.
    
    All MCP tools access the database through this API.
    The server can disable access for maintenance (e.g., deleting DB files).
    """
    
    _instance: Optional["DatabaseAPI"] = None
    
    def __new__(cls) -> "DatabaseAPI":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._enabled = True
        self._db: Optional["DBQueries"] = None
        self._db_path: Optional[Path] = None
        self._session = None  # Will hold session reference for cvid resolution
    
    # =========================================================================
    # Control Methods (called by server.py only)
    # =========================================================================
    
    def configure(self, db_path: Path, session=None) -> None:
        """Configure the database path. Called during session initialization."""
        self._db_path = db_path
        self._session = session
    
    def disable(self) -> dict:
        """
        Close DB connection and block all operations until enable() called.
        
        This switches SQLite out of WAL mode to release memory-mapped file locks,
        allowing the database files to be deleted on Windows.
        """
        self._enabled = False
        if self._db is not None:
            try:
                # Switch out of WAL mode to release memory-mapped locks (Windows fix)
                self._db.conn.execute("PRAGMA journal_mode = DELETE")
                self._db.conn.commit()
                self._db.close()
            except Exception:
                pass  # Best effort
            self._db = None
        return {"success": True, "status": "disabled", "message": "Database disabled. Files can now be deleted."}
    
    def enable(self) -> dict:
        """Re-enable database access."""
        self._enabled = True
        return {"success": True, "status": "enabled", "message": "Database access re-enabled."}
    
    def is_available(self) -> bool:
        """Check if database access is currently enabled."""
        return self._enabled and self._db_path is not None
    
    def status(self) -> dict:
        """Get current database status."""
        return {
            "enabled": self._enabled,
            "connected": self._db is not None,
            "db_path": str(self._db_path) if self._db_path else None,
        }
    
    # =========================================================================
    # Internal Helpers
    # =========================================================================
    
    def _check_available(self) -> Optional[dict]:
        """Returns error dict if disabled, None if OK."""
        if not self._enabled:
            return {
                "error": "Database disabled for maintenance",
                "hint": "Call ck3_db(command='enable') to reconnect",
                "status": "disabled",
            }
        if self._db_path is None:
            return {
                "error": "Database not configured",
                "hint": "Session may not be initialized",
                "status": "unconfigured",
            }
        return None
    
    def _get_db(self) -> "DBQueries":
        """
        Get or create database connection.
        
        INTERNAL USE ONLY - tools should use the wrapper methods.
        Raises RuntimeError if disabled.
        """
        if not self._enabled:
            raise RuntimeError("Database is disabled for maintenance")
        if self._db_path is None:
            raise RuntimeError("Database path not configured")
        
        if self._db is None:
            from ck3lens.db_queries import DBQueries
            self._db = DBQueries(db_path=self._db_path)
        
        return self._db
    
    # =========================================================================
    # Database Operations (wrapped with graceful error handling)
    # =========================================================================
    
    def unified_search(self, **kwargs) -> dict:
        """Unified search across symbols, content, and files."""
        if err := self._check_available():
            return err
        try:
            return self._get_db()._unified_search_internal(**kwargs)
        except Exception as e:
            return {"error": f"Search failed: {e}"}
    
    def get_symbol_conflicts(self, **kwargs) -> dict:
        """Get symbol conflicts."""
        if err := self._check_available():
            return err
        try:
            return self._get_db()._get_symbol_conflicts_internal(**kwargs)
        except Exception as e:
            return {"error": f"Conflict detection failed: {e}"}
    
    def get_file(self, **kwargs) -> Optional[dict]:
        """Get file from database."""
        if err := self._check_available():
            return err
        try:
            return self._get_db().get_file(**kwargs)
        except Exception as e:
            return {"error": f"File retrieval failed: {e}"}
    
    def search_symbols(self, **kwargs) -> dict:
        """Search symbols."""
        if err := self._check_available():
            return err
        try:
            return self._get_db().search_symbols(**kwargs)
        except Exception as e:
            return {"error": f"Symbol search failed: {e}"}
    
    def get_cvids(self, mods: list, normalize_func=None) -> dict:
        """Get content version IDs for mods."""
        if err := self._check_available():
            return err
        try:
            return self._get_db().get_cvids(mods, normalize_func)
        except Exception as e:
            return {"error": f"CVID resolution failed: {e}"}
    
    # =========================================================================
    # Raw Connection Access (for tools that need direct SQL)
    # =========================================================================
    
    @property
    def conn(self) -> Optional[sqlite3.Connection]:
        """
        Get raw database connection.
        
        Returns None if disabled. Tools should check for None before use.
        """
        if not self._enabled or self._db_path is None:
            return None
        try:
            return self._get_db().conn
        except Exception:
            return None
    
    def execute(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Cursor]:
        """
        Execute SQL with graceful handling.
        
        Returns None if disabled or on error.
        """
        if err := self._check_available():
            return None
        try:
            return self._get_db().conn.execute(sql, params)
        except Exception:
            return None
    
    def execute_safe(self, sql: str, params: tuple = ()) -> dict:
        """
        Execute SQL and return result dict.
        
        Always returns a dict with either 'rows' or 'error'.
        """
        if err := self._check_available():
            return err
        try:
            cursor = self._get_db().conn.execute(sql, params)
            rows = cursor.fetchall()
            return {"success": True, "rows": rows, "rowcount": len(rows)}
        except Exception as e:
            return {"error": f"SQL execution failed: {e}"}


# Singleton instance - import this in tools
db = DatabaseAPI()
