"""
Contract v1 Schema — Hard Law Implementation

This module implements the EXACT contract schema from CANONICAL CONTRACT SYSTEM.

Authority: CANONICAL CONTRACT SYSTEM, Part II (Hard Law)
Status: CANONICAL - No extensions, no interpretations

Key Principles:
1. Contracts declare intent and impact, not implementation
2. One root_category per contract (geographic, not semantic)
3. Unknown fields are REJECTED (strict validation)
4. No backward compatibility with legacy schemas

Contract Shape (Section 5):
{
  "contract_id": "string",
  "mode": "ck3raven-dev | ck3lens",
  "root_category": "ROOT_*",
  "intent": "short free-text label",
  "operations": ["READ", "WRITE", "..."],
  "targets": [],
  "work_declaration": {},
  "created_at": "ISO-8601",
  "author": "string"
}
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional

from .capability_matrix import AgentMode, RootCategory, Operation, validate_operations


# =============================================================================
# SCHEMA VERSION
# =============================================================================

CONTRACT_SCHEMA_VERSION = "v1"

# Known fields in Contract v1 (for strict validation)
_V1_REQUIRED_FIELDS = frozenset({
    "contract_id",
    "mode",
    "root_category",
    "intent",
    "operations",
    "targets",
    "work_declaration",
    "created_at",
    "author",
})

_V1_OPTIONAL_FIELDS = frozenset({
    "expires_at",
    "status",
    "closed_at",
    "notes",
    "schema_version",
})

_V1_ALL_FIELDS = _V1_REQUIRED_FIELDS | _V1_OPTIONAL_FIELDS

# BANNED FIELDS (immediate rejection per Section 3.1)
_BANNED_FIELDS = frozenset({
    "canonical_domains",
    "active_local_mods",
    "active_workshop_mods",
    "intent_type",  # Moved inside work_declaration
    "targets_legacy",
    "allowed_paths",  # Legacy field, replaced by targets
    "capabilities",  # Legacy field, replaced by operations
})


# =============================================================================
# TARGET TYPES (Section 7)
# =============================================================================

class TargetType(str, Enum):
    """Target types for contract scope declaration."""
    FILE = "file"
    FOLDER = "folder"
    COMMAND = "command"
    DB_TABLE = "db_table"


@dataclass
class ContractTarget:
    """
    A target in the contract scope (Section 7).
    
    Targets define WHAT objects are in scope, not how they are processed.
    """
    target_type: TargetType | str
    path: str  # Canonical RELATIVE path (absolute paths forbidden)
    description: str
    
    def __post_init__(self):
        # Normalize target_type
        if isinstance(self.target_type, str):
            self.target_type = TargetType(self.target_type)
        
        # Validate: absolute paths are forbidden
        if self.path.startswith("/") or (len(self.path) > 1 and self.path[1] == ":"):
            raise ValueError(f"Absolute paths are forbidden in targets: {self.path}")
    
    def to_dict(self) -> dict:
        return {
            "target_type": self.target_type.value if isinstance(self.target_type, TargetType) else self.target_type,
            "path": self.path,
            "description": self.description,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ContractTarget":
        return cls(
            target_type=data["target_type"],
            path=data["path"],
            description=data["description"],
        )


# =============================================================================
# WORK DECLARATION (Section 8)
# =============================================================================

@dataclass
class EditDeclaration:
    """Declaration of a specific edit within work_declaration."""
    file: str
    edit_kind: str  # e.g., "add", "modify", "delete", "rename"
    location: str   # e.g., "line 42-50", "after trait definition"
    change_description: str
    post_conditions: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "EditDeclaration":
        return cls(
            file=data["file"],
            edit_kind=data["edit_kind"],
            location=data["location"],
            change_description=data["change_description"],
            post_conditions=data.get("post_conditions", []),
        )


@dataclass
class SymbolIntent:
    """
    Symbol creation intent (Section 9).
    
    Symbol creation must be declared explicitly. Silent invention is forbidden.
    """
    creating_symbols: bool = False
    symbols: list[dict] = field(default_factory=list)  # [{type, name, reason}]
    
    def to_dict(self) -> dict:
        return {
            "creating_symbols": self.creating_symbols,
            "symbols": self.symbols,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SymbolIntent":
        return cls(
            creating_symbols=data.get("creating_symbols", False),
            symbols=data.get("symbols", []),
        )


@dataclass
class WorkDeclaration:
    """
    Work declaration (Section 8).
    
    This information is for audit, not automation.
    """
    work_summary: str
    work_plan: list[str]  # 3-15 bullets
    out_of_scope: list[str]
    symbol_intent: SymbolIntent
    edits: list[EditDeclaration] = field(default_factory=list)  # Required if mutating
    
    def __post_init__(self):
        # Validate work_plan length
        if len(self.work_plan) < 1:
            raise ValueError("work_plan must have at least 1 item")
        if len(self.work_plan) > 15:
            raise ValueError("work_plan must have at most 15 items")
    
    def to_dict(self) -> dict:
        return {
            "work_summary": self.work_summary,
            "work_plan": self.work_plan,
            "out_of_scope": self.out_of_scope,
            "symbol_intent": self.symbol_intent.to_dict(),
            "edits": [e.to_dict() for e in self.edits],
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "WorkDeclaration":
        symbol_intent = SymbolIntent.from_dict(data.get("symbol_intent", {}))
        edits = [EditDeclaration.from_dict(e) for e in data.get("edits", [])]
        return cls(
            work_summary=data.get("work_summary", ""),
            work_plan=data.get("work_plan", ["TBD"]),
            out_of_scope=data.get("out_of_scope", []),
            symbol_intent=symbol_intent,
            edits=edits,
        )


# =============================================================================
# CONTRACT V1 (Section 5)
# =============================================================================

@dataclass
class ContractV1:
    """
    Contract v1 — The canonical contract schema.
    
    Every field must match Section 5 exactly.
    Unknown fields are rejected.
    """
    # Required fields
    contract_id: str
    mode: AgentMode | str
    root_category: RootCategory | str
    intent: str
    operations: list[Operation | str]
    targets: list[ContractTarget]
    work_declaration: WorkDeclaration
    created_at: str  # ISO-8601
    author: str
    
    # Optional fields
    expires_at: Optional[str] = None
    status: Literal["open", "closed", "expired", "cancelled"] = "open"
    closed_at: Optional[str] = None
    notes: Optional[str] = None
    schema_version: str = CONTRACT_SCHEMA_VERSION    
    def __post_init__(self):
        # Normalize mode
        if isinstance(self.mode, str):
            self.mode = AgentMode(self.mode)
        
        # Normalize root_category
        if isinstance(self.root_category, str):
            self.root_category = RootCategory(self.root_category)
        
        # Normalize operations
        normalized_ops = []
        for op in self.operations:
            if isinstance(op, str):
                normalized_ops.append(Operation(op))
            else:
                normalized_ops.append(op)
        self.operations = normalized_ops
    
    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique contract ID."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_hash = hashlib.sha256(now.isoformat().encode()).hexdigest()[:6]
        return f"v1-{date_str}-{time_hash}"
    
    def validate(self) -> tuple[bool, list[str]]:
        """
        Validate contract against v1 schema.
        
        Returns:
            (valid: bool, errors: list[str])
        """
        errors = []
        
        # Validate operations against capability matrix
        valid, denied = validate_operations(self.mode, self.root_category, self.operations)
        if not valid:
            mode_val = self.mode.value if isinstance(self.mode, AgentMode) else self.mode
            root_val = self.root_category.value if isinstance(self.root_category, RootCategory) else self.root_category
            errors.append(f"Operations not authorized for {mode_val}/{root_val}: {denied}")
        
        # Validate targets have required fields
        for i, target in enumerate(self.targets):
            if not target.path:
                errors.append(f"Target {i}: path is required")
            if not target.description:
                errors.append(f"Target {i}: description is required")
        
        # Validate work_declaration has required content
        if not self.work_declaration.work_summary:
            errors.append("work_declaration.work_summary is required")
        if len(self.work_declaration.work_plan) < 1:
            errors.append("work_declaration.work_plan must have at least 1 item")
        
        # If mutating operations, edits should be declared
        mutating = {Operation.WRITE, Operation.DELETE, Operation.RENAME}
        has_mutating = any(op in mutating for op in self.operations)
        if has_mutating and not self.work_declaration.edits:
            errors.append("Mutating operations require edits in work_declaration")
        
        return (len(errors) == 0, errors)
    
    def is_expired(self) -> bool:
        """Check if contract has expired."""
        if self.expires_at:
            expires = datetime.fromisoformat(self.expires_at)
            return datetime.now() > expires
        return False
    
    def is_active(self) -> bool:
        """Check if contract is currently active."""
        return self.status == "open" and not self.is_expired()
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "mode": self.mode.value if isinstance(self.mode, AgentMode) else self.mode,
            "root_category": self.root_category.value if isinstance(self.root_category, RootCategory) else self.root_category,
            "intent": self.intent,
            "operations": [op.value if isinstance(op, Operation) else op for op in self.operations],
            "targets": [t.to_dict() for t in self.targets],
            "work_declaration": self.work_declaration.to_dict(),
            "created_at": self.created_at,
            "author": self.author,
            "expires_at": self.expires_at,
            "status": self.status,
            "closed_at": self.closed_at,
            "notes": self.notes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "ContractV1":
        """
        Deserialize from dictionary with strict validation.
        
        Raises:
            ValueError: If data contains banned or unknown fields
        """
        # Check for banned fields (Section 3.1)
        banned_found = set(data.keys()) & _BANNED_FIELDS
        if banned_found:
            raise ValueError(f"Contract contains banned fields (rejected): {banned_found}")
        
        # Check for unknown fields
        unknown = set(data.keys()) - _V1_ALL_FIELDS
        if unknown:
            raise ValueError(f"Contract contains unknown fields (rejected): {unknown}")
        
        # Check required fields
        missing = _V1_REQUIRED_FIELDS - set(data.keys())
        if missing:
            raise ValueError(f"Contract missing required fields: {missing}")
        
        # Parse targets
        targets = [ContractTarget.from_dict(t) for t in data.get("targets", [])]
        
        # Parse work_declaration
        work_decl = WorkDeclaration.from_dict(data["work_declaration"])
        
        return cls(
            contract_id=data["contract_id"],
            mode=data["mode"],
            root_category=data["root_category"],
            intent=data["intent"],
            operations=data["operations"],
            targets=targets,
            work_declaration=work_decl,
            created_at=data["created_at"],
            author=data["author"],
            expires_at=data.get("expires_at"),
            status=data.get("status", "open"),
            closed_at=data.get("closed_at"),
            notes=data.get("notes"),
            schema_version=data.get("schema_version", CONTRACT_SCHEMA_VERSION),
        )


# =============================================================================
# CONTRACT STORAGE (v1 only)
# =============================================================================

def _get_contracts_dir() -> Path:
    """Get the contracts directory, creating if needed."""
    path = Path.home() / ".ck3raven" / "contracts" / "v1"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_archive_dir() -> Path:
    """Get the archive directory for old contracts."""
    path = Path.home() / ".ck3raven" / "contracts" / "v1" / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_legacy_archive_dir() -> Path:
    """Get the archive directory for legacy (pre-v1) contracts."""
    path = Path.home() / ".ck3raven" / "contracts" / "archive" / "legacy_pre_v1"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_contract(contract: ContractV1) -> Path:
    """Save a v1 contract to disk."""
    contracts_dir = _get_contracts_dir()
    path = contracts_dir / f"{contract.contract_id}.json"
    path.write_text(json.dumps(contract.to_dict(), indent=2))
    return path


def load_contract(contract_id: str) -> Optional[ContractV1]:
    """Load a v1 contract by ID."""
    contracts_dir = _get_contracts_dir()
    path = contracts_dir / f"{contract_id}.json"
    
    if not path.exists():
        # Check archive
        archive_path = _get_archive_dir() / f"{contract_id}.json"
        if archive_path.exists():
            path = archive_path
        else:
            return None
    
    data = json.loads(path.read_text())
    return ContractV1.from_dict(data)


def get_active_contract() -> Optional[ContractV1]:
    """Get the currently active (open, non-expired) v1 contract."""
    contracts_dir = _get_contracts_dir()
    
    for path in contracts_dir.glob("v1-*.json"):
        try:
            data = json.loads(path.read_text())
            contract = ContractV1.from_dict(data)
            if contract.is_active():
                return contract
        except Exception:
            continue
    
    return None


def list_contracts(
    status: Optional[str] = None,
    include_archived: bool = False,
) -> list[ContractV1]:
    """List v1 contracts with optional filters."""
    contracts = []
    contracts_dir = _get_contracts_dir()
    
    # Current contracts
    for path in contracts_dir.glob("v1-*.json"):
        try:
            data = json.loads(path.read_text())
            contract = ContractV1.from_dict(data)
            if status is None or contract.status == status:
                contracts.append(contract)
        except Exception:
            continue
    
    # Archived contracts
    if include_archived:
        archive_dir = _get_archive_dir()
        for path in archive_dir.glob("v1-*.json"):
            try:
                data = json.loads(path.read_text())
                contract = ContractV1.from_dict(data)
                if status is None or contract.status == status:
                    contracts.append(contract)
            except Exception:
                continue
    
    # Sort by created_at descending
    contracts.sort(key=lambda c: c.created_at, reverse=True)
    return contracts


# =============================================================================
# CONTRACT LIFECYCLE
# =============================================================================

def open_contract(
    mode: AgentMode | str,
    root_category: RootCategory | str,
    intent: str,
    operations: list[Operation | str],
    targets: list[ContractTarget] | list[dict],
    work_declaration: WorkDeclaration | dict,
    author: str = "agent",
    expires_hours: float = 8.0,
    notes: Optional[str] = None,
) -> ContractV1:
    """
    Open a new v1 contract.
    
    Args:
        mode: Agent mode (ck3lens or ck3raven-dev)
        root_category: Geographic root for this contract
        intent: Short description of work
        operations: List of requested operations
        targets: List of targets in scope
        work_declaration: Work declaration with plan and edits
        author: Who is opening this contract
        expires_hours: Hours until expiration
        notes: Optional notes
    
    Returns:
        The opened contract
    
    Raises:
        ValueError: If contract validation fails
    """
    # Normalize targets
    if targets and isinstance(targets[0], dict):
        targets = [ContractTarget.from_dict(t) for t in targets]
    
    # Normalize work_declaration
    if isinstance(work_declaration, dict):
        work_declaration = WorkDeclaration.from_dict(work_declaration)
    
    contract = ContractV1(
        contract_id=ContractV1.generate_id(),
        mode=mode,
        root_category=root_category,
        intent=intent,
        operations=operations,
        targets=targets,
        work_declaration=work_declaration,
        created_at=datetime.now().isoformat(),
        author=author,
        expires_at=(datetime.now() + timedelta(hours=expires_hours)).isoformat(),
        notes=notes,
    )
    
    # Validate before saving
    valid, errors = contract.validate()
    if not valid:
        raise ValueError(f"Contract validation failed: {errors}")
    
    save_contract(contract)
    return contract


def close_contract(contract_id: str, notes: Optional[str] = None) -> ContractV1:
    """Close a contract."""
    contract = load_contract(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    if contract.status != "open":
        raise ValueError(f"Contract is not open: {contract.status}")
    
    contract.status = "closed"
    contract.closed_at = datetime.now().isoformat()
    if notes:
        contract.notes = (contract.notes or "") + f"\n[CLOSED] {notes}"
    
    save_contract(contract)
    return contract


def cancel_contract(contract_id: str, reason: str = "") -> ContractV1:
    """Cancel a contract."""
    contract = load_contract(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    contract.status = "cancelled"
    contract.closed_at = datetime.now().isoformat()
    if reason:
        contract.notes = (contract.notes or "") + f"\n[CANCELLED] {reason}"
    
    save_contract(contract)
    return contract


# =============================================================================
# LEGACY MIGRATION (Hard Cutover)
# =============================================================================

def archive_legacy_contracts() -> int:
    """
    Archive all legacy (non-v1) contracts.
    
    Per Section 3.2: Hard Cutover Requirement
    - All existing on-disk contracts using legacy schemas MUST be archived
    - Legacy contracts MUST NOT be parsed, migrated, or interpreted
    
    Returns:
        Number of contracts archived
    """
    import shutil
    
    legacy_dir = Path.home() / ".ck3raven" / "contracts"
    archive_dir = _get_legacy_archive_dir()
    
    archived = 0
    
    # Find legacy contract files (wcp-* pattern, not v1-*)
    for path in legacy_dir.glob("wcp-*.json"):
        try:
            # Move to legacy archive (don't parse, don't migrate)
            dest = archive_dir / path.name
            shutil.move(str(path), str(dest))
            archived += 1
        except Exception:
            continue
    
    return archived
