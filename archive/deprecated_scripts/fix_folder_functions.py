"""Fix folder functions to use session.mods[] cvids instead of playset_id."""
import pathlib

unified_path = pathlib.Path('tools/ck3lens_mcp/ck3lens/unified_tools.py')
content = unified_path.read_text(encoding='utf-8')

# Replace the function signature and implementation
old_impl = '''def ck3_folder_impl(
    command: FolderCommand = "list",
    # For list/contents
    path: str | None = None,
    justification: str | None = None,
    # For mod_folders
    content_version_id: int | None = None,
    # For contents
    folder_pattern: str | None = None,
    text_search: str | None = None,
    symbol_search: str | None = None,
    mod_filter: list[str] | None = None,
    file_type_filter: list[str] | None = None,
    # Dependencies
    db=None,
    playset_id: int | None = None,
    trace=None,
    world=None,  # WorldAdapter for visibility enforcement
) -> dict:
    """
    Unified folder operations tool.
    
    Commands:
    
    command=list        → List directory contents from filesystem (path required)
    command=contents    → Get folder contents from database (path required)
    command=top_level   → Get top-level folders in active playset
    command=mod_folders → Get folders in specific mod (content_version_id required)
    
    The world parameter provides WorldAdapter for visibility enforcement on
    filesystem operations (command=list).
    """
    
    if command == "list":
        if not path:
            return {"error": "path required for list command"}
        return _folder_list_raw(path, justification or "folder listing", trace, world)
    
    elif command == "contents":
        if not path:
            return {"error": "path required for contents command"}
        return _folder_contents(path, content_version_id, folder_pattern, text_search,
                                symbol_search, mod_filter, file_type_filter, db, playset_id, trace)
    
    elif command == "top_level":
        return _folder_top_level(db, playset_id, trace)
    
    elif command == "mod_folders":
        if not content_version_id:
            return {"error": "content_version_id required for mod_folders command"}
        return _folder_mod_folders(content_version_id, db, trace)
    
    return {"error": f"Unknown command: {command}"}'''

new_impl = '''def ck3_folder_impl(
    command: FolderCommand = "list",
    # For list/contents
    path: str | None = None,
    justification: str | None = None,
    # For mod_folders
    content_version_id: int | None = None,
    # For contents
    folder_pattern: str | None = None,
    text_search: str | None = None,
    symbol_search: str | None = None,
    mod_filter: list[str] | None = None,
    file_type_filter: list[str] | None = None,
    # Dependencies
    db=None,
    cvids: list[int] | None = None,  # CANONICAL: cvids from session.mods[]
    trace=None,
    world=None,  # WorldAdapter for visibility enforcement
) -> dict:
    """
    Unified folder operations tool.
    
    Commands:
    
    command=list        → List directory contents from filesystem (path required)
    command=contents    → Get folder contents from database (path required)
    command=top_level   → Get top-level folders in active playset
    command=mod_folders → Get folders in specific mod (content_version_id required)
    
    CANONICAL: Uses cvids (list of content_version_ids from session.mods[]) instead of playset_id.
    The caller should pass cvids=[m.cvid for m in session.mods if m.cvid].
    """
    
    if command == "list":
        if not path:
            return {"error": "path required for list command"}
        return _folder_list_raw(path, justification or "folder listing", trace, world)
    
    elif command == "contents":
        if not path:
            return {"error": "path required for contents command"}
        return _folder_contents(path, content_version_id, folder_pattern, text_search,
                                symbol_search, mod_filter, file_type_filter, db, cvids, trace)
    
    elif command == "top_level":
        return _folder_top_level(db, cvids, trace)
    
    elif command == "mod_folders":
        if not content_version_id:
            return {"error": "content_version_id required for mod_folders command"}
        return _folder_mod_folders(content_version_id, db, trace)
    
    return {"error": f"Unknown command: {command}"}'''

content = content.replace(old_impl, new_impl)

# Fix _folder_contents to use cvids instead of playset_id
old_contents = '''def _folder_contents(path, content_version_id, folder_pattern, text_search,
                     symbol_search, mod_filter, file_type_filter, db, playset_id, trace):
    """Get folder contents from database."""
    # Normalize path
    path = path.replace("\\\\", "/").strip("/")
    
    # Build query
    conditions = ["pm.playset_id = ?", "pm.enabled = 1", "f.deleted = 0"]
    params = [playset_id]
    
    if content_version_id:
        conditions.append("f.content_version_id = ?")
        params.append(content_version_id)
    
    if path:
        conditions.append("f.relpath LIKE ?")
        params.append(f"{path}/%")
    
    query = f"""
        SELECT DISTINCT
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0
                THEN SUBSTR(SUBSTR(f.relpath, LENGTH(?) + 2), 1, 
                            INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1)
                ELSE SUBSTR(f.relpath, LENGTH(?) + 2)
            END as item_name,
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0 THEN 1
                ELSE 0
            END as is_folder,
            COUNT(*) as file_count
        FROM files f
        JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
        WHERE {" AND ".join(conditions)}
        GROUP BY item_name, is_folder
        ORDER BY is_folder DESC, item_name
    """
    
    prefix_params = [path] * 5
    
    try:
        rows = db.conn.execute(query, prefix_params + params).fetchall()
        
        entries = []
        for row in rows:
            if row['item_name']:
                entries.append({
                    "name": row['item_name'],
                    "type": "folder" if row['is_folder'] else "file",
                    "file_count": row['file_count'],
                })
        
        if trace:
            trace.log("ck3lens.folder.contents", {"path": path}, {"entries": len(entries)})
        
        return {
            "path": path,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}'''

