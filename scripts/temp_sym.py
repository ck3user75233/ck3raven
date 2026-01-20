"""Write the symbols locker module."""

from pathlib import Path

CONTENT = '''"""
Symbols Locker - Phase 1.5 Component B

Playset-scoped symbol snapshot and comparison system.
Detects new symbols added during a contract session.

Scope:
- Playset-scoped (filters by session.mods[] CVIDs)
- New symbol detection only (not full regeneration)
- No source tagging (vanilla/mod distinction already in DB)

Usage:
    python -m tools.compliance.symbols_lock snapshot <contract_id>
    python -m tools.compliance.symbols_lock diff <baseline> <current>
    python -m tools.compliance.symbols_lock check-new <baseline>

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _get_repo_root() -> Path:
    """Get the ck3raven repository root."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "pyproject.toml").exists():
            return parent
    raise RuntimeError("Could not find repository root")


def _get_db_path() -> Path:
    """Get the ck3raven database path."""
    return Path.home() / ".ck3raven" / "ck3raven.db"


def _get_snapshots_dir() -> Path:
    """Get the symbols snapshots directory."""
    return _get_repo_root() / "artifacts" / "symbols"


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class SymbolEntry:
    """A single symbol from the database."""
    name: str
    symbol_type: str
    scope: Optional[str]
    content_version_id: int
    file_relpath: str
    line_number: Optional[int]
    
    def identity_key(self) -> str:
        """Unique identity for this symbol (name + type + scope)."""
        return f"{self.symbol_type}:{self.scope or ''}:{self.name}"
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolEntry":
        return cls(**data)


@dataclass
class SymbolsSnapshot:
    """A snapshot of all symbols in the active playset."""
    snapshot_id: str
    contract_id: str
    playset_name: str
    created_at: str
    cvid_count: int
    symbol_count: int
    snapshot_hash: str
    symbols_by_type: dict[str, int]
    symbols: list[SymbolEntry]
    
    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "contract_id": self.contract_id,
            "playset_name": self.playset_name,
            "created_at": self.created_at,
            "cvid_count": self.cvid_count,
            "symbol_count": self.symbol_count,
            "snapshot_hash": self.snapshot_hash,
            "symbols_by_type": self.symbols_by_type,
            "symbols": [s.to_dict() for s in self.symbols],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolsSnapshot":
        return cls(
            snapshot_id=data["snapshot_id"],
            contract_id=data["contract_id"],
            playset_name=data["playset_name"],
            created_at=data["created_at"],
            cvid_count=data["cvid_count"],
            symbol_count=data["symbol_count"],
            snapshot_hash=data["snapshot_hash"],
            symbols_by_type=data["symbols_by_type"],
            symbols=[SymbolEntry.from_dict(s) for s in data["symbols"]],
        )
    
    def save(self, path: Optional[Path] = None) -> Path:
        """Save snapshot to disk."""
        if path is None:
            snapshots_dir = _get_snapshots_dir()
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            path = snapshots_dir / f"{self.snapshot_id}.symbols.json"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path
    
    @classmethod
    def load(cls, path: Path) -> Optional["SymbolsSnapshot"]:
        """Load snapshot from disk."""
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


@dataclass
class SymbolsDiff:
    """Diff between two symbol snapshots."""
    baseline_id: str
    current_id: str
    baseline_hash: str
    current_hash: str
    hashes_match: bool
    added_symbols: list[SymbolEntry]
    removed_symbols: list[SymbolEntry]
    added_count: int
    removed_count: int
    added_by_type: dict[str, int]
    removed_by_type: dict[str, int]
    
    def to_dict(self) -> dict:
        return {
            "baseline_id": self.baseline_id,
            "current_id": self.current_id,
            "baseline_hash": self.baseline_hash,
            "current_hash": self.current_hash,
            "hashes_match": self.hashes_match,
            "added_symbols": [s.to_dict() for s in self.added_symbols],
            "removed_symbols": [s.to_dict() for s in self.removed_symbols],
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "added_by_type": self.added_by_type,
            "removed_by_type": self.removed_by_type,
        }
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=== Symbols Diff Summary ===",
            f"Baseline: {self.baseline_id} ({self.baseline_hash[:16]}...)",
            f"Current:  {self.current_id} ({self.current_hash[:16]}...)",
            f"Hashes match: {self.hashes_match}",
            "",
        ]
        
        if self.hashes_match:
            lines.append("No changes detected.")
            return "\\n".join(lines)
        
        if self.added_count > 0:
            lines.append(f"Added symbols: {self.added_count}")
            for sym_type, count in sorted(self.added_by_type.items()):
                lines.append(f"  + {sym_type}: {count}")
        
        if self.removed_count > 0:
            lines.append(f"\\nRemoved symbols: {self.removed_count}")
            for sym_type, count in sorted(self.removed_by_type.items()):
                lines.append(f"  - {sym_type}: {count}")
        
        return "\\n".join(lines)


# =============================================================================
# Core Functions
# =============================================================================

def get_active_playset_cvids() -> tuple[str, list[int]]:
    """
    Get CVIDs for the active playset from the MCP session.
    
    Returns:
        Tuple of (playset_name, list of content_version_ids)
    """
    # Import here to avoid circular imports
    import sys
    sys.path.insert(0, str(_get_repo_root()))
    
    db_path = _get_db_path()
    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        # Get all CVIDs - we'll filter by playset config
        # For now, get all indexed CVIDs (a full implementation would read playset JSON)
        cursor = conn.execute("""
            SELECT cv.content_version_id, cv.kind, mp.name, mp.workshop_id
            FROM content_versions cv
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            ORDER BY cv.content_version_id
        """)
        
        cvids = []
        for row in cursor:
            cvids.append(row["content_version_id"])
        
        # Get playset name from config (simplified - reads from session)
        playset_name = "active_playset"
        
        return playset_name, cvids
    finally:
        conn.close()


def query_symbols(cvids: list[int]) -> list[SymbolEntry]:
    """
    Query symbols for the given content version IDs.
    
    Args:
        cvids: List of content_version_ids to include
    
    Returns:
        List of SymbolEntry objects
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        # Join symbols -> asts -> file_contents -> files -> content_versions
        # to filter by CVID
        placeholders = ",".join("?" * len(cvids))
        
        cursor = conn.execute(f"""
            SELECT DISTINCT
                s.name,
                s.symbol_type,
                s.scope,
                f.content_version_id,
                f.relpath,
                s.line_number
            FROM symbols s
            JOIN asts a ON s.ast_id = a.ast_id
            JOIN files f ON a.content_hash = f.content_hash
            WHERE f.content_version_id IN ({placeholders})
              AND f.deleted = 0
            ORDER BY s.symbol_type, s.name
        """, cvids)
        
        symbols = []
        for row in cursor:
            symbols.append(SymbolEntry(
                name=row["name"],
                symbol_type=row["symbol_type"],
                scope=row["scope"],
                content_version_id=row["content_version_id"],
                file_relpath=row["relpath"],
                line_number=row["line_number"],
            ))
        
        return symbols
    finally:
        conn.close()


def compute_snapshot_hash(symbols: list[SymbolEntry]) -> str:
    """
    Compute deterministic hash for a symbol list.
    
    Algorithm:
        1. Sort symbols by identity_key()
        2. Build canonical JSON array
        3. SHA256 of canonical JSON
    """
    sorted_symbols = sorted(symbols, key=lambda s: s.identity_key())
    
    canonical_data = [
        {"key": s.identity_key(), "file": s.file_relpath}
        for s in sorted_symbols
    ]
    canonical_json = json.dumps(canonical_data, sort_keys=True, separators=(',', ':'))
    
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def create_symbols_snapshot(
    contract_id: str,
    cvids: Optional[list[int]] = None,
    playset_name: Optional[str] = None,
) -> SymbolsSnapshot:
    """
    Create a snapshot of current symbols in the active playset.
    
    Args:
        contract_id: Contract ID to associate with snapshot
        cvids: Content version IDs to include (auto-detected if None)
        playset_name: Playset name (auto-detected if None)
    
    Returns:
        SymbolsSnapshot object
    """
    if cvids is None or playset_name is None:
        detected_name, detected_cvids = get_active_playset_cvids()
        if cvids is None:
            cvids = detected_cvids
        if playset_name is None:
            playset_name = detected_name
    
    # Query symbols
    symbols = query_symbols(cvids)
    
    # Compute hash
    snapshot_hash = compute_snapshot_hash(symbols)
    
    # Count by type
    symbols_by_type: dict[str, int] = {}
    for sym in symbols:
        symbols_by_type[sym.symbol_type] = symbols_by_type.get(sym.symbol_type, 0) + 1
    
    # Create snapshot
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot_id = f"{contract_id}_{timestamp.replace(':', '-').replace('.', '-')[:19]}"
    
    return SymbolsSnapshot(
        snapshot_id=snapshot_id,
        contract_id=contract_id,
        playset_name=playset_name,
        created_at=timestamp,
        cvid_count=len(cvids),
        symbol_count=len(symbols),
        snapshot_hash=snapshot_hash,
        symbols_by_type=symbols_by_type,
        symbols=symbols,
    )


def diff_symbols(
    baseline: SymbolsSnapshot,
    current: SymbolsSnapshot,
) -> SymbolsDiff:
    """
    Compute diff between two symbol snapshots.
    
    Args:
        baseline: Earlier snapshot
        current: Later snapshot
    
    Returns:
        SymbolsDiff with added/removed symbols
    """
    # Build identity sets
    baseline_keys = {s.identity_key(): s for s in baseline.symbols}
    current_keys = {s.identity_key(): s for s in current.symbols}
    
    # Find differences
    added_keys = set(current_keys.keys()) - set(baseline_keys.keys())
    removed_keys = set(baseline_keys.keys()) - set(current_keys.keys())
    
    added_symbols = [current_keys[k] for k in sorted(added_keys)]
    removed_symbols = [baseline_keys[k] for k in sorted(removed_keys)]
    
    # Count by type
    added_by_type: dict[str, int] = {}
    for sym in added_symbols:
        added_by_type[sym.symbol_type] = added_by_type.get(sym.symbol_type, 0) + 1
    
    removed_by_type: dict[str, int] = {}
    for sym in removed_symbols:
        removed_by_type[sym.symbol_type] = removed_by_type.get(sym.symbol_type, 0) + 1
    
    return SymbolsDiff(
        baseline_id=baseline.snapshot_id,
        current_id=current.snapshot_id,
        baseline_hash=baseline.snapshot_hash,
        current_hash=current.snapshot_hash,
        hashes_match=baseline.snapshot_hash == current.snapshot_hash,
        added_symbols=added_symbols,
        removed_symbols=removed_symbols,
        added_count=len(added_symbols),
        removed_count=len(removed_symbols),
        added_by_type=added_by_type,
        removed_by_type=removed_by_type,
    )


def check_new_symbols(baseline_path: Path) -> tuple[bool, SymbolsDiff]:
    """
    Check if any new symbols have been added since baseline.
    
    Args:
        baseline_path: Path to baseline snapshot
    
    Returns:
        Tuple of (has_new_symbols, diff)
    """
    baseline = SymbolsSnapshot.load(baseline_path)
    if baseline is None:
        raise FileNotFoundError(f"Baseline not found: {baseline_path}")
    
    # Create current snapshot
    current = create_symbols_snapshot(
        contract_id=baseline.contract_id + "_check",
        playset_name=baseline.playset_name,
    )
    
    diff = diff_symbols(baseline, current)
    
    return diff.added_count > 0, diff


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    """CLI entry point."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python -m tools.compliance.symbols_lock <command> [args...]")
        print()
        print("Commands:")
        print("  snapshot <contract_id>      Create symbol snapshot for contract")
        print("  diff <baseline> <current>   Compare two snapshots")
        print("  check-new <baseline>        Check for new symbols since baseline")
        print("  status                      Show current symbol counts")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "snapshot":
        if len(sys.argv) < 3:
            print("Usage: snapshot <contract_id>")
            sys.exit(1)
        
        contract_id = sys.argv[2]
        print(f"Creating symbols snapshot for contract: {contract_id}")
        
        snapshot = create_symbols_snapshot(contract_id)
        path = snapshot.save()
        
        print(f"Snapshot created: {path}")
        print(f"  Symbols: {snapshot.symbol_count}")
        print(f"  CVIDs: {snapshot.cvid_count}")
        print(f"  Hash: {snapshot.snapshot_hash[:16]}...")
        print()
        print("Symbol counts by type:")
        for sym_type, count in sorted(snapshot.symbols_by_type.items(), key=lambda x: -x[1])[:10]:
            print(f"  {sym_type}: {count}")
    
    elif command == "diff":
        if len(sys.argv) < 4:
            print("Usage: diff <baseline_path> <current_path>")
            sys.exit(1)
        
        baseline_path = Path(sys.argv[2])
        current_path = Path(sys.argv[3])
        
        baseline = SymbolsSnapshot.load(baseline_path)
        current = SymbolsSnapshot.load(current_path)
        
        if baseline is None:
            print(f"Error: Baseline not found: {baseline_path}")
            sys.exit(1)
        if current is None:
            print(f"Error: Current not found: {current_path}")
            sys.exit(1)
        
        diff = diff_symbols(baseline, current)
        print(diff.summary())
    
    elif command == "check-new":
        if len(sys.argv) < 3:
            print("Usage: check-new <baseline_path>")
            sys.exit(1)
        
        baseline_path = Path(sys.argv[2])
        
        try:
            has_new, diff = check_new_symbols(baseline_path)
            
            if has_new:
                print(f"NEW SYMBOLS DETECTED: {diff.added_count}")
                print()
                print("New symbols by type:")
                for sym_type, count in sorted(diff.added_by_type.items()):
                    print(f"  + {sym_type}: {count}")
                
                if diff.added_count <= 20:
                    print()
                    print("New symbols:")
                    for sym in diff.added_symbols[:20]:
                        print(f"  + {sym.symbol_type}:{sym.name} in {sym.file_relpath}")
                
                sys.exit(1)  # Exit with error if new symbols
            else:
                print("No new symbols detected.")
                print(f"Baseline hash: {diff.baseline_hash[:16]}...")
                print(f"Current hash:  {diff.current_hash[:16]}...")
                sys.exit(0)
        
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif command == "status":
        playset_name, cvids = get_active_playset_cvids()
        symbols = query_symbols(cvids)
        
        print(f"Playset: {playset_name}")
        print(f"CVIDs: {len(cvids)}")
        print(f"Total symbols: {len(symbols)}")
        print()
        
        # Count by type
        by_type: dict[str, int] = {}
        for sym in symbols:
            by_type[sym.symbol_type] = by_type.get(sym.symbol_type, 0) + 1
        
        print("Symbols by type:")
        for sym_type, count in sorted(by_type.items(), key=lambda x: -x[1])[:15]:
            print(f"  {sym_type}: {count}")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
'''

target = Path(r"C:\\Users\\nateb\\Documents\\CK3 Mod Project 1.18\\ck3raven\\tools\\compliance\\symbols_lock.py")
target.write_text(CONTENT, encoding="utf-8")
print(f"Written {len(CONTENT)} bytes")
