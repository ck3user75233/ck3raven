"""
Symbols Locker - Phase 1.5 Component B (B0-corrected)

Playset-scoped symbol snapshot and comparison system.
Detects new symbol IDENTITIES added during a contract session.

B0 Corrections Applied:
- B0.1: Playset identity metadata (playset_cvids, playset_mods, playset_hash)
- B0.2: No DISTINCT, deterministic ORDER BY
- B0.3: Symbol identity = (symbol_type, scope, name) for NST
- B0.4: check_symbol_identities_exist() API
- B0.5: Proof bundle tests

Scope:
- Playset-scoped (filters by session.mods[] CVIDs)
- New symbol IDENTITY detection (not source tracking)
- Playset drift detection on contract close

Usage:
    python -m tools.compliance.symbols_lock snapshot <contract_id>
    python -m tools.compliance.symbols_lock diff <baseline> <current>
    python -m tools.compliance.symbols_lock check-new <baseline>
    python -m tools.compliance.symbols_lock check-exists <contract_id> <type:scope:name> ...
    python -m tools.compliance.symbols_lock verify-playset <baseline>

Authority: docs/PHASE_1_5_AGENT_INSTRUCTION.md
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, asdict, field
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


def _resolve_snapshot_path(path_or_prefix: str) -> Path:
    """
    Resolve a snapshot path from either:
    - Full path (returned as-is)
    - Contract_id prefix (searches artifacts/symbols/)
    """
    path = Path(path_or_prefix)
    
    # If it's a full path that exists, use it
    if path.exists() and path.suffix == ".json":
        return path
    
    # Try as prefix in snapshots directory
    snapshots_dir = _get_snapshots_dir()
    if snapshots_dir.exists():
        matches = list(snapshots_dir.glob(f"{path_or_prefix}*.symbols.json"))
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            # Return the most recent one
            matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return matches[0]
    
    # Return as-is and let caller handle not found
    return path


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class SymbolIdentity:
    """
    Canonical symbol identity for NST (New Symbol Tracking).
    
    Identity = (symbol_type, scope, name)
    
    This is what matters for "is this symbol new?" checks.
    Different mods can define the same identity - that's an override, not a new symbol.
    """
    symbol_type: str
    scope: Optional[str]
    name: str
    
    def key(self) -> str:
        """Canonical string key for this identity."""
        return f"{self.symbol_type}:{self.scope or ''}:{self.name}"
    
    def to_dict(self) -> dict:
        return {"symbol_type": self.symbol_type, "scope": self.scope, "name": self.name}
    
    @classmethod
    def from_key(cls, key: str) -> "SymbolIdentity":
        """Parse from key string."""
        parts = key.split(":", 2)
        return cls(
            symbol_type=parts[0],
            scope=parts[1] if parts[1] else None,
            name=parts[2],
        )
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolIdentity":
        return cls(**data)


@dataclass
class SymbolProvenance:
    """
    Full provenance for a symbol (for reporting, not identity).
    
    This records WHERE a symbol is defined, not WHAT it is.
    Multiple provenance records can exist for the same identity (overrides).
    """
    symbol_id: int
    symbol_type: str
    scope: Optional[str]
    name: str
    content_version_id: int
    file_relpath: str
    line_number: Optional[int]
    
    def identity(self) -> SymbolIdentity:
        """Extract identity from this provenance."""
        return SymbolIdentity(
            symbol_type=self.symbol_type,
            scope=self.scope,
            name=self.name,
        )
    
    def identity_key(self) -> str:
        """Get identity key."""
        return self.identity().key()
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolProvenance":
        return cls(**data)


@dataclass
class ModIdentity:
    """
    Identity of a mod in the playset.
    
    Used for playset drift detection.
    """
    cvid: int
    mod_package_id: Optional[int]
    name: Optional[str]
    workshop_id: Optional[str]
    source_root: str  # ROOT_GAME, ROOT_STEAM, ROOT_USER_DOCS, etc.
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ModIdentity":
        return cls(**data)


@dataclass
class PlaysetIdentity:
    """
    Full playset identity for drift detection.
    
    B0.1 requirement: snapshot must include playset identity to detect
    if playset changed between contract open and close.
    """
    playset_name: str
    cvids: list[int]  # Sorted list of CVIDs
    mods: list[ModIdentity]  # Full mod identity
    playset_hash: str  # sha256 of canonical representation
    
    def to_dict(self) -> dict:
        return {
            "playset_name": self.playset_name,
            "cvids": self.cvids,
            "mods": [m.to_dict() for m in self.mods],
            "playset_hash": self.playset_hash,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PlaysetIdentity":
        return cls(
            playset_name=data["playset_name"],
            cvids=data["cvids"],
            mods=[ModIdentity.from_dict(m) for m in data["mods"]],
            playset_hash=data["playset_hash"],
        )
    
    @classmethod
    def compute_hash(cls, cvids: list[int], mods: list[ModIdentity]) -> str:
        """Compute deterministic hash of playset identity."""
        canonical = {
            "cvids": sorted(cvids),
            "mods": [
                {"cvid": m.cvid, "workshop_id": m.workshop_id, "name": m.name}
                for m in sorted(mods, key=lambda x: x.cvid)
            ],
        }
        canonical_json = json.dumps(canonical, sort_keys=True, separators=(',', ':'))
        return f"sha256:{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()}"


@dataclass
class SymbolsSnapshot:
    """
    A snapshot of all symbols in the active playset.
    
    B0 Schema:
    - playset: Full playset identity for drift detection
    - identities: Set of unique (type, scope, name) tuples
    - provenance: Full provenance records for reporting
    - symbols_hash: Hash of identities (not provenance)
    """
    schema_version: str
    snapshot_id: str
    contract_id: str
    created_at: str
    
    # B0.1: Playset identity
    playset: PlaysetIdentity
    
    # Symbol summary
    identity_count: int
    provenance_count: int
    symbols_hash: str  # Hash of identities only
    identities_by_type: dict[str, int]
    
    # Full data
    identities: list[SymbolIdentity]
    provenance: list[SymbolProvenance]
    
    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "contract_id": self.contract_id,
            "created_at": self.created_at,
            "playset": self.playset.to_dict(),
            "identity_count": self.identity_count,
            "provenance_count": self.provenance_count,
            "symbols_hash": self.symbols_hash,
            "identities_by_type": self.identities_by_type,
            "identities": [i.to_dict() for i in self.identities],
            "provenance": [p.to_dict() for p in self.provenance],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolsSnapshot":
        return cls(
            schema_version=data["schema_version"],
            snapshot_id=data["snapshot_id"],
            contract_id=data["contract_id"],
            created_at=data["created_at"],
            playset=PlaysetIdentity.from_dict(data["playset"]),
            identity_count=data["identity_count"],
            provenance_count=data["provenance_count"],
            symbols_hash=data["symbols_hash"],
            identities_by_type=data["identities_by_type"],
            identities=[SymbolIdentity.from_dict(i) for i in data["identities"]],
            provenance=[SymbolProvenance.from_dict(p) for p in data["provenance"]],
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
    """
    Diff between two symbol snapshots.
    
    B0.3: Compares IDENTITIES, not provenance.
    """
    baseline_id: str
    current_id: str
    baseline_hash: str
    current_hash: str
    hashes_match: bool
    
    # Playset drift check
    playset_match: bool
    playset_drift_message: Optional[str]
    
    # Identity-level diff (B0.3)
    added_identities: list[SymbolIdentity]
    removed_identities: list[SymbolIdentity]
    added_count: int
    removed_count: int
    added_by_type: dict[str, int]
    removed_by_type: dict[str, int]
    
    # Provenance for reporting only (not identity)
    added_provenance: list[SymbolProvenance]
    removed_provenance: list[SymbolProvenance]
    
    def to_dict(self) -> dict:
        return {
            "baseline_id": self.baseline_id,
            "current_id": self.current_id,
            "baseline_hash": self.baseline_hash,
            "current_hash": self.current_hash,
            "hashes_match": self.hashes_match,
            "playset_match": self.playset_match,
            "playset_drift_message": self.playset_drift_message,
            "added_identities": [i.to_dict() for i in self.added_identities],
            "removed_identities": [i.to_dict() for i in self.removed_identities],
            "added_count": self.added_count,
            "removed_count": self.removed_count,
            "added_by_type": self.added_by_type,
            "removed_by_type": self.removed_by_type,
            "added_provenance": [p.to_dict() for p in self.added_provenance],
            "removed_provenance": [p.to_dict() for p in self.removed_provenance],
        }
    
    def summary(self) -> str:
        """Generate human-readable summary."""
        lines = [
            "=== Symbols Diff Summary ===",
            f"Baseline: {self.baseline_id} ({self.baseline_hash[:16]}...)",
            f"Current:  {self.current_id} ({self.current_hash[:16]}...)",
            f"Hashes match: {self.hashes_match}",
            f"Playset match: {self.playset_match}",
            "",
        ]
        
        if not self.playset_match:
            lines.append(f"⚠️  PLAYSET_DRIFT: {self.playset_drift_message}")
            lines.append("")
        
        if self.hashes_match and self.playset_match:
            lines.append("No changes detected.")
            return "\n".join(lines)
        
        if self.added_count > 0:
            lines.append(f"Added identities: {self.added_count}")
            for sym_type, count in sorted(self.added_by_type.items()):
                lines.append(f"  + {sym_type}: {count}")
        
        if self.removed_count > 0:
            lines.append(f"\nRemoved identities: {self.removed_count}")
            for sym_type, count in sorted(self.removed_by_type.items()):
                lines.append(f"  - {sym_type}: {count}")
        
        return "\n".join(lines)


@dataclass
class ExistsCheckResult:
    """
    Result of B0.4 check_symbol_identities_exist().
    """
    contract_id: str
    checked_at: str
    playset_hash: str
    identities_checked: int
    results: dict[str, bool]  # identity_key -> exists
    result_hash: str  # Deterministic hash of results
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def save(self, path: Optional[Path] = None) -> Path:
        """Save to disk."""
        if path is None:
            snapshots_dir = _get_snapshots_dir()
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            path = snapshots_dir / f"{self.contract_id}.exists_check.json"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path


# =============================================================================
# Core Functions
# =============================================================================

def get_active_playset_identity() -> PlaysetIdentity:
    """
    Get full playset identity from the database.
    
    B0.1: Returns playset_cvids, playset_mods, playset_hash.
    """
    db_path = _get_db_path()
    if not db_path.exists():
        raise RuntimeError(f"Database not found: {db_path}")
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        # Get all CVIDs with mod identity
        cursor = conn.execute("""
            SELECT 
                cv.content_version_id,
                cv.kind,
                cv.mod_package_id,
                mp.name,
                mp.workshop_id,
                mp.source_path
            FROM content_versions cv
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            ORDER BY cv.content_version_id
        """)
        
        cvids = []
        mods = []
        
        for row in cursor:
            cvid = row["content_version_id"]
            cvids.append(cvid)
            
            # Determine source_root from path
            source_path = row["source_path"] or ""
            if "steamapps/common" in source_path.lower().replace("\\", "/"):
                source_root = "ROOT_GAME"
            elif "steamapps/workshop" in source_path.lower().replace("\\", "/"):
                source_root = "ROOT_STEAM"
            elif "paradox interactive" in source_path.lower():
                source_root = "ROOT_USER_DOCS"
            else:
                source_root = "ROOT_UNKNOWN"
            
            mods.append(ModIdentity(
                cvid=cvid,
                mod_package_id=row["mod_package_id"],
                name=row["name"],
                workshop_id=row["workshop_id"],
                source_root=source_root,
            ))
        
        # Compute playset hash
        playset_hash = PlaysetIdentity.compute_hash(cvids, mods)
        
        return PlaysetIdentity(
            playset_name="active_playset",  # TODO: Get from session
            cvids=sorted(cvids),
            mods=mods,
            playset_hash=playset_hash,
        )
    finally:
        conn.close()


def query_symbol_provenance(cvids: list[int]) -> list[SymbolProvenance]:
    """
    Query all symbol provenance for the given CVIDs.
    
    B0.2: No DISTINCT, deterministic ORDER BY.
    
    Returns ALL rows - does not deduplicate. Deduplication happens
    at the identity level, not the provenance level.
    """
    db_path = _get_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        placeholders = ",".join("?" * len(cvids))
        
        # B0.2: No DISTINCT, full deterministic ORDER BY
        cursor = conn.execute(f"""
            SELECT
                s.symbol_id,
                s.name,
                s.symbol_type,
                s.scope,
                s.line_number,
                f.content_version_id,
                f.relpath
            FROM symbols s
            JOIN asts a ON s.ast_id = a.ast_id
            JOIN files f ON a.content_hash = f.content_hash
            WHERE f.content_version_id IN ({placeholders})
              AND f.deleted = 0
            ORDER BY
                f.content_version_id,
                f.relpath,
                s.symbol_type,
                s.scope,
                s.name,
                s.line_number,
                s.symbol_id
        """, cvids)
        
        provenance = []
        for row in cursor:
            provenance.append(SymbolProvenance(
                symbol_id=row["symbol_id"],
                name=row["name"],
                symbol_type=row["symbol_type"],
                scope=row["scope"],
                content_version_id=row["content_version_id"],
                file_relpath=row["relpath"],
                line_number=row["line_number"],
            ))
        
        return provenance
    finally:
        conn.close()


def extract_identities(provenance: list[SymbolProvenance]) -> list[SymbolIdentity]:
    """
    Extract unique identities from provenance records.
    
    B0.3: Identity = (symbol_type, scope, name)
    
    Multiple provenance records can map to the same identity (overrides).
    """
    seen = set()
    identities = []
    
    for p in provenance:
        key = p.identity_key()
        if key not in seen:
            seen.add(key)
            identities.append(p.identity())
    
    # Sort for determinism
    identities.sort(key=lambda i: i.key())
    return identities


def compute_identities_hash(identities: list[SymbolIdentity]) -> str:
    """
    Compute deterministic hash of symbol identities.
    
    B0.3: Hash is based on identity keys only, not provenance.
    """
    sorted_keys = sorted(i.key() for i in identities)
    canonical_json = json.dumps(sorted_keys, separators=(',', ':'))
    return f"sha256:{hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()}"


def create_symbols_snapshot(
    contract_id: str,
    playset: Optional[PlaysetIdentity] = None,
) -> SymbolsSnapshot:
    """
    Create a snapshot of current symbols in the active playset.
    
    B0.1: Includes full playset identity
    B0.2: Uses corrected query (no DISTINCT)
    B0.3: Separates identities from provenance
    """
    if playset is None:
        playset = get_active_playset_identity()
    
    # Query all provenance records
    provenance = query_symbol_provenance(playset.cvids)
    
    # Extract unique identities
    identities = extract_identities(provenance)
    
    # Compute hash of identities (not provenance)
    symbols_hash = compute_identities_hash(identities)
    
    # Count by type
    identities_by_type: dict[str, int] = {}
    for ident in identities:
        identities_by_type[ident.symbol_type] = identities_by_type.get(ident.symbol_type, 0) + 1
    
    # Create snapshot
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot_id = f"{contract_id}_{timestamp.replace(':', '-').replace('.', '-')[:19]}"
    
    return SymbolsSnapshot(
        schema_version="v2",  # B0 corrected version
        snapshot_id=snapshot_id,
        contract_id=contract_id,
        created_at=timestamp,
        playset=playset,
        identity_count=len(identities),
        provenance_count=len(provenance),
        symbols_hash=symbols_hash,
        identities_by_type=identities_by_type,
        identities=identities,
        provenance=provenance,
    )


def check_playset_drift(baseline: PlaysetIdentity, current: PlaysetIdentity) -> tuple[bool, Optional[str]]:
    """
    Check if playset has drifted between baseline and current.
    
    B0.1: Contract close must hard-fail on playset mismatch.
    
    Returns:
        (match, error_message) - if match is False, error_message explains drift
    """
    if baseline.playset_hash != current.playset_hash:
        baseline_cvid_set = set(baseline.cvids)
        current_cvid_set = set(current.cvids)
        
        added_cvids = current_cvid_set - baseline_cvid_set
        removed_cvids = baseline_cvid_set - current_cvid_set
        
        parts = []
        if added_cvids:
            parts.append(f"added CVIDs: {sorted(added_cvids)}")
        if removed_cvids:
            parts.append(f"removed CVIDs: {sorted(removed_cvids)}")
        
        if not parts:
            # Same CVIDs but different mods (workshop_id or name changed?)
            parts.append("mod identity changed (same CVIDs, different metadata)")
        
        return False, f"PLAYSET_DRIFT: {'; '.join(parts)}"
    
    return True, None


def diff_symbols(
    baseline: SymbolsSnapshot,
    current: SymbolsSnapshot,
) -> SymbolsDiff:
    """
    Compute diff between two symbol snapshots.
    
    B0.1: Checks playset drift first
    B0.3: Diffs on identity, not provenance
    """
    # Check playset drift first
    playset_match, playset_drift_message = check_playset_drift(
        baseline.playset, current.playset
    )
    
    # Build identity sets
    baseline_keys = {i.key(): i for i in baseline.identities}
    current_keys = {i.key(): i for i in current.identities}
    
    # Find identity differences
    added_keys = set(current_keys.keys()) - set(baseline_keys.keys())
    removed_keys = set(baseline_keys.keys()) - set(current_keys.keys())
    
    added_identities = [current_keys[k] for k in sorted(added_keys)]
    removed_identities = [baseline_keys[k] for k in sorted(removed_keys)]
    
    # Find provenance for reporting (not for identity)
    baseline_prov_keys = {p.identity_key(): p for p in baseline.provenance}
    current_prov_keys = {p.identity_key(): p for p in current.provenance}
    
    added_provenance = [current_prov_keys[k] for k in sorted(added_keys) if k in current_prov_keys]
    removed_provenance = [baseline_prov_keys[k] for k in sorted(removed_keys) if k in baseline_prov_keys]
    
    # Count by type
    added_by_type: dict[str, int] = {}
    for ident in added_identities:
        added_by_type[ident.symbol_type] = added_by_type.get(ident.symbol_type, 0) + 1
    
    removed_by_type: dict[str, int] = {}
    for ident in removed_identities:
        removed_by_type[ident.symbol_type] = removed_by_type.get(ident.symbol_type, 0) + 1
    
    return SymbolsDiff(
        baseline_id=baseline.snapshot_id,
        current_id=current.snapshot_id,
        baseline_hash=baseline.symbols_hash,
        current_hash=current.symbols_hash,
        hashes_match=baseline.symbols_hash == current.symbols_hash,
        playset_match=playset_match,
        playset_drift_message=playset_drift_message,
        added_identities=added_identities,
        removed_identities=removed_identities,
        added_count=len(added_identities),
        removed_count=len(removed_identities),
        added_by_type=added_by_type,
        removed_by_type=removed_by_type,
        added_provenance=added_provenance,
        removed_provenance=removed_provenance,
    )


def check_new_symbols(baseline_path: Path) -> tuple[bool, SymbolsDiff]:
    """
    Check if any new symbol identities have been added since baseline.
    
    B0.1: Also checks playset drift
    B0.3: Checks identities, not provenance
    
    Returns:
        (has_new_or_drift, diff)
    """
    baseline = SymbolsSnapshot.load(baseline_path)
    if baseline is None:
        raise FileNotFoundError(f"Baseline not found: {baseline_path}")
    
    # Create current snapshot with same playset to detect drift
    current = create_symbols_snapshot(
        contract_id=baseline.contract_id + "_check",
    )
    
    diff = diff_symbols(baseline, current)
    
    # Fail if drift or new identities
    has_issues = not diff.playset_match or diff.added_count > 0
    
    return has_issues, diff


def check_symbol_identities_exist(
    contract_id: str,
    identities: list[tuple[str, Optional[str], str]],  # (type, scope, name)
) -> ExistsCheckResult:
    """
    B0.4: Check if specific symbol identities exist in current playset.
    
    Args:
        contract_id: Contract for artifact naming
        identities: List of (symbol_type, scope, name) tuples
    
    Returns:
        ExistsCheckResult with per-identity existence
    """
    playset = get_active_playset_identity()
    provenance = query_symbol_provenance(playset.cvids)
    
    # Build identity set from current DB
    current_identities = set(p.identity_key() for p in provenance)
    
    # Check each requested identity
    results: dict[str, bool] = {}
    for sym_type, scope, name in identities:
        key = f"{sym_type}:{scope or ''}:{name}"
        results[key] = key in current_identities
    
    # Compute deterministic hash of results
    sorted_results = dict(sorted(results.items()))
    result_json = json.dumps(sorted_results, separators=(',', ':'))
    result_hash = f"sha256:{hashlib.sha256(result_json.encode('utf-8')).hexdigest()}"
    
    return ExistsCheckResult(
        contract_id=contract_id,
        checked_at=datetime.now(timezone.utc).isoformat(),
        playset_hash=playset.playset_hash,
        identities_checked=len(identities),
        results=results,
        result_hash=result_hash,
    )


def verify_playset(baseline_path: Path) -> tuple[bool, str]:
    """
    Verify current playset matches baseline playset.
    
    B0.1: Used by contract closure to detect drift.
    
    Returns:
        (match, message)
    """
    baseline = SymbolsSnapshot.load(baseline_path)
    if baseline is None:
        return False, f"Baseline not found: {baseline_path}"
    
    current_playset = get_active_playset_identity()
    
    match, drift_message = check_playset_drift(baseline.playset, current_playset)
    
    if match:
        return True, f"Playset verified: {baseline.playset.playset_hash}"
    else:
        return False, drift_message or "Unknown drift"


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
        print("  check-new <baseline>        Check for new identities since baseline")
        print("  check-exists <contract> <type:scope:name> ...  Check if identities exist")
        print("  verify-playset <baseline>   Verify playset hasn't drifted")
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
        print(f"  Schema version: {snapshot.schema_version}")
        print(f"  Identities: {snapshot.identity_count}")
        print(f"  Provenance records: {snapshot.provenance_count}")
        print(f"  Playset CVIDs: {len(snapshot.playset.cvids)}")
        print(f"  Playset hash: {snapshot.playset.playset_hash[:32]}...")
        print(f"  Symbols hash: {snapshot.symbols_hash[:32]}...")
        print()
        print("Identity counts by type:")
        for sym_type, count in sorted(snapshot.identities_by_type.items(), key=lambda x: -x[1])[:10]:
            print(f"  {sym_type}: {count}")
    
    elif command == "diff":
        if len(sys.argv) < 4:
            print("Usage: diff <baseline> <current>")
            sys.exit(1)
        
        baseline_path = _resolve_snapshot_path(sys.argv[2])
        current_path = _resolve_snapshot_path(sys.argv[3])
        
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
        
        if not diff.playset_match:
            sys.exit(2)  # Playset drift
        if diff.added_count > 0:
            sys.exit(1)  # New symbols
    
    elif command == "check-new":
        if len(sys.argv) < 3:
            print("Usage: check-new <baseline>")
            sys.exit(1)
        
        baseline_path = _resolve_snapshot_path(sys.argv[2])
        
        try:
            has_issues, diff = check_new_symbols(baseline_path)
            
            if not diff.playset_match:
                print(f"[FAIL] {diff.playset_drift_message}")
                sys.exit(2)
            
            if diff.added_count > 0:
                print(f"NEW IDENTITIES DETECTED: {diff.added_count}")
                print()
                print("New identities by type:")
                for sym_type, count in sorted(diff.added_by_type.items()):
                    print(f"  + {sym_type}: {count}")
                
                if diff.added_count <= 20:
                    print()
                    print("New identities:")
                    for ident in diff.added_identities[:20]:
                        print(f"  + {ident.key()}")
                
                sys.exit(1)
            else:
                print("[OK] No new identities detected.")
                print(f"  Playset hash: {diff.current_hash[:16]}...")
                sys.exit(0)
        
        except FileNotFoundError as e:
            print(f"Error: {e}")
            sys.exit(1)
    
    elif command == "check-exists":
        if len(sys.argv) < 4:
            print("Usage: check-exists <contract_id> <type:scope:name> ...")
            sys.exit(1)
        
        contract_id = sys.argv[2]
        identity_strs = sys.argv[3:]
        
        # Parse identities
        identities = []
        for s in identity_strs:
            parts = s.split(":", 2)
            if len(parts) < 3:
                print(f"Invalid identity format: {s} (expected type:scope:name)")
                sys.exit(1)
            identities.append((parts[0], parts[1] if parts[1] else None, parts[2]))
        
        result = check_symbol_identities_exist(contract_id, identities)
        path = result.save()
        
        print(f"Exists check saved: {path}")
        print(f"  Playset hash: {result.playset_hash[:32]}...")
        print(f"  Result hash: {result.result_hash[:32]}...")
        print()
        print("Results:")
        for key, exists in sorted(result.results.items()):
            mark = "[Y]" if exists else "[N]"
            print(f"  {mark} {key}")
    
    elif command == "verify-playset":
        if len(sys.argv) < 3:
            print("Usage: verify-playset <baseline>")
            sys.exit(1)
        
        baseline_path = _resolve_snapshot_path(sys.argv[2])
        match, message = verify_playset(baseline_path)
        
        if match:
            print(f"[OK] {message}")
            sys.exit(0)
        else:
            print(f"[FAIL] {message}")
            sys.exit(2)
    
    elif command == "status":
        playset = get_active_playset_identity()
        provenance = query_symbol_provenance(playset.cvids)
        identities = extract_identities(provenance)
        
        print(f"Playset: {playset.playset_name}")
        print(f"CVIDs: {len(playset.cvids)}")
        print(f"Playset hash: {playset.playset_hash[:32]}...")
        print(f"Total identities: {len(identities)}")
        print(f"Total provenance records: {len(provenance)}")
        print()
        
        # Count by type
        by_type: dict[str, int] = {}
        for ident in identities:
            by_type[ident.symbol_type] = by_type.get(ident.symbol_type, 0) + 1
        
        print("Identities by type:")
        for sym_type, count in sorted(by_type.items(), key=lambda x: -x[1])[:15]:
            print(f"  {sym_type}: {count}")
    
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
