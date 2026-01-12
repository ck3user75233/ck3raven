"""Create localization tables in current database."""
import sqlite3
from pathlib import Path

db = Path.home() / '.ck3raven/ck3raven.db'
conn = sqlite3.connect(str(db))

# Create localization tables
conn.executescript('''
CREATE TABLE IF NOT EXISTS localization_entries (
    loc_id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,
    language TEXT NOT NULL,
    loc_key TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    raw_value TEXT NOT NULL,
    plain_text TEXT,
    line_number INTEGER,
    parser_version_id INTEGER,
    UNIQUE(content_hash, loc_key, parser_version_id),
    FOREIGN KEY (parser_version_id) REFERENCES parsers(parser_version_id)
);

CREATE INDEX IF NOT EXISTS idx_loc_key ON localization_entries(loc_key);
CREATE INDEX IF NOT EXISTS idx_loc_language ON localization_entries(language);
CREATE INDEX IF NOT EXISTS idx_loc_hash ON localization_entries(content_hash);

CREATE TABLE IF NOT EXISTS localization_refs (
    loc_ref_id INTEGER PRIMARY KEY AUTOINCREMENT,
    loc_id INTEGER NOT NULL,
    ref_type TEXT NOT NULL,
    ref_value TEXT NOT NULL,
    FOREIGN KEY (loc_id) REFERENCES localization_entries(loc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_locref_locid ON localization_refs(loc_id);
CREATE INDEX IF NOT EXISTS idx_locref_value ON localization_refs(ref_value);
''')

conn.commit()
print('Localization tables created successfully')

# Verify
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'local%'").fetchall()
for t in tables:
    print(f'  - {t[0]}')
