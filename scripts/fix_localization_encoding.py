#!/usr/bin/env python3
"""Fix CK3 localization file encoding (must be UTF-8 with BOM)

Usage:
  python scripts/fix_localization_encoding.py path/to/mod --check
  python scripts/fix_localization_encoding.py path/to/mod --fix
"""
import argparse, sys
from pathlib import Path

def detect_encoding(p):
    data = p.read_bytes()
    if data.startswith(b'\xef\xbb\xbf'): return 'utf-8-sig', True, data
    if data.startswith(b'\xff\xfe') or data.startswith(b'\xfe\xff'): return 'utf-16', True, data
    try:
        data.decode('utf-8')
        return 'utf-8', False, data
    except UnicodeDecodeError:
        return 'cp1252', False, data

def convert_to_utf8_bom(p, enc, data):
    if enc == 'utf-8-sig': data = data[3:]
    elif enc == 'utf-16': data = data[2:]
    if enc in ('utf-8-sig', 'utf-8'): text = data.decode('utf-8')
    elif enc == 'utf-16': text = data.decode('utf-16')
    else: text = data.decode(enc, errors='replace')
    p.write_text(text, encoding='utf-8-sig')
    return True

def main():
    parser = argparse.ArgumentParser(description='Fix CK3 localization encoding')
    parser.add_argument('mod_path', type=Path, help='Path to mod folder')
    parser.add_argument('--check', action='store_true', help='Only report issues')
    parser.add_argument('--fix', action='store_true', help='Fix all issues')
    args = parser.parse_args()
    
    if not args.mod_path.exists():
        print(f"Error: Mod path does not exist: {args.mod_path}"); sys.exit(1)
    if not args.fix: args.check = True
    
    loc_path = args.mod_path / "localization"
    if not loc_path.exists():
        print("No localization folder found."); return
    
    print(f"Scanning: {loc_path}")
    results = []
    for yml in loc_path.rglob("*.yml"):
        enc, has_bom, data = detect_encoding(yml)
        results.append((yml, enc, has_bom, data))
    
    issues = []
    for path, enc, has_bom, data in results:
        if enc == 'utf-8-sig': continue
        rel = path.relative_to(args.mod_path)
        if enc == 'utf-8': issues.append((path, rel, "UTF-8 MISSING BOM", enc, data))
        elif enc == 'cp1252': issues.append((path, rel, "ANSI (cp1252)", enc, data))
        else: issues.append((path, rel, enc, enc, data))
    
    print(f"Scanned: {len(results)} files, Issues: {len(issues)}")
    if not issues:
        print("All files are correctly encoded (UTF-8 with BOM)."); return
    
    print("Files with encoding issues:")
    for _, rel, issue, _, _ in issues:
        print(f"  {issue:20s} {rel}")
    
    if args.fix:
        print("\nFixing issues...")
        fixed = 0
        for path, rel, _, enc, data in issues:
            if convert_to_utf8_bom(path, enc, data):
                print(f"  Fixed: {rel}"); fixed += 1
        print(f"\nFixed {fixed} files.")

if __name__ == "__main__":
    main()
