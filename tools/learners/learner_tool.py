#!/usr/bin/env python3
"""
Learner CLI Tool

Exposes the learner infrastructure for comparing CK3 mod symbols.

Commands:
    compare  - Compare a single symbol between vanilla and a mod
    batch    - Batch compare all symbols of a type
    list     - List what symbol types a mod contains

Output:
    By default prints JSON to stdout.
    Use --export to write JSONL + summary files to tools/learners/output/
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# Add learners package to path
LEARNERS_DIR = Path(__file__).parent
if str(LEARNERS_DIR) not in sys.path:
    sys.path.insert(0, str(LEARNERS_DIR))

from db_adapter import LearnerDb
from batch_differ import diff_symbol_from_db, batch_diff_symbols, export_to_jsonl, export_summary


def compare_symbol(
    symbol_name: str,
    baseline: str = "vanilla",
    compare: str = None,
    symbol_type: str = None,
    export: bool = False,
) -> dict:
    """
    Compare a single symbol between two sources.
    
    Args:
        symbol_name: Name of the symbol (e.g., "murder", "brave", "heavy_infantry")
        baseline: Baseline source - "vanilla" or mod name (default: vanilla)
        compare: Compare source - mod name (required)
        symbol_type: Symbol type - auto-detected if not provided
        export: If True, write results to JSONL file
    
    Returns:
        Dict with changes or error
    """
    if not compare:
        return {"error": "Must specify 'compare' mod name"}
    
    try:
        with LearnerDb() as db:
            # Resolve baseline CVID
            if baseline.lower() == "vanilla":
                baseline_cvid = db.get_vanilla_cvid()
            else:
                baseline_cvid = db.get_mod_cvid(baseline)
                if not baseline_cvid:
                    return {"error": f"Baseline mod not found: {baseline}"}
            
            # Resolve compare CVID
            compare_cvid = db.get_mod_cvid(compare)
            if not compare_cvid:
                return {"error": f"Compare mod not found: {compare}"}
            
            # Auto-detect symbol type if not provided
            if not symbol_type:
                row = db.conn.execute("""
                    SELECT DISTINCT symbol_type FROM symbols WHERE name = ?
                """, (symbol_name,)).fetchone()
                if not row:
                    return {"error": f"Symbol not found: {symbol_name}"}
                symbol_type = row[0]
            
            # Get the diff
            result = diff_symbol_from_db(
                db=db,
                name=symbol_name,
                symbol_type=symbol_type,
                baseline_cvid=baseline_cvid,
                compare_cvid=compare_cvid,
            )
            
            if not result:
                return {
                    "symbol_name": symbol_name,
                    "symbol_type": symbol_type,
                    "baseline": baseline,
                    "compare": compare,
                    "error": "Symbol not found in one or both sources",
                }
            
            # Export if requested
            output_files = {}
            if export and result.changes:
                safe_compare = compare.replace(" ", "_").replace("/", "_")
                output_name = f"{symbol_name}_{safe_compare}"
                jsonl_path = export_to_jsonl([result], output_name)
                summary_path = export_summary([result], output_name)
                output_files = {
                    "jsonl": str(jsonl_path),
                    "summary": str(summary_path),
                }
            
            response = {
                "symbol_name": result.symbol_name,
                "symbol_type": result.symbol_type,
                "baseline": result.baseline_source,
                "compare": result.compare_source,
                "change_count": len(result.changes),
                "changes": [c.to_dict() for c in result.changes],
            }
            
            if output_files:
                response["output_files"] = output_files
            
            return response
            
    except Exception as e:
        return {"error": str(e)}


def batch_compare(
    symbol_type: str,
    compare: str,
    baseline: str = "vanilla",
    limit: int = 50,
    export: bool = False,
) -> dict:
    """
    Batch compare all symbols of a type between two sources.
    
    Args:
        symbol_type: Type of symbols to compare (maa_type, building, trait, etc.)
        compare: Compare source mod name
        baseline: Baseline source (default: vanilla)
        limit: Maximum symbols to process
        export: If True, write results to JSONL file
    
    Returns:
        Dict with summary and list of changed symbols
    """
    try:
        with LearnerDb() as db:
            # Resolve CVIDs
            if baseline.lower() == "vanilla":
                baseline_cvid = db.get_vanilla_cvid()
            else:
                baseline_cvid = db.get_mod_cvid(baseline)
                if not baseline_cvid:
                    return {"error": f"Baseline mod not found: {baseline}"}
            
            compare_cvid = db.get_mod_cvid(compare)
            if not compare_cvid:
                return {"error": f"Compare mod not found: {compare}"}
            
            # Run batch diff
            results = batch_diff_symbols(
                symbol_type=symbol_type,
                baseline_cvid=baseline_cvid,
                compare_cvid=compare_cvid,
                limit=limit,
            )
            
            # Export if requested
            output_files = {}
            if export and results:
                safe_compare = compare.replace(" ", "_").replace("/", "_")
                output_name = f"{symbol_type}_{safe_compare}"
                jsonl_path = export_to_jsonl(
                    results, 
                    output_name,
                    metadata={"baseline_cvid": baseline_cvid, "compare_cvid": compare_cvid}
                )
                summary_path = export_summary(results, output_name)
                output_files = {
                    "jsonl": str(jsonl_path),
                    "summary": str(summary_path),
                }
            
            response = {
                "symbol_type": symbol_type,
                "baseline": baseline,
                "compare": compare,
                "total_changed": len(results),
                "symbols": [
                    {
                        "name": r.symbol_name,
                        "change_count": len(r.changes),
                    }
                    for r in results
                ],
            }
            
            if output_files:
                response["output_files"] = output_files
            
            return response
            
    except Exception as e:
        return {"error": str(e)}


def list_mod_changes(
    mod_name: str,
    symbol_type: str = None,
    limit: int = 100,
) -> dict:
    """
    List what symbols a mod changes compared to vanilla.
    
    Args:
        mod_name: Name of the mod
        symbol_type: Optional filter by symbol type
        limit: Maximum results
    
    Returns:
        Dict with list of changed symbols
    """
    try:
        with LearnerDb() as db:
            mod_cvid = db.get_mod_cvid(mod_name)
            if not mod_cvid:
                return {"error": f"Mod not found: {mod_name}"}
            
            vanilla_cvid = db.get_vanilla_cvid()
            
            # Find common symbols
            if symbol_type:
                common = db.find_common_symbols(symbol_type, vanilla_cvid, mod_cvid, limit)
                
                # Check which ones are actually different
                changed = []
                for name in common:
                    result = diff_symbol_from_db(db, name, symbol_type, vanilla_cvid, mod_cvid)
                    if result and result.changes:
                        changed.append({
                            "name": name,
                            "type": symbol_type,
                            "change_count": len(result.changes),
                        })
                
                return {
                    "mod": mod_name,
                    "symbol_type": symbol_type,
                    "changed_count": len(changed),
                    "symbols": changed,
                }
            else:
                # Query all symbol types this mod has
                rows = db.conn.execute("""
                    SELECT s.symbol_type, COUNT(DISTINCT s.name) as count
                    FROM symbols s
                    JOIN asts a ON s.ast_id = a.ast_id
                    JOIN files f ON a.content_hash = f.content_hash
                    WHERE f.content_version_id = ?
                    GROUP BY s.symbol_type
                    ORDER BY count DESC
                """, (mod_cvid,)).fetchall()
                
                return {
                    "mod": mod_name,
                    "symbol_types": [
                        {"type": row[0], "count": row[1]}
                        for row in rows
                    ],
                }
                
    except Exception as e:
        return {"error": str(e)}


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    import json
    
    parser = argparse.ArgumentParser(
        description="CK3 Learner - Compare mod symbols against vanilla",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare murder scheme between vanilla and More Game Rules
  python learner_tool.py compare murder --mod "More Game Rules"
  
  # Batch compare all MAA types, export to files
  python learner_tool.py batch maa_type --mod KGD --export
  
  # List what symbol types a mod touches
  python learner_tool.py list "More Game Rules"
  
  # List which traits a mod changes
  python learner_tool.py list KGD --type trait

Output files are written to: tools/learners/output/
        """
    )
    subparsers = parser.add_subparsers(dest="command")
    
    # compare command
    compare_p = subparsers.add_parser("compare", help="Compare a single symbol")
    compare_p.add_argument("symbol", help="Symbol name (e.g., murder, brave, heavy_infantry)")
    compare_p.add_argument("--mod", "-m", required=True, help="Mod to compare against vanilla")
    compare_p.add_argument("--type", "-t", help="Symbol type (auto-detected if not provided)")
    compare_p.add_argument("--export", "-e", action="store_true", help="Export results to JSONL file")
    
    # batch command
    batch_p = subparsers.add_parser("batch", help="Batch compare all symbols of a type")
    batch_p.add_argument("type", help="Symbol type (maa_type, building, trait, scheme, etc.)")
    batch_p.add_argument("--mod", "-m", required=True, help="Mod to compare against vanilla")
    batch_p.add_argument("--limit", "-l", type=int, default=50, help="Max symbols to process (default: 50)")
    batch_p.add_argument("--export", "-e", action="store_true", help="Export results to JSONL + summary files")
    
    # list command
    list_p = subparsers.add_parser("list", help="List what a mod changes")
    list_p.add_argument("mod", help="Mod name (fuzzy match)")
    list_p.add_argument("--type", "-t", help="Filter by symbol type")
    list_p.add_argument("--limit", "-l", type=int, default=100, help="Max results (default: 100)")
    
    args = parser.parse_args()
    
    if args.command == "compare":
        result = compare_symbol(
            args.symbol, 
            compare=args.mod, 
            symbol_type=args.type,
            export=args.export,
        )
    elif args.command == "batch":
        result = batch_compare(
            args.type, 
            compare=args.mod, 
            limit=args.limit,
            export=args.export,
        )
    elif args.command == "list":
        result = list_mod_changes(args.mod, symbol_type=args.type, limit=args.limit)
    else:
        parser.print_help()
        sys.exit(1)
    
    print(json.dumps(result, indent=2))
