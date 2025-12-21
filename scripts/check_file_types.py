import sqlite3
conn = sqlite3.connect(r'C:\Users\Nathan\.ck3raven\ck3raven_new.db')

# Get largest .txt/.yml files under 5MB without ASTs
large = conn.execute("""
    SELECT DISTINCT f.relpath, LENGTH(fc.content_text) as size, fc.content_hash
    FROM files f
    JOIN file_contents fc ON f.content_hash = fc.content_hash
    LEFT JOIN asts a ON f.content_hash = a.content_hash
    WHERE f.deleted = 0
    AND (f.relpath LIKE '%.txt' OR f.relpath LIKE '%.yml')
    AND fc.content_text IS NOT NULL
    AND a.ast_id IS NULL
    AND LENGTH(fc.content_text) < 5000000
    ORDER BY LENGTH(fc.content_text) DESC
    LIMIT 15
""").fetchall()

print('Largest .txt/.yml files (under 5MB) without ASTs:')
for relpath, size, hash in large:
    print(f'{size:>10,} bytes: {relpath[:80]}')
    
# Show a sample of content from the largest file
if large:
    largest_hash = large[0][2]
    largest_path = large[0][0]
    content = conn.execute("SELECT content_text FROM file_contents WHERE content_hash = ?", (largest_hash,)).fetchone()[0]
    print(f"\n--- First 2000 chars of {largest_path} ---")
    print(content[:2000])
    print(f"\n--- Last 500 chars ---")
    print(content[-500:])
