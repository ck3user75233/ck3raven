"""
CLI entry point for ck3raven.

Usage:
    ck3raven parse <file>              Parse a file and show AST summary
    ck3raven ingest <path>             Ingest vanilla or mod into database
    ck3raven playset <name>            Create/manage playsets
    ck3raven emulate <playset>         Emulate full game state from playset
    ck3raven export <playset>          Export resolved game state
    ck3raven conflicts <playset>       Show conflicts for a playset
    ck3raven query <playset> <key>     Query a specific definition
    
Tools:
    ck3raven format <file>             Format a PDX script file
    ck3raven lint <file>               Lint a file for issues
    ck3raven diff <file1> <file2>      Semantic diff two files
"""

import argparse
import sys
from pathlib import Path


def cmd_parse(args):
    """Parse a file and show AST summary."""
    from .parser import parse_file
    
    try:
        ast = parse_file(args.file)
        print(f"Parsed: {args.file}")
        print(f"Top-level entries: {len(ast.children)}")
        
        if args.verbose:
            for child in ast.children[:20]:
                name = getattr(child, 'name', None) or getattr(child, 'key', None)
                print(f"  - {name}")
            if len(ast.children) > 20:
                print(f"  ... and {len(ast.children) - 20} more")
                
    except Exception as e:
        print(f"Parse error: {e}", file=sys.stderr)
        return 1
    
    return 0


def cmd_format(args):
    """Format a PDX script file."""
    from .tools.format import PDXFormatter, FormatOptions
    
    formatter = PDXFormatter()
    
    try:
        result = formatter.format_file(Path(args.file))
        
        if args.inplace:
            with open(args.file, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f"Formatted: {args.file}")
        else:
            print(result)
            
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    
    return 0


def cmd_lint(args):
    """Lint a file for issues."""
    from .tools.lint import PDXLinter
    
    linter = PDXLinter()
    issues = linter.lint_file(Path(args.file))
    
    if issues:
        for issue in issues:
            print(issue)
        print(f"\n{len(issues)} issues found")
        return 1
    else:
        print("No issues found")
        return 0


def cmd_diff(args):
    """Semantic diff two files."""
    from .tools.diff import PDXDiffer
    
    differ = PDXDiffer()
    result = differ.diff_files(Path(args.file1), Path(args.file2), args.block)
    
    if result.identical:
        print("Files are semantically identical")
    else:
        print(result.summary())
        for diff in result.differences:
            print(diff)
    
    return 0 if result.identical else 1


def cmd_ingest(args):
    """Ingest vanilla or mod into database."""
    print(f"Ingest: {args.path}")
    print("(Not yet implemented - use db.ingest module directly)")
    return 0


def cmd_emulate(args):
    """Emulate full game state from playset."""
    print(f"Emulate playset: {args.playset}")
    print("(Not yet implemented - use emulator.builder module directly)")
    return 0


def cmd_conflicts(args):
    """Show conflicts for a playset."""
    print(f"Conflicts for: {args.playset}")
    print("(Not yet implemented)")
    return 0


def cmd_query(args):
    """Query a specific definition."""
    print(f"Query {args.key} in playset {args.playset}")
    print("(Not yet implemented)")
    return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="CK3 Game State Emulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    ck3raven parse common/traditions/00_traditions.txt
    ck3raven format mymod/common/events/my_event.txt --inplace
    ck3raven lint mymod/common/decisions/my_decision.txt
    ck3raven diff vanilla.txt modded.txt
"""
    )
    parser.add_argument('--version', action='version', version='ck3raven 0.1.0')
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # parse
    parse_p = subparsers.add_parser('parse', help='Parse a PDX file')
    parse_p.add_argument('file', help='File to parse')
    parse_p.add_argument('-v', '--verbose', action='store_true')
    parse_p.set_defaults(func=cmd_parse)
    
    # format
    format_p = subparsers.add_parser('format', help='Format a PDX file')
    format_p.add_argument('file', help='File to format')
    format_p.add_argument('-i', '--inplace', action='store_true', help='Modify in place')
    format_p.set_defaults(func=cmd_format)
    
    # lint
    lint_p = subparsers.add_parser('lint', help='Lint a PDX file')
    lint_p.add_argument('file', help='File to lint')
    lint_p.set_defaults(func=cmd_lint)
    
    # diff
    diff_p = subparsers.add_parser('diff', help='Diff two PDX files')
    diff_p.add_argument('file1', help='First file')
    diff_p.add_argument('file2', help='Second file')
    diff_p.add_argument('-b', '--block', help='Compare specific block')
    diff_p.set_defaults(func=cmd_diff)
    
    # ingest
    ingest_p = subparsers.add_parser('ingest', help='Ingest vanilla/mod to database')
    ingest_p.add_argument('path', help='Path to ingest')
    ingest_p.set_defaults(func=cmd_ingest)
    
    # emulate
    emulate_p = subparsers.add_parser('emulate', help='Emulate game state')
    emulate_p.add_argument('playset', help='Playset name or ID')
    emulate_p.set_defaults(func=cmd_emulate)
    
    # conflicts
    conflicts_p = subparsers.add_parser('conflicts', help='Show conflicts')
    conflicts_p.add_argument('playset', help='Playset name or ID')
    conflicts_p.set_defaults(func=cmd_conflicts)
    
    # query
    query_p = subparsers.add_parser('query', help='Query a definition')
    query_p.add_argument('playset', help='Playset name or ID')
    query_p.add_argument('key', help='Definition key')
    query_p.set_defaults(func=cmd_query)
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
