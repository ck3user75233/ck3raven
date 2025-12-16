"""
Conflict Analysis Tool

Generates detailed reports of content conflicts across mods.

ARCHITECTURE:
    This tool uses SQLResolver to query the database - NO direct file I/O.
    All content must first be ingested via `ck3raven ingest`.

Usage:
    python -m ck3raven.tools.conflicts --db <path> --playset <id>
    python -m ck3raven.tools.conflicts --db <path> --playset <id> --folder common/culture/traditions
    python -m ck3raven.tools.conflicts --db <path> --playset <id> --output conflicts.md
"""

import argparse
import json
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from ..db.schema import get_connection, DEFAULT_DB_PATH
from ..resolver import SQLResolver, ResolutionResult, MergePolicy


@dataclass
class ConflictReport:
    """Summary of conflicts for a folder or entire playset."""
    playset_id: int
    generated_at: str
    folder_results: Dict[str, ResolutionResult] = field(default_factory=dict)
    
    @property
    def total_file_overrides(self) -> int:
        return sum(r.file_override_count for r in self.folder_results.values())
    
    @property
    def total_symbol_conflicts(self) -> int:
        return sum(r.conflict_count for r in self.folder_results.values())
    
    @property
    def folders_with_conflicts(self) -> int:
        return sum(1 for r in self.folder_results.values() 
                   if r.file_override_count > 0 or r.conflict_count > 0)


def get_playset_folders(conn: sqlite3.Connection, playset_id: int) -> List[str]:
    """Get all unique folder paths in a playset."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT DISTINCT 
            CASE 
                WHEN instr(f.relpath, '/') > 0 
                THEN substr(f.relpath, 1, length(f.relpath) - length(
                    substr(f.relpath, 1 + length(f.relpath) - length(replace(f.relpath, '/', '')))
                ))
                ELSE f.relpath
            END as folder
        FROM files f
        LEFT JOIN playset_mods pm ON f.content_version_id = pm.content_version_id 
            AND pm.playset_id = ? AND pm.enabled = 1
        LEFT JOIN content_versions cv ON f.content_version_id = cv.content_version_id
        WHERE (
            (cv.kind = 'vanilla' AND cv.vanilla_version_id = (SELECT vanilla_version_id FROM playsets WHERE playset_id = ?))
            OR pm.playset_id = ?
        )
          AND f.file_type = 'script'
          AND f.deleted = 0
          AND f.relpath LIKE 'common/%'
    """, (playset_id, playset_id, playset_id)).fetchall()
    
    # Extract unique folder paths (strip filename, get directory)
    folders = set()
    for row in rows:
        folder = row['folder']
        if folder:
            # Normalize: take up to second-to-last slash
            parts = folder.rstrip('/').rsplit('/', 1)
            if len(parts) > 0:
                folders.add(parts[0].rstrip('/'))
    
    return sorted(folders)


