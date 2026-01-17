# Proposed Fix for MCP DB Lock Bug

> **Status:** ✅ IMPLEMENTED (see [SINGLE_WRITER_ARCHITECTURE.md](SINGLE_WRITER_ARCHITECTURE.md))  
> **Date:** January 10, 2026 (Proposed) → January 17, 2026 (Implemented)  
> **Author:** Agent (ck3raven-dev mode)  
> **Problem:** When the daemon holds a database lock, MCP tools hang indefinitely instead of failing gracefully

---

## ✅ Resolution

**This proposal was implemented on January 17, 2026 using "Option C: Reader/Writer Split".**

The implemented solution:
- **QBuilder daemon** is the ONLY process that writes to SQLite
- **MCP servers** connect with `mode=ro` (read-only at SQLite level)
- Mutations are requested via **IPC** (NDJSON over TCP, port 19876)
- **Writer lock** (`{db_path}.writer.lock`) prevents duplicate daemons

### Implementation Files

| Component | Path |
|-----------|------|
| Architecture spec | `docs/SINGLE_WRITER_ARCHITECTURE.md` |
| Daemon IPC server | `qbuilder/ipc_server.py` |
| IPC client for MCP | `tools/ck3lens_mcp/ck3lens/daemon_client.py` |
| Writer lock | `qbuilder/writer_lock.py` |
| Read-only DB API | `tools/ck3lens_mcp/ck3lens/db_api.py` |

---

## Original Problem Statement (Historical)

When the build daemon (builder/daemon.py) is running, it holds a long-running SQLite connection with WAL mode enabled. If the daemon is executing an expensive query or has uncommitted transactions, MCP tools that attempt to access the database will:

1. **Hang indefinitely** - waiting for the lock to be released
2. **Block Copilot** - the entire MCP server becomes unresponsive
3. **No timeout** - the user has no indication of what's wrong
4. **No recovery** - only killing the daemon or restarting VS Code helps

This was observed on January 10, 2026 when `ck3_file_search`, `ck3_exec`, and other MCP tools hung after the daemon crashed mid-query.

---

## Root Cause Analysis

### Current Connection Handling

**MCP Server (server.py lines 108-127):**
```python
def _get_db() -> DBQueries:
    global _db, _session_cv_ids_resolved
    if _db is None:
        session = _get_session()
        # ... health check ...
        _db = DBQueries(db_path=session.db_path)  # ← Connection created here
        # ...
    return _db
```

**DBQueries (db_queries.py lines 148-150):**
```python
def __init__(self, db_path: Path):
    self.db_path = db_path
    self.conn = get_connection(db_path)  # ← Uses get_connection
    self.conn.row_factory = sqlite3.Row
```

**get_connection (schema.py lines 1020-1029):**
```python
conn = sqlite3.connect(str(db_path), check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA foreign_keys = ON")
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA synchronous = NORMAL")
# ← NO TIMEOUT SET!
```

### The Problem

1. **No `timeout` parameter** - `sqlite3.connect()` defaults to 5 seconds, but individual queries have no timeout
2. **No `busy_timeout` PRAGMA** - SQLite will wait forever for locks
3. **Single shared connection** - all MCP tools share one connection that can block
4. **No lock detection** - MCP doesn't check if daemon holds the lock

### Daemon Connection (for comparison)

The daemon DOES configure timeouts properly (daemon.py lines 135-141):
```python
conn = sqlite3.connect(
    str(self.db_path),
    timeout=30.0,  # Wait up to 30s for locks
    isolation_level=None  # Autocommit mode
)
conn.execute("PRAGMA busy_timeout=30000")  # 30s busy timeout
```

But MCP uses `get_connection()` which lacks these safeguards.

---

## Proposed Solutions

### Solution 1: Add Timeouts to MCP Connection (Quick Fix)

**Minimal change to `get_connection()` in schema.py:**