new_contents = '''def _folder_contents(path, content_version_id, folder_pattern, text_search,
                     symbol_search, mod_filter, file_type_filter, db, cvids, trace):
    """Get folder contents from database.
    
    CANONICAL: Uses cvids (list of content_version_ids) instead of playset_id.
    """
    # Normalize path
    path = path.replace("\\\\", "/").strip("/")
    
    if not cvids:
        return {"error": "No cvids provided - session.mods[] may be empty or not resolved"}
    
    # Build query using cvids directly (no playset_mods table!)
    placeholders = ",".join("?" * len(cvids))
    conditions = [f"f.content_version_id IN ({placeholders})", "f.deleted = 0"]
    params = list(cvids)
    
    if content_version_id:
        conditions.append("f.content_version_id = ?")
        params.append(content_version_id)
    
    if path:
        conditions.append("f.relpath LIKE ?")
        params.append(f"{path}/%")
    
    query = f"""
        SELECT DISTINCT
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0
                THEN SUBSTR(SUBSTR(f.relpath, LENGTH(?) + 2), 1, 
                            INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') - 1)
                ELSE SUBSTR(f.relpath, LENGTH(?) + 2)
            END as item_name,
            CASE 
                WHEN INSTR(SUBSTR(f.relpath, LENGTH(?) + 2), '/') > 0 THEN 1
                ELSE 0
            END as is_folder,
            COUNT(*) as file_count
        FROM files f
        WHERE {" AND ".join(conditions)}
        GROUP BY item_name, is_folder
        ORDER BY is_folder DESC, item_name
    """
    
    prefix_params = [path] * 5
    
    try:
        rows = db.conn.execute(query, prefix_params + params).fetchall()
        
        entries = []
        for row in rows:
            if row['item_name']:
                entries.append({
                    "name": row['item_name'],
                    "type": "folder" if row['is_folder'] else "file",
                    "file_count": row['file_count'],
                })
        
        if trace:
            trace.log("ck3lens.folder.contents", {"path": path, "cvids_count": len(cvids)}, {"entries": len(entries)})
        
        return {
            "path": path,
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        return {"error": str(e)}'''

content = content.replace(old_contents, new_contents)

# Fix _folder_top_level
old_top_level = '''def _folder_top_level(db, playset_id, trace):
    """Get top-level folders."""
    rows = db.conn.execute("""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        JOIN playset_mods pm ON f.content_version_id = pm.content_version_id
        WHERE pm.playset_id = ? AND pm.enabled = 1 AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, (playset_id,)).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} 
               for row in rows if row['folder']]
    
    if trace:
        trace.log("ck3lens.folder.top_level", {}, {"folders": len(folders)})
    
    return {"folders": folders}'''

new_top_level = '''def _folder_top_level(db, cvids, trace):
    """Get top-level folders.
    
    CANONICAL: Uses cvids (list of content_version_ids) instead of playset_id.
    """
    if not cvids:
        return {"error": "No cvids provided - session.mods[] may be empty or not resolved"}
    
    placeholders = ",".join("?" * len(cvids))
    
    rows = db.conn.execute(f"""
        SELECT 
            SUBSTR(f.relpath, 1, INSTR(f.relpath || '/', '/') - 1) as folder,
            COUNT(*) as file_count
        FROM files f
        WHERE f.content_version_id IN ({placeholders}) AND f.deleted = 0
        GROUP BY folder
        ORDER BY folder
    """, cvids).fetchall()
    
    folders = [{"name": row['folder'], "fileCount": row['file_count']} 
               for row in rows if row['folder']]
    
    if trace:
        trace.log("ck3lens.folder.top_level", {"cvids_count": len(cvids)}, {"folders": len(folders)})
    
    return {"folders": folders}'''

content = content.replace(old_top_level, new_top_level)

unified_path.write_text(content, encoding='utf-8')
print('Fixed folder functions to use cvids instead of playset_id')
