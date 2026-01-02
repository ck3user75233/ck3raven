"""Remove _get_playset_id and _playset_id from server.py."""
import pathlib

server_path = pathlib.Path('tools/ck3lens_mcp/server.py')
content = server_path.read_text(encoding='utf-8')

# Remove the _get_playset_id function entirely
old_fn = '''def _get_playset_id() -> int:
    """Get active playset ID, auto-detecting if needed."""
    global _playset_id
    if _playset_id is None:
        db = _get_db()
        # Get the first active playset from the database
        playsets = db.conn.execute(
            "SELECT playset_id FROM playsets WHERE is_active = 1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if playsets:
            _playset_id = playsets[0]
        else:
            # Fallback: get any playset
            playsets = db.conn.execute(
                "SELECT playset_id FROM playsets ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            _playset_id = playsets[0] if playsets else 1
    return _playset_id'''

tombstone = '''# ARCHIVED 2025-01-02: _get_playset_id removed (used BANNED playset tables)
# Conflict analysis will use session.mods[] cvids directly instead.
# See: archive/conflict_analysis_jan2026/'''

content = content.replace(old_fn, tombstone)

# Also remove any remaining _playset_id global
content = content.replace('# EXPUNGED: _playset_id (use session.mods[] cvids instead)\n', '')
content = content.replace('_playset_id: Optional[int] = None\n', '')

server_path.write_text(content, encoding='utf-8')
print('Removed _get_playset_id from server.py')
