"""Create queue tables in live database."""
from pathlib import Path
import sqlite3

DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    
    # Create work_queue table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS work_queue (
            work_id         INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id         INTEGER NOT NULL,
            content_version_id INTEGER NOT NULL,
            processing_mask INTEGER NOT NULL,
            file_type       TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            priority        INTEGER NOT NULL DEFAULT 100,
            queued_at       TEXT NOT NULL,
            started_at      TEXT,
            completed_at    TEXT,
            error_message   TEXT,
            error_code      TEXT,
            retry_count     INTEGER NOT NULL DEFAULT 0,
            worker_id       TEXT,
            lease_expires_at TEXT,
            UNIQUE(file_id),
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
            FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_work_queue_status ON work_queue(status, priority, queued_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_work_queue_cv ON work_queue(content_version_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_work_queue_lease ON work_queue(status, lease_expires_at)")
    
    # Create file_state table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_state (
            file_id         INTEGER PRIMARY KEY,
            content_version_id INTEGER NOT NULL,
            last_mtime      REAL NOT NULL,
            last_size       INTEGER NOT NULL,
            content_hash    TEXT,
            last_checked_at TEXT NOT NULL,
            last_processed_at TEXT,
            processing_mask INTEGER,
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
            FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id)
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_state_cv ON file_state(content_version_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_file_state_mtime ON file_state(last_mtime)")
    
    # Create processing_log table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS processing_log (
            log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id         INTEGER,
            file_id         INTEGER,
            event_type      TEXT NOT NULL,
            stage           TEXT,
            logged_at       TEXT NOT NULL,
            duration_ms     INTEGER,
            rows_affected   INTEGER,
            error_message   TEXT,
            worker_id       TEXT,
            FOREIGN KEY (work_id) REFERENCES work_queue(work_id) ON DELETE SET NULL,
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE SET NULL
        )
    """)
    
    conn.execute("CREATE INDEX IF NOT EXISTS idx_processing_log_work ON processing_log(work_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_processing_log_file ON processing_log(file_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_processing_log_time ON processing_log(logged_at)")
    
    conn.commit()
    print("Tables created successfully")
    
    # Verify
    for table in ['work_queue', 'file_state', 'processing_log']:
        count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        print(f'{table}: {count} rows')
    
    conn.close()

if __name__ == "__main__":
    main()
