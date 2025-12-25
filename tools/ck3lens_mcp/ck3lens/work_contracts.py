"""
Work Contract Protocol (WCP) for CLI Wrapping

Work contracts define the scope and constraints for agent tasks.
Every task requiring writes or destructive operations must have
an active work contract.

Contract Lifecycle:
1. Agent opens contract with intent, canonical_domains, and capabilities
2. Policy engine validates requested capabilities
3. Agent performs work within contract bounds
4. Agent closes contract with closure_commit
5. Pre-commit verifies contract was properly closed

Storage:
- Active contracts: ~/.ck3raven/contracts/
- Archived contracts: ~/.ck3raven/contracts/archive/
- Session flush: Archive contracts from previous days at session start
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Literal, Optional


# Contract storage paths
def _get_contracts_dir() -> Path:
    """Get the contracts directory, creating if needed."""
    path = Path.home() / ".ck3raven" / "contracts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_archive_dir() -> Path:
    """Get the archive directory for old contracts."""
    path = _get_contracts_dir() / "archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


# Valid canonical domains
CANONICAL_DOMAINS = frozenset({
    "parser",      # src/ck3raven/parser/
    "routing",     # src/ck3raven/resolver/
    "builder",     # builder/
    "extraction",  # src/ck3raven/db/ (ingest, symbols, refs)
    "query",       # src/ck3raven/db/ (search, playsets), tools/ck3lens_mcp/ck3lens/
    "cli",         # CLI glue, tools/, scripts/
})

# Capability tiers
CAPABILITIES = frozenset({
    # Filesystem
    "FS_READ",               # Read any file
    "FS_WRITE_TMP",          # Write to temp directories
    "FS_WRITE_CODE",         # Write to canonical source directories
    "FS_WRITE_EPHEMERAL",    # Write to scripts/one_off/
    "FS_DELETE_TMP",         # Delete temp files
    "FS_DELETE_CODE",        # Delete source files (rare)
    
    # Commands
    "CMD_RUN_READONLY",      # Read-only commands (git status, cat, etc.)
    "CMD_RUN_PYTHON_MODULE", # Run python -m ...
    "CMD_RUN_TESTS",         # Run pytest
    "CMD_RUN_DESTRUCTIVE",   # rm, git reset, etc.
    
    # Git
    "GIT_STAGE",             # git add
    "GIT_COMMIT",            # git commit  
    "GIT_PUSH",              # git push
    "GIT_REWRITE_HISTORY",   # git rebase, git reset --hard
    
    # Database (informational - actual protection via triggers)
    "DB_READ",               # Query database
    "DB_WRITE_BUILDER",      # Builder writes (only builder daemon has this)
    "DB_SCHEMA_MIGRATE",     # Schema changes
})

# Capability tiers for auto-grant
TIER_READ_ONLY = frozenset({
    "FS_READ",
    "CMD_RUN_READONLY",
    "DB_READ",
})

TIER_STANDARD = TIER_READ_ONLY | frozenset({
    "FS_WRITE_TMP",
    "FS_WRITE_CODE",
    "CMD_RUN_PYTHON_MODULE",
    "CMD_RUN_TESTS",
    "GIT_STAGE",
    "GIT_COMMIT",
})


@dataclass
class WorkContract:
    """
    Work Contract Protocol (WCP) contract.
    
    Defines the scope and constraints for an agent task.
    """
    # Identity
    contract_id: str
    
    # Intent and scope
    intent: str  # What the agent is trying to accomplish
    canonical_domains: list[str]  # Which domains this work touches
    
    # Allowed paths (glob patterns)
    allowed_paths: list[str] = field(default_factory=list)
    
    # Requested capabilities
    capabilities: list[str] = field(default_factory=list)
    
    # Lifecycle
    status: Literal["open", "closed", "expired", "cancelled"] = "open"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None  # ISO timestamp
    closed_at: Optional[str] = None
    closure_commit: Optional[str] = None  # Git commit SHA that closed this
    
    # Metadata
    agent_mode: Optional[str] = None  # ck3lens or ck3raven-dev
    notes: Optional[str] = None
    
    def __post_init__(self):
        # Validate canonical domains
        invalid_domains = set(self.canonical_domains) - CANONICAL_DOMAINS
        if invalid_domains:
            raise ValueError(f"Invalid canonical domains: {invalid_domains}")
        
        # Validate capabilities
        invalid_caps = set(self.capabilities) - CAPABILITIES
        if invalid_caps:
            raise ValueError(f"Invalid capabilities: {invalid_caps}")
    
    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique contract ID."""
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        time_hash = hashlib.sha256(now.isoformat().encode()).hexdigest()[:6]
        return f"wcp-{date_str}-{time_hash}"
    
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
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "WorkContract":
        """Create from dictionary."""
        return cls(**data)
    
    def save(self) -> Path:
        """Save contract to disk."""
        contracts_dir = _get_contracts_dir()
        path = contracts_dir / f"{self.contract_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
    
    @classmethod
    def load(cls, contract_id: str) -> Optional["WorkContract"]:
        """Load contract by ID from disk."""
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
        return cls.from_dict(data)


