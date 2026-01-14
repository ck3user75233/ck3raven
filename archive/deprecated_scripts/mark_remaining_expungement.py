"""Mark remaining playset_id usages with EXPUNGEMENT comments."""
import pathlib

# Update server.py _get_playset_id function
server_path = pathlib.Path('tools/ck3lens_mcp/server.py')
c = server_path.read_text(encoding='utf-8')

old_fn = '''def _get_playset_id() -> int:
    \"\"\"Get active playset ID, auto-detecting if needed.\"\"\"
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

new_fn = '''def _get_playset_id() -> int:
    """DEPRECATED: Get active playset ID - BANNED ARCHITECTURE.
    
    EXPUNGEMENT NOTICE (2025-01-02):
    This function queries the EXPUNGED playsets table which no longer exists.
    It will fail at runtime. The conflict system needs to be migrated to
    use file-based playsets and session.mods[] cvids instead.
    
    TODO: Replace with session-based cvid lookup:
    - session = _get_session()
    - cvids = [m.cvid for m in session.mods if m.cvid]
    - Pass cvids directly to conflict functions instead of playset_id
    """
    global _playset_id
    if _playset_id is None:
        # EXPUNGED: This queries deleted playsets table
        raise NotImplementedError(
            "EXPUNGED: playset_id architecture removed 2025-01-02. "
            "Use session.mods[] cvids instead. See CANONICAL_ARCHITECTURE.md."
        )
    return _playset_id'''

c = c.replace(old_fn, new_fn)

# Also remove _playset_id global initialization
c = c.replace('_playset_id: Optional[int] = None', '# EXPUNGED: _playset_id (use session.mods[] cvids instead)')

server_path.write_text(c, encoding='utf-8')
print('server.py: marked _get_playset_id as EXPUNGED')

# Update workspace.py Session class
workspace_path = pathlib.Path('tools/ck3lens_mcp/ck3lens/workspace.py')
c = workspace_path.read_text(encoding='utf-8')

c = c.replace('    playset_id: Optional[int] = None',
              '    # EXPUNGED: playset_id - use playset_name and mods[] cvids instead\n    playset_id: Optional[int] = None  # TODO: Remove after conflict system migration')

workspace_path.write_text(c, encoding='utf-8')
print('workspace.py: marked playset_id as EXPUNGED')

print('Done marking remaining playset_id usages')
