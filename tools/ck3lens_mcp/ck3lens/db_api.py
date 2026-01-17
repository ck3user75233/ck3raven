"""
Database API - The ONLY interface for MCP tools to access the database.

ARCHITECTURAL RULE: 
- MCP tools MUST use this module for database access
- MCP tools are READ-ONLY clients
- All writes go through the QBuilder daemon via IPC

See docs/SINGLE_WRITER_ARCHITECTURE.md for the canonical design.

This module provides:
1. Read-only database access (mode=ro enforced at SQLite level)
2. Enable/disable mechanism for maintenance operations
3. Graceful error returns (never raises when disabled)
4. Daemon client integration for write operations

Usage in MCP tools:
    from ck3lens.db_api import db
    
    # READ operations - direct DB access
    result = db.search(query="brave", ...)
    if "error" in result:
        return result
    
    # WRITE operations - must go through daemon
    from ck3lens.daemon_client import daemon
    daemon.enqueue_files([path])
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
    
    CRITICAL: This opens the database in READ-ONLY mode.
    Any attempt to execute INSERT/UPDATE/DELETE will fail at the SQLite layer.
    Write operations must go through the daemon via IPC.
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
        self._read_only = True  # ALWAYS read-only for MCP
    
    # =========================================================================
    # Control Methods (called by server.py only)
    # =========================================================================
    
    def configure(self, db_path: Path, session=None) -> None:
        """
        Configure the database path. Called during session initialization.
        
        IMPORTANT: This also re-enables the database if it was disabled.
        A new session should always start with DB enabled.
        
        The connection is ALWAYS opened in read-only mode for MCP.
        """
        self._db_path = db_path
        self._session = session
        # Re-enable on new session (fixes persistence bug across MCP restarts)
        self._enabled = True
        # Force reconnect to pick up new path
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
    
    def disable(self) -> dict:
        """
        Close DB connection and block all operations until enable() called.
        
        For read-only MCP connections, we just close the connection.
        No need to switch WAL mode since we're not holding write locks.
        """
        self._enabled = False
        if self._db is not None:
            try:
                self._db.close()
            except Exception:
                pass
            self._db = None
        return {
            "success": True, 
            "status": "disabled", 
            "message": "Database disabled. Read-only connection closed.",
            "note": "Write operations always go through daemon IPC.",
        }
    
    def enable(self) -> dict:
        """Re-enable database access."""
        self._enabled = True
        return {
            "success": True, 
            "status": "enabled", 
            "message": "Database access re-enabled (read-only).",
        }
    
    def is_available(self) -> bool:
        """Check if database access is currently enabled."""
        return self._enabled and self._db_path is not None
    
    def status(self) -> dict:
        """Get current database status."""
        # Also check daemon status
        daemon_status = {"connected": False, "state": "unknown"}
        try:
            from ck3lens.daemon_client import daemon
            if daemon.is_available():
                health = daemon.health()
                daemon_status = {
                    "connected": True,
                    "state": health.state,
                    "pid": health.daemon_pid,
                    "queue_pending": health.queue_pending,
                }
        except Exception:
            pass
        
        return {
            "enabled": self._enabled,
            "connected": self._db is not None,
            "db_path": str(self._db_path) if self._db_path else None,
            "read_only": self._read_only,
            "daemon": daemon_status,
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
        Opens connection in READ-ONLY mode.
        Raises RuntimeError if disabled.
        """
        if not self._enabled:
            raise RuntimeError("Database is disabled for maintenance")
        if self._db_path is None:
            raise RuntimeError("Database path not configured")
        
        if self._db is None:
            from ck3lens.db_queries import DBQueries
            # Open in read-only mode
            self._db = DBQueries(db_path=self._db_path, read_only=True)
        
        return self._db
    
    # =========================================================================
    # Database Operations (READ-ONLY, wrapped with graceful error handling)
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
    # Raw Connection Access (READ-ONLY)
    # =========================================================================
    
    @property
    def conn(self) -> Optional[sqlite3.Connection]:
        """
        Get raw database connection (READ-ONLY).
        
        Returns None if disabled. Tools should check for None before use.
        
        WARNING: This connection is read-only. Any mutation will raise
        sqlite3.OperationalError: attempt to write a readonly database
        """
        if not self._enabled or self._db_path is None:
            return None
        try:
            return self._get_db().conn
        except Exception:
            return None
    
    def execute(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Cursor]:
        """
        Execute SQL with graceful handling (READ-ONLY).
        
        Returns None if disabled or on error.
        
        WARNING: Only SELECT queries are allowed. Mutations will fail.
        """
        if err := self._check_available():
            return None
        
        # Validate query is read-only
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("PRAGMA"):
            # Log warning but let SQLite enforce (belt and suspenders)
            import logging
            logging.warning(f"db_api.execute() received mutation query (will fail): {sql[:50]}")
        
        try:
            return self._get_db().conn.execute(sql, params)
        except Exception:
            return None
    
    def execute_safe(self, sql: str, params: tuple = ()) -> dict:
        """
        Execute SQL and return result dict (READ-ONLY).
        
        Always returns a dict with either 'rows' or 'error'.
        
        WARNING: Only SELECT queries are allowed. Mutations will fail.
        """
        if err := self._check_available():
            return err
        
        # Validate query is read-only
        sql_upper = sql.strip().upper()
        if not sql_upper.startswith("SELECT") and not sql_upper.startswith("PRAGMA"):
            return {
                "error": "Write operations not allowed from MCP",
                "hint": "Use daemon IPC for mutations. See docs/SINGLE_WRITER_ARCHITECTURE.md",
            }
        
        try:
            cursor = self._get_db().conn.execute(sql, params)
            rows = cursor.fetchall()
            return {"success": True, "rows": rows, "rowcount": len(rows)}
        except sqlite3.OperationalError as e:
            if "readonly" in str(e).lower():
                return {
                    "error": "Database is read-only (as designed)",
                    "hint": "Use daemon IPC for mutations",
                }
            return {"error": f"SQL execution failed: {e}"}
        except Exception as e:
            return {"error": f"SQL execution failed: {e}"}


# Singleton instance - import this in tools
db = DatabaseAPI()
