#!/usr/bin/env python3
"""
Batch Differ

Combines the database adapter with the AST differ to process
multiple symbols in batch and produce JSONL output.

This is Phase 2 of the Unified Learner architecture:
1. Query symbols from database using golden_join pattern
2. Apply AST differ to each symbol pair
3. Export flat change records to JSONL

Output is written to tools/learners/output/ - NOT to the database.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from db_adapter import LearnerDb, SymbolRecord
from ast_diff import diff_symbol_asts, DiffResult, ChangeRecord


# Output directory for learner results
OUTPUT_DIR = Path(__file__).parent / "output"


def ensure_output_dir():
    """Create output directory if it doesn't exist."""
    OUTPUT_DIR.mkdir(exist_ok=True)


def diff_symbol_from_db(
    db: LearnerDb,
    name: str,
    symbol_type: str,
    baseline_cvid: int,
    compare_cvid: int,
) -> Optional[DiffResult]:
    """
    Diff a single symbol between two content versions.
    
    Args:
        db: Database accessor
        name: Symbol name
        symbol_type: Symbol type (trait, maa_type, etc.)
        baseline_cvid: Baseline content version ID (usually vanilla)
        compare_cvid: Compare content version ID (mod)
    
    Returns:
        DiffResult with changes, or None if symbol not found in both
    """
    # Get symbols from database
    baseline = db.get_symbol_with_ast(name, symbol_type, baseline_cvid)
    compare = db.get_symbol_with_ast(name, symbol_type, compare_cvid)
    
    if not baseline or not compare:
        return None
    
    # Extract symbol blocks from file ASTs
    baseline_block = baseline.extract_symbol_block()
    compare_block = compare.extract_symbol_block()
    
    if not baseline_block or not compare_block:
        return None
    
    # Run the differ
    return diff_symbol_asts(
        baseline_ast=baseline_block,
        compare_ast=compare_block,
        symbol_name=name,
        baseline_source=baseline.source_name,
        compare_source=compare.source_name,
        symbol_type=symbol_type,
    )


def batch_diff_symbols(
    symbol_type: str,
    baseline_cvid: int,
    compare_cvid: int,
    limit: int = 100,
    db_path: Optional[Path] = None,
) -> list[DiffResult]:
    """
    Batch diff all common symbols of a given type.
    
    Args:
        symbol_type: Symbol type to diff
        baseline_cvid: Baseline content version ID
        compare_cvid: Compare content version ID
        limit: Maximum symbols to process
        db_path: Optional database path override
    
    Returns:
        List of DiffResults for symbols with changes
    """
    db_kwargs = {"db_path": db_path} if db_path else {}
    results = []
    
    with LearnerDb(**db_kwargs) as db:
        # Find common symbols
        common = db.find_common_symbols(symbol_type, baseline_cvid, compare_cvid, limit)
        print(f"Found {len(common)} common {symbol_type} symbols")
        
        # Diff each symbol
        for i, name in enumerate(common):
            result = diff_symbol_from_db(db, name, symbol_type, baseline_cvid, compare_cvid)
            
            if result and result.changes:  # Check if changes list is non-empty
                results.append(result)
                
            # Progress indicator
            if (i + 1) % 10 == 0:
                print(f"  Processed {i + 1}/{len(common)}...")
    
    return results


def export_to_jsonl(
    results: list[DiffResult],
    output_name: str,
    metadata: Optional[dict] = None,
) -> Path:
    """
    Export diff results to JSONL file.
    
    Each line is a flat change record with metadata.
    
    Args:
        results: List of DiffResults to export
        output_name: Base name for output file
        metadata: Optional metadata to include in each record
    
    Returns:
        Path to output file
    """
    ensure_output_dir()
    
    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{output_name}_{timestamp}.jsonl"
    
    # Flatten all changes into records
    with open(output_file, "w", encoding="utf-8") as f:
        for result in results:
            for change in result.changes:
                # Use to_dict() which handles enum serialization
                record = {
                    "symbol_name": result.symbol_name,
                    "symbol_type": result.symbol_type,
                    "baseline_source": result.baseline_source,
                    "compare_source": result.compare_source,
                    **change.to_dict(),
                    **(metadata or {}),
                }
                f.write(json.dumps(record) + "\n")
    
    return output_file