def analyze_playset(
    conn: sqlite3.Connection, 
    playset_id: int, 
    folders: Optional[List[str]] = None
) -> ConflictReport:
    """
    Analyze all conflicts in a playset using SQL-based resolver.
    
    Args:
        conn: Database connection
        playset_id: Playset to analyze
        folders: Specific folders to check (all if None)
    
    Returns:
        ConflictReport with all resolution results
    """
    resolver = SQLResolver(conn)
    
    # Get folders to analyze
    if folders is None:
        folders = get_playset_folders(conn, playset_id)
    
    report = ConflictReport(
        playset_id=playset_id,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    for folder in folders:
        try:
            result = resolver.resolve_folder(playset_id, folder)
            # Only include if there are conflicts
            if result.file_override_count > 0 or result.conflict_count > 0:
                report.folder_results[folder] = result
        except Exception as e:
            # Skip folders with errors
            print(f"Warning: Failed to analyze {folder}: {e}", file=sys.stderr)
    
    return report


def generate_markdown_report(report: ConflictReport) -> str:
    """Generate a markdown conflict report."""
    lines = []
    lines.append(f"# CK3 Conflict Analysis - Playset {report.playset_id}")
    lines.append(f"Generated: {report.generated_at}")
    lines.append("")
    lines.append("## Summary")
    lines.append(f"- Folders with conflicts: {report.folders_with_conflicts}")
    lines.append(f"- Total file-level overrides: {report.total_file_overrides}")
    lines.append(f"- Total symbol conflicts: {report.total_symbol_conflicts}")
    lines.append("")
    
    if not report.folder_results:
        lines.append("*No conflicts detected.*")
        return "\n".join(lines)
    
    # Group by policy type
    override_folders = []
    container_merge_folders = []
    fios_folders = []
    
    for folder, result in sorted(report.folder_results.items()):
        if result.policy == MergePolicy.OVERRIDE:
            override_folders.append((folder, result))
        elif result.policy == MergePolicy.CONTAINER_MERGE:
            container_merge_folders.append((folder, result))
        elif result.policy == MergePolicy.FIOS:
            fios_folders.append((folder, result))
        else:
            override_folders.append((folder, result))
    
    # Report OVERRIDE conflicts
    if override_folders:
        lines.append("## 🔄 OVERRIDE Conflicts (Last In Only Served)")
        lines.append("")
        for folder, result in override_folders:
            lines.append(f"### {folder}")
            lines.append(f"- File overrides: {result.file_override_count}")
            lines.append(f"- Symbol conflicts: {result.conflict_count}")
            lines.append("")
            
            # Show file overrides
            if result.file_overrides:
                lines.append("**File-level overrides:**")
                for fo in result.file_overrides[:10]:  # Limit to 10
                    lines.append(f"- `{fo.relpath}` - load order {fo.loser_load_order} replaced by {fo.winner_load_order}")
                if len(result.file_overrides) > 10:
                    lines.append(f"- ... and {len(result.file_overrides) - 10} more")
                lines.append("")
            
            # Show symbol conflicts  
            if result.overridden:
                lines.append("**Symbol-level conflicts:**")
                for ov in result.overridden[:20]:  # Limit to 20
                    lines.append(f"- `{ov.name}` ({ov.symbol_type}) - overridden by symbol {ov.winner_symbol_id}")
                if len(result.overridden) > 20:
                    lines.append(f"- ... and {len(result.overridden) - 20} more")
                lines.append("")
    
    # Report CONTAINER_MERGE conflicts
    if container_merge_folders:
        lines.append("## 📦 CONTAINER_MERGE Conflicts (on_actions, events)")
        lines.append("")
        for folder, result in container_merge_folders:
            lines.append(f"### {folder}")
            lines.append(f"- Containers with conflicts: {result.conflict_count}")
            lines.append("")
    
    # Report FIOS conflicts  
    if fios_folders:
        lines.append("## 🥇 FIOS Conflicts (First In Only Served - GUI)")
        lines.append("")
        for folder, result in fios_folders:
            lines.append(f"### {folder}")
            lines.append(f"- Ignored definitions: {result.conflict_count}")
            lines.append("")
    
    return "\n".join(lines)


def generate_json_report(report: ConflictReport) -> str:
    """Generate a JSON conflict report."""
    output = {
        "playset_id": report.playset_id,
        "generated_at": report.generated_at,
        "summary": {
            "folders_with_conflicts": report.folders_with_conflicts,
            "total_file_overrides": report.total_file_overrides,
            "total_symbol_conflicts": report.total_symbol_conflicts,
        },
        "folders": {}
    }
    
    for folder, result in report.folder_results.items():
        output["folders"][folder] = {
            "policy": result.policy.name,
            "file_override_count": result.file_override_count,
            "symbol_conflict_count": result.conflict_count,
            "file_overrides": [
                {
                    "relpath": fo.relpath,
                    "loser_load_order": fo.loser_load_order,
                    "winner_load_order": fo.winner_load_order,
                }
                for fo in result.file_overrides
            ],
            "overridden_symbols": [
                {
                    "name": ov.name,
                    "symbol_type": ov.symbol_type,
                    "load_order": ov.load_order_index,
                    "winner_load_order": ov.winner_load_order,
                }
                for ov in result.overridden
            ],
        }
    
    return json.dumps(output, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze content conflicts using SQLResolver (database-based)"
    )
    parser.add_argument("--db", "-d", type=Path, default=DEFAULT_DB_PATH,
                       help="Database path (default: ~/.ck3raven/ck3raven.db)")
    parser.add_argument("--playset", "-p", type=int, required=True,
                       help="Playset ID to analyze")
    parser.add_argument("--folder", "-f", type=str, nargs="*",
                       help="Specific folders to analyze (all if omitted)")
    parser.add_argument("--output", "-o", type=Path,
                       help="Output file for report")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON instead of markdown")
    
    args = parser.parse_args()
    
    # Connect to database
    try:
        conn = get_connection(args.db)
    except Exception as e:
        print(f"Error: Failed to connect to database at {args.db}: {e}", file=sys.stderr)
        print("Hint: Run 'ck3raven ingest' first to populate the database.", file=sys.stderr)
        sys.exit(1)
    
    # Verify playset exists
    row = conn.execute(
        "SELECT name FROM playsets WHERE playset_id = ?", 
        (args.playset,)
    ).fetchone()
    if not row:
        print(f"Error: Playset {args.playset} not found in database.", file=sys.stderr)
        sys.exit(1)
    
    print(f"Analyzing playset {args.playset}: {row[0]}...", file=sys.stderr)
    
    # Analyze
    report = analyze_playset(conn, args.playset, args.folder)
    
    if not report.folder_results:
        print("No conflicts found.")
        sys.exit(0)
    
    # Generate output
    if args.json:
        result = generate_json_report(report)
    else:
        result = generate_markdown_report(report)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
        print(f"Report saved to {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()