def open_contract(
    intent: str,
    canonical_domains: list[str],
    allowed_paths: Optional[list[str]] = None,
    capabilities: Optional[list[str]] = None,
    expires_hours: float = 8.0,
    agent_mode: Optional[str] = None,
    notes: Optional[str] = None,
) -> WorkContract:
    """
    Open a new work contract.
    
    Args:
        intent: Human-readable description of what work will be done
        canonical_domains: List of domains this work touches
        allowed_paths: Glob patterns for allowed file paths
        capabilities: Requested capabilities (defaults to TIER_STANDARD)
        expires_hours: Hours until contract expires (default 8)
        agent_mode: ck3lens or ck3raven-dev
        notes: Optional notes
    
    Returns:
        The opened contract
    """
    # Default capabilities
    if capabilities is None:
        capabilities = list(TIER_STANDARD)
    
    # Default paths based on domains
    if allowed_paths is None:
        allowed_paths = []
        domain_paths = {
            "parser": ["src/ck3raven/parser/**"],
            "routing": ["src/ck3raven/resolver/**"],
            "builder": ["builder/**"],
            "extraction": ["src/ck3raven/db/**"],
            "query": ["src/ck3raven/db/**", "tools/ck3lens_mcp/**"],
            "cli": ["tools/**", "scripts/**"],
        }
        for domain in canonical_domains:
            allowed_paths.extend(domain_paths.get(domain, []))
        # Always allow tests
        allowed_paths.append("tests/**")
    
    contract = WorkContract(
        contract_id=WorkContract.generate_id(),
        intent=intent,
        canonical_domains=canonical_domains,
        allowed_paths=allowed_paths,
        capabilities=capabilities,
        expires_at=(datetime.now().replace(microsecond=0) + 
                   __import__("datetime").timedelta(hours=expires_hours)).isoformat(),
        agent_mode=agent_mode,
        notes=notes,
    )
    
    contract.save()
    return contract