def export_summary(
    results: list[DiffResult],
    output_name: str,
) -> Path:
    """
    Export summary report of changes.
    
    Args:
        results: List of DiffResults
        output_name: Base name for output file
    
    Returns:
        Path to output file
    """
    ensure_output_dir()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{output_name}_summary_{timestamp}.txt"
    
    # Count by change type
    from collections import Counter
    change_counts = Counter()
    path_counts = Counter()
    
    total_changes = 0
    for result in results:
        for change in result.changes:
            change_counts[change.change_type.value] += 1  # Use .value for enum
            path_counts[change.json_path.split(".")[1] if "." in change.json_path else "root"] += 1
            total_changes += 1
    
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Diff Summary: {output_name}\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"Symbols with changes: {len(results)}\n")
        f.write(f"Total changes: {total_changes}\n\n")
        
        f.write("By change type:\n")
        for ctype, count in sorted(change_counts.items()):
            f.write(f"  {ctype}: {count}\n")
        
        f.write("\nTop modified paths:\n")
        for path, count in path_counts.most_common(10):
            f.write(f"  {path}: {count}\n")
        
        f.write("\n\nPer-symbol breakdown:\n")
        f.write("-" * 60 + "\n")
        
        for result in sorted(results, key=lambda r: len(r.changes), reverse=True):
            f.write(f"\n{result.symbol_name} ({len(result.changes)} changes):\n")
            for change in result.changes[:5]:  # Show first 5
                old = change.old_value
                new = change.new_value
                f.write(f"  [{change.change_type}] {change.json_path}\n")
                if old is not None:
                    f.write(f"    - {old}\n")
                if new is not None:
                    f.write(f"    + {new}\n")
            if len(result.changes) > 5:
                f.write(f"  ... and {len(result.changes) - 5} more\n")
    
    return output_file


# =============================================================================
# Demo / Main Entry Point
# =============================================================================

def demo():
    """Run a demo batch diff of MAA types between vanilla and KGD."""
    print("=" * 70)
    print("Batch Differ Demo: Vanilla vs KGD MAA Types")
    print("=" * 70)
    
    with LearnerDb() as db:
        kgd_cvid = db.get_mod_cvid("KGD")
        
        if not kgd_cvid:
            print("Error: Could not find KGD mod in database")
            return
        
        print(f"\nVanilla cvid: 1")
        print(f"KGD cvid: {kgd_cvid}")
        print()
    
    # Run batch diff
    print("Running batch diff...")
    results = batch_diff_symbols(
        symbol_type="maa_type",
        baseline_cvid=1,
        compare_cvid=kgd_cvid,
        limit=50,  # Process first 50 common symbols
    )
    
    print(f"\nSymbols with changes: {len(results)}")
    
    # Show sample
    if results:
        print("\nSample changes:")
        for result in results[:3]:
            print(f"\n  {result.symbol_name}:")
            for change in result.changes[:3]:
                print(f"    [{change.change_type.value}] {change.json_path}")
                if change.old_value:
                    print(f"      - {change.old_value}")
                if change.new_value:
                    print(f"      + {change.new_value}")
    
    # Export results
    if results:
        print("\nExporting results...")
        jsonl_path = export_to_jsonl(
            results,
            "maa_vanilla_vs_kgd",
            metadata={"baseline_cvid": 1, "compare_cvid": kgd_cvid},
        )
        print(f"  JSONL: {jsonl_path}")
        
        summary_path = export_summary(results, "maa_vanilla_vs_kgd")
        print(f"  Summary: {summary_path}")


if __name__ == "__main__":
    demo()
