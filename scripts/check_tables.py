import sqlite3
conn = sqlite3.connect(r'C:\Users\Nathan\.ck3raven\ck3raven.db')
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    print(t[0])

# Check parsers schema
print("\n--- parsers schema ---")
print(conn.execute("SELECT sql FROM sqlite_master WHERE name='parsers'").fetchone()[0])

# Check asts schema
print("\n--- asts schema ---")
print(conn.execute("SELECT sql FROM sqlite_master WHERE name='asts'").fetchone()[0])