```python
def get_connection(db_path: Optional[Path] = None, timeout: float = 5.0) -> sqlite3.Connection:
    """
    Get a thread-local database connection.
    
    Args:
        db_path: Path to database
        timeout: Lock wait timeout in seconds (default 5.0)
    """
    # ... existing code ...
    
    if key not in _local.connections:
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(f"PRAGMA busy_timeout = {int(timeout * 1000)}")  # ← ADD THIS
        _local.connections[key] = conn
    
    return _local.connections[key]
```

**Pros:** Simple, one-line fix  
**Cons:** All MCP tools share same timeout; doesn't distinguish read vs write

---

### Solution 2: Separate Read/Write Connections (Better)

Create two connections with different characteristics:

```python
# In db_queries.py or a new db_connections.py

class ConnectionPool:
    """Manages separate read and write connections."""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._read_conn: Optional[sqlite3.Connection] = None
        self._write_conn: Optional[sqlite3.Connection] = None
    
    @property
    def read(self) -> sqlite3.Connection:
        """Get read-only connection with short timeout."""
        if self._read_conn is None:
            self._read_conn = sqlite3.connect(
                str(self.db_path),
                timeout=2.0,       # Short timeout for reads
                check_same_thread=False
            )
            self._read_conn.execute("PRAGMA journal_mode = WAL")
            self._read_conn.execute("PRAGMA busy_timeout = 2000")
            self._read_conn.execute("PRAGMA query_only = ON")  # Read-only mode
            self._read_conn.row_factory = sqlite3.Row
        return self._read_conn
    
    @property
    def write(self) -> sqlite3.Connection:
        """Get write connection with longer timeout."""
        if self._write_conn is None:
            self._write_conn = sqlite3.connect(
                str(self.db_path),
                timeout=10.0,      # Longer timeout for writes
                check_same_thread=False
            )
            self._write_conn.execute("PRAGMA journal_mode = WAL")
            self._write_conn.execute("PRAGMA busy_timeout = 10000")
            self._write_conn.row_factory = sqlite3.Row
        return self._write_conn
    
    def close(self):
        """Close all connections."""
        if self._read_conn:
            self._read_conn.close()
            self._read_conn = None
        if self._write_conn:
            self._write_conn.close()
            self._write_conn = None
```

**Usage in MCP tools:**
```python
# For read operations (search, get file, etc.)
pool = get_connection_pool()
cursor = pool.read.execute("SELECT ...")

# For write operations (rare in MCP)
pool.write.execute("INSERT ...")
pool.write.commit()
```

**Pros:** Read operations won't be blocked by write locks; appropriate timeouts per use case  
**Cons:** More complex; needs refactoring of DBQueries

---

### Solution 3: Lock Detection with Graceful Fallback (Best)

Before any database operation, check if the daemon is running and holding a lock:

```python
# In db_queries.py or server.py

def check_db_lock_status(db_path: Path) -> dict:
    """
    Check if database is locked by daemon.
    
    Returns:
        {
            "locked": bool,
            "lock_holder": str or None,  # PID or process name
            "lock_age_seconds": float or None,
            "can_read": bool,  # WAL mode allows concurrent reads
        }
    """
    try:
        # Quick probe with very short timeout
        probe = sqlite3.connect(str(db_path), timeout=0.1)
        probe.execute("SELECT 1")  # Simple query to test lock
        probe.close()
        return {"locked": False, "can_read": True}
    except sqlite3.OperationalError as e:
        if "locked" in str(e).lower():
            # Check build_lock table for holder info
            try:
                read_conn = sqlite3.connect(str(db_path), timeout=0.5)
                read_conn.execute("PRAGMA journal_mode = WAL")  # WAL allows reads
                row = read_conn.execute(
                    "SELECT build_id, pid, heartbeat_at FROM build_lock WHERE lock_id = 1"
                ).fetchone()
                read_conn.close()
                
                if row:
                    heartbeat = datetime.fromisoformat(row[2])
                    age = (datetime.now() - heartbeat).total_seconds()
                    return {
                        "locked": True,
                        "lock_holder": f"daemon pid={row[1]}",
                        "lock_age_seconds": age,
                        "can_read": True,  # WAL allows reads
                    }
            except Exception:
                pass
            
            return {"locked": True, "can_read": False}
        raise


def with_lock_check(func):
    """Decorator that checks lock status before DB operations."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        session = _get_session()
        lock_status = check_db_lock_status(session.db_path)
        
        if lock_status["locked"] and not lock_status["can_read"]:
            return {
                "error": "Database locked by build daemon",
                "details": lock_status,
                "suggestion": "Wait for build to complete or run: python builder/daemon.py stop"
            }
        
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                return {
                    "error": "Database operation timed out",
                    "details": str(e),
                    "suggestion": "Database may be locked by daemon"
                }
            raise
    
    return wrapper
```

