"""Archive playset functions in db_queries.py that use deleted tables."""
import pathlib

db_queries_path = pathlib.Path('tools/ck3lens_mcp/ck3lens/db_queries.py')
content = db_queries_path.read_text(encoding='utf-8')

# Find and replace the playset functions
old_funcs = '''    def list_playsets(self) -> list[dict]:
        """List all available playsets."""
        rows = self.conn.execute("""
            SELECT 
                p.playset_id,
                p.name,
                p.is_active,
                p.created_at,
                (SELECT COUNT(*) FROM playset_mods pm WHERE pm.playset_id = p.playset_id) as mod_count
            FROM playsets p
            ORDER BY p.is_active DESC, p.updated_at DESC
        """).fetchall()
        
        return [dict(row) for row in rows]
    
    def set_active_playset(self, playset_id: int) -> bool:
        """
        Switch the active playset.
        
        This is instant - just updates which playset is marked active.
        Does NOT modify any mod data.
        """
        # Verify playset exists
        exists = self.conn.execute(
            "SELECT 1 FROM playsets WHERE playset_id = ?", (playset_id,)
        ).fetchone()
        
        if not exists:
            return False
        
        # Deactivate all, activate this one
        self.conn.execute("UPDATE playsets SET is_active = 0")
        self.conn.execute(
            "UPDATE playsets SET is_active = 1, updated_at = datetime('now') WHERE playset_id = ?",
            (playset_id,)
        )
        self.conn.commit()
        
        return True'''

new_funcs = '''    # ARCHIVED 2025-01-02: list_playsets and set_active_playset removed.
    # These used BANNED playsets/playset_mods tables (now deleted).
    # Playsets are now file-based JSON. See playsets/*.json and server.py ck3_playset.'''

content = content.replace(old_funcs, new_funcs)

db_queries_path.write_text(content, encoding='utf-8')
print('Archived playset functions from db_queries.py')