def close_contract(
    contract_id: str,
    closure_commit: Optional[str] = None,
) -> WorkContract:
    """
    Close a work contract.
    
    Args:
        contract_id: ID of contract to close
        closure_commit: Git commit SHA (if work was committed)
    
    Returns:
        The closed contract
    """
    contract = WorkContract.load(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    if contract.status != "open":
        raise ValueError(f"Contract is not open: {contract.status}")
    
    contract.status = "closed"
    contract.closed_at = datetime.now().isoformat()
    contract.closure_commit = closure_commit
    
    contract.save()
    return contract


def cancel_contract(contract_id: str, reason: str = "") -> WorkContract:
    """
    Cancel a work contract without completing work.
    
    Args:
        contract_id: ID of contract to cancel
        reason: Why the contract is being cancelled
    
    Returns:
        The cancelled contract
    """
    contract = WorkContract.load(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    contract.status = "cancelled"
    contract.closed_at = datetime.now().isoformat()
    if reason:
        contract.notes = (contract.notes or "") + f"\n[CANCELLED] {reason}"
    
    contract.save()
    return contract


def get_active_contract() -> Optional[WorkContract]:
    """
    Get the currently active (open, non-expired) contract.
    
    Returns:
        Active contract or None if no active contract
    """
    contracts_dir = _get_contracts_dir()
    
    for path in contracts_dir.glob("wcp-*.json"):
        try:
            contract = WorkContract.from_dict(json.loads(path.read_text()))
            if contract.is_active():
                return contract
        except Exception:
            continue
    
    return None


def list_contracts(
    status: Optional[str] = None,
    include_archived: bool = False,
) -> list[WorkContract]:
    """
    List contracts with optional filters.
    
    Args:
        status: Filter by status (open, closed, expired, cancelled)
        include_archived: Include archived contracts
    
    Returns:
        List of matching contracts
    """
    contracts = []
    contracts_dir = _get_contracts_dir()
    
    # Current contracts
    for path in contracts_dir.glob("wcp-*.json"):
        try:
            contract = WorkContract.from_dict(json.loads(path.read_text()))
            if status is None or contract.status == status:
                contracts.append(contract)
        except Exception:
            continue
    
    # Archived contracts
    if include_archived:
        archive_dir = _get_archive_dir()
        for path in archive_dir.glob("wcp-*.json"):
            try:
                contract = WorkContract.from_dict(json.loads(path.read_text()))
                if status is None or contract.status == status:
                    contracts.append(contract)
            except Exception:
                continue
    
    # Sort by created_at descending
    contracts.sort(key=lambda c: c.created_at, reverse=True)
    return contracts


def flush_old_contracts() -> int:
    """
    Archive contracts from previous days.
    
    Called at session start to clean up old contracts.
    
    Returns:
        Number of contracts archived
    """
    today = date.today()
    contracts_dir = _get_contracts_dir()
    archive_dir = _get_archive_dir()
    archived = 0
    
    for path in contracts_dir.glob("wcp-*.json"):
        try:
            contract = WorkContract.from_dict(json.loads(path.read_text()))
            
            # Parse date from contract_id (wcp-YYYY-MM-DD-xxxxxx)
            parts = contract.contract_id.split("-")
            if len(parts) >= 4:
                contract_date = date(int(parts[1]), int(parts[2]), int(parts[3]))
                
                if contract_date < today:
                    # Auto-expire open contracts from previous days
                    if contract.status == "open":
                        contract.status = "expired"
                        contract.closed_at = datetime.now().isoformat()
                        contract.notes = (contract.notes or "") + "\n[AUTO-EXPIRED] Day boundary crossed"
                    
                    # Move to archive
                    archive_path = archive_dir / path.name
                    archive_path.write_text(json.dumps(contract.to_dict(), indent=2))
                    path.unlink()
                    archived += 1
        except Exception:
            continue
    
    return archived


def validate_path_against_contract(
    path: str,
    contract: WorkContract,
) -> bool:
    """
    Check if a path is allowed by the contract.
    
    Args:
        path: Relative path to check
        contract: Active contract
    
    Returns:
        True if path is allowed
    """
    import fnmatch
    
    for pattern in contract.allowed_paths:
        if fnmatch.fnmatch(path, pattern):
            return True
    
    return False


def validate_capability(
    capability: str,
    contract: WorkContract,
) -> bool:
    """
    Check if a capability is granted by the contract.
    
    Args:
        capability: Capability to check
        contract: Active contract
    
    Returns:
        True if capability is granted
    """
    return capability in contract.capabilities
