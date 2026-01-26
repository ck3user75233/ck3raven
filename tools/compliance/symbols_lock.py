"""
Symbols Lock - DEPRECATED

This module previously provided playset-scoped symbol snapshots.
The snapshot approach has been replaced with git-diff-based detection:
- Parse changed files from git diff
- Compare new symbol definitions directly against DB baseline
- No persistent snapshot files needed

The functions remain as pass-throughs for API compatibility until
all callers are updated.

Migration path: Use semantic_validator.py with git-diff file list instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SymbolIdentity:
    """Symbol identity tuple (deprecated)."""
    symbol_type: str
    scope: str
    name: str


def create_symbols_snapshot(
    contract_id: str,
    cvids: list[int] | None = None,
) -> dict:
    """
    DEPRECATED: Snapshots are no longer created.
    
    Use semantic_validator.py with git-diff file list instead.
    
    Returns:
        Empty dict indicating no-op
    """
    return {
        "deprecated": True,
        "message": "Snapshots replaced by git-diff approach. Use semantic_validator.py instead.",
        "contract_id": contract_id,
    }


def diff_snapshots(
    baseline_path: str,
    current_path: str,
) -> dict:
    """
    DEPRECATED: Use git diff + semantic_validator instead.
    
    Returns:
        Empty diff result
    """
    return {
        "deprecated": True,
        "message": "Snapshots replaced by git-diff approach. Use semantic_validator.py instead.",
        "new_identities": [],
        "removed_identities": [],
    }


def check_new_symbols(baseline_path: str) -> dict:
    """
    DEPRECATED: Use semantic_validator.py definitions_added instead.
    
    Returns:
        Empty result
    """
    return {
        "deprecated": True,
        "message": "Use semantic_validator.py definitions_added instead.",
        "new_symbols": [],
        "requires_nst": False,
    }


def check_symbol_identities_exist(
    contract_id: str,
    identities: list[str],
) -> dict:
    """
    DEPRECATED: Use golden_join.symbol_exists() instead.
    
    Returns:
        Pass-through result
    """
    return {
        "deprecated": True,
        "message": "Use ck3lens.db.golden_join.symbol_exists() instead.",
        "all_exist": True,
        "missing": [],
    }


def verify_playset_unchanged(baseline_path: str) -> dict:
    """
    DEPRECATED: Playset drift is detected via other mechanisms.
    
    Returns:
        Pass-through result
    """
    return {
        "deprecated": True,
        "message": "Playset drift detection handled elsewhere.",
        "unchanged": True,
    }


def main():
    """CLI entry point - deprecated."""
    import sys
    print("WARNING: symbols_lock.py is deprecated.")
    print("Use semantic_validator.py with git-diff file list instead.")
    print()
    print("Migration:")
    print("  1. Get changed files from git diff")
    print("  2. Run: python -m tools.compliance.semantic_validator <files> --json")
    print("  3. Check definitions_added for new symbols")
    sys.exit(0)


if __name__ == "__main__":
    main()