**Apply to MCP tools:**
```python
@mcp.tool()
@with_lock_check
def ck3_search(query: str, ...) -> dict:
    ...
```

**Pros:** Clear error messages; user knows what's happening; WAL reads still work  
**Cons:** Decorator overhead; still need underlying timeout fix

---

### Solution 4: Async Connection with Cancellation (Advanced)

For a truly robust solution, use async database access with timeout support:

```python
import asyncio
import aiosqlite

async def execute_with_timeout(db_path: Path, sql: str, params=(), timeout: float = 5.0):
    """Execute SQL with asyncio timeout."""
    try:
        async with asyncio.timeout(timeout):
            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute(sql, params)
                return await cursor.fetchall()
    except asyncio.TimeoutError:
        raise TimeoutError(f"Database query timed out after {timeout}s")
```

**Pros:** Truly cancellable operations; plays well with FastMCP async  
**Cons:** Major refactor; aiosqlite dependency; needs testing

---

## Recommended Implementation

### Phase 1: Quick Fix (Immediate)

Apply Solution 1 - add `busy_timeout` to `get_connection()`:

```python
# schema.py line 1029, after WAL pragma
conn.execute("PRAGMA busy_timeout = 5000")  # 5 second timeout
```

This prevents infinite hangs. Queries will fail with "database is locked" after 5 seconds.

### Phase 2: Better Errors (Short Term)

Apply Solution 3's lock detection:

1. Add `check_db_lock_status()` function to `db_queries.py`
2. Call it in `_get_db()` when connection fails
3. Return user-friendly error with daemon status

### Phase 3: Connection Pool (Medium Term)

Apply Solution 2 - separate read/write connections:

1. Create `ConnectionPool` class
2. Refactor `DBQueries` to use pool
3. Read-only operations use read connection with short timeout
4. Write operations use write connection with longer timeout

### Phase 4: Consider Async (Long Term)

If the MCP server moves to fully async, consider Solution 4.

---

## Testing Plan

### Test 1: Lock Detection
```bash
# Terminal 1: Start daemon with artificial delay
python builder/daemon.py start --test

# Terminal 2: Run MCP tool
# Should get clear error about daemon lock, not hang
```

### Test 2: Timeout Recovery
```bash
# Simulate locked database
sqlite3 ~/.ck3raven/ck3raven.db "BEGIN EXCLUSIVE; SELECT SLEEP(60);"

# In VS Code, run ck3_search
# Should timeout after 5s with clear error
```

### Test 3: WAL Read During Write
```bash
# Daemon running with write lock
# MCP read-only queries should still work (WAL allows this)
```

---

## Files to Modify

| File | Change |
|------|--------|
| `src/ck3raven/db/schema.py` | Add `busy_timeout` PRAGMA to `get_connection()` |
| `tools/ck3lens_mcp/ck3lens/db_queries.py` | Add `check_db_lock_status()`, optional `ConnectionPool` |
| `tools/ck3lens_mcp/server.py` | Add lock check to `_get_db()`, better error handling |

---

## Related Documents

- [Proposed Queue-Based Build Daemon.md](Proposed%20Queue-Based%20Build%20Daemon.md) - Daemon architecture redesign
- [CANONICAL_ARCHITECTURE.md](CANONICAL_ARCHITECTURE.md) - System architecture
