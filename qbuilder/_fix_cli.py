from pathlib import Path
content = Path('qbuilder/cli.py').read_text(encoding='utf-8')

# Add BuilderSession import
old_import = "from qbuilder.schema import"
new_import = "from ck3raven.db.schema import BuilderSession\nfrom qbuilder.schema import"
content = content.replace(old_import, new_import)

# Fix the reset command to use BuilderSession
old_reset = """    try:
        if args.fresh:
            print("Resetting ALL data for fresh build...")
            
            # Clear derived data
            for table in ['asts', 'symbols', 'refs', 'localization_entries', 
                          'trait_lookups', 'event_lookups', 'decision_lookups']:
                try:
                    conn.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    pass
            
            # Clear files
            conn.execute("DELETE FROM files")
            
            # Clear content_versions and mod_packages (keep vanilla_versions)
            conn.execute("DELETE FROM content_versions")
            conn.execute("DELETE FROM mod_packages")
            
            conn.commit()
            print("  Cleared all derived data")"""

new_reset = """    try:
        if args.fresh:
            print("Resetting ALL data for fresh build...")
            
            # Use BuilderSession to clear protected tables
            with BuilderSession(conn, "qbuilder_reset_fresh"):
                # Clear derived data
                for table in ['asts', 'symbols', 'refs', 'localization_entries', 
                              'trait_lookups', 'event_lookups', 'decision_lookups',
                              'character_lookup', 'province_lookup', 'dynasty_lookup',
                              'holy_site_lookup', 'name_lookup']:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except sqlite3.OperationalError:
                        pass
                
                # Clear files
                conn.execute("DELETE FROM files")
                
                # Clear content_versions and mod_packages
                conn.execute("DELETE FROM content_versions")
                conn.execute("DELETE FROM mod_packages")
                
                conn.commit()
            print("  Cleared all derived data")"""

content = content.replace(old_reset, new_reset)

Path('qbuilder/cli.py').write_text(content, encoding='utf-8')
print('Fixed cli.py reset command')
