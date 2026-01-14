"""Fix ck3_folder in server.py to use cvids from session.mods[]."""
import pathlib

server_path = pathlib.Path('tools/ck3lens_mcp/server.py')
content = server_path.read_text(encoding='utf-8')

# Fix the ck3_folder implementation
old_impl = '''    from ck3lens.unified_tools import ck3_folder_impl
    
    db = _get_db()
    playset_id = _get_playset_id()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for visibility enforcement
    
    return ck3_folder_impl(
        command=command,
        path=path,
        justification=justification,
        content_version_id=content_version_id,
        folder_pattern=folder_pattern,
        text_search=text_search,
        symbol_search=symbol_search,
        mod_filter=mod_filter,
        file_type_filter=file_type_filter,
        db=db,
        playset_id=playset_id,
        trace=trace,
        world=world,
    )'''

new_impl = '''    from ck3lens.unified_tools import ck3_folder_impl
    
    db = _get_db()
    session = _get_session()
    trace = _get_trace()
    world = _get_world()  # WorldAdapter for visibility enforcement
    
    # CANONICAL: Get cvids from session.mods[] instead of using playset_id
    cvids = [m.cvid for m in session.mods if m.cvid is not None]
    
    return ck3_folder_impl(
        command=command,
        path=path,
        justification=justification,
        content_version_id=content_version_id,
        folder_pattern=folder_pattern,
        text_search=text_search,
        symbol_search=symbol_search,
        mod_filter=mod_filter,
        file_type_filter=file_type_filter,
        db=db,
        cvids=cvids,
        trace=trace,
        world=world,
    )'''

content = content.replace(old_impl, new_impl)
server_path.write_text(content, encoding='utf-8')
print('Fixed ck3_folder to use cvids from session.mods[]')
