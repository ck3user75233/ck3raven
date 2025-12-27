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

CK3Lens Mode Extensions:
- Contracts must declare intent_type (COMPATCH, BUGPATCH, etc.)
- Write contracts require targets, snippets, and DIFF_SANITY
- Delete operations require explicit file list + approval token
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Literal, Optional, Any

# Import new policy types for CK3Lens
from .policy.types import IntentType, AcceptanceTest, ScopeDomain


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


# Valid canonical domains for ck3raven-dev mode
CANONICAL_DOMAINS = frozenset({
    "parser",      # src/ck3raven/parser/
    "routing",     # src/ck3raven/resolver/
    "builder",     # builder/
    "extraction",  # src/ck3raven/db/ (ingest, symbols, refs)
    "query",       # src/ck3raven/db/ (search, playsets), tools/ck3lens_mcp/ck3lens/
    "cli",         # CLI glue, tools/, scripts/
})

# Valid domains for ck3lens mode (CK3 modding)
CK3LENS_DOMAINS = frozenset({
    "active_local_mods",   # Editable local mods
    "active_workshop_mods",  # Read-only workshop mods
    "vanilla",             # Read-only vanilla game
    "wip_workspace",       # ~/.ck3raven/wip/ for scripts
    "launcher",            # Launcher registry repair (via ck3_repair)
})

# Combined for validation
ALL_DOMAINS = CANONICAL_DOMAINS | CK3LENS_DOMAINS

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
    
    For ck3lens mode, contracts require:
    - intent_type: One of COMPATCH, BUGPATCH, RESEARCH_MOD_ISSUES, RESEARCH_BUGREPORT, SCRIPT_WIP
    - targets: For write intents, list of {mod_id, rel_path} 
    - snippets: For write intents, before/after code snippets
    - acceptance_tests: For write intents, must include DIFF_SANITY
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
    
    # ============================================
    # CK3Lens-specific fields (Phase 2 additions)
    # ============================================
    
    # Intent type (REQUIRED for ck3lens write operations)
    intent_type: Optional[str] = None  # IntentType value
    
    # Targets for write contracts [{mod_id, rel_path, operation}]
    targets: list[dict[str, str]] = field(default_factory=list)
    
    # Before/after snippets for change preview
    before_after_snippets: list[dict[str, Any]] = field(default_factory=list)
    
    # Change summary (required if >3 files)
    change_summary: Optional[str] = None
    
    # Rollback plan (required for write contracts)
    rollback_plan: Optional[str] = None
    
    # Acceptance tests (must include DIFF_SANITY for writes)
    acceptance_tests: list[str] = field(default_factory=list)
    
    # Script execution fields (for SCRIPT_WIP intent)
    script_hash: Optional[str] = None
    declared_reads: list[str] = field(default_factory=list)
    declared_writes: list[str] = field(default_factory=list)
    
    # Research fields (for RESEARCH_* intents)
    findings_evidence: Optional[str] = None
    ck3raven_source_access: bool = False
    
    # Approval tokens bound to this contract
    bound_tokens: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        # Validate domains based on mode
        if self.agent_mode == "ck3lens":
            # CK3Lens uses CK3LENS_DOMAINS
            invalid_domains = set(self.canonical_domains) - CK3LENS_DOMAINS
            if invalid_domains:
                raise ValueError(f"Invalid ck3lens domains: {invalid_domains}. Valid: {CK3LENS_DOMAINS}")
        elif self.agent_mode == "ck3raven-dev":
            # ck3raven-dev uses CANONICAL_DOMAINS
            invalid_domains = set(self.canonical_domains) - CANONICAL_DOMAINS
            if invalid_domains:
                raise ValueError(f"Invalid ck3raven-dev domains: {invalid_domains}")
        else:
            # Unknown or unset mode - allow all domains
            invalid_domains = set(self.canonical_domains) - ALL_DOMAINS
            if invalid_domains:
                raise ValueError(f"Invalid domains: {invalid_domains}")
        
        # Validate capabilities
        invalid_caps = set(self.capabilities) - CAPABILITIES
        if invalid_caps:
            raise ValueError(f"Invalid capabilities: {invalid_caps}")
    
    def validate_ck3lens_requirements(self) -> tuple[bool, list[str]]:
        """
        Validate CK3Lens-specific contract requirements.
        
        Returns:
            (valid: bool, errors: list[str])
        """
        errors = []
        
        if self.agent_mode != "ck3lens":
            return True, []  # Not a ck3lens contract
        
        # Check intent_type is set
        if not self.intent_type:
            errors.append("ck3lens contract must specify intent_type")
            return False, errors
        
        # Validate intent_type is known
        try:
            intent = IntentType(self.intent_type)
        except ValueError:
            errors.append(f"Unknown intent_type: {self.intent_type}")
            return False, errors
        
        # Write intent requirements
        if intent in {IntentType.COMPATCH, IntentType.BUGPATCH}:
            if not self.targets:
                errors.append("Write contract must have targets")
            
            if self.targets and not self.before_after_snippets:
                errors.append("Write contract must include before_after_snippets")
            
            if len(self.targets) > 3 and not self.change_summary:
                errors.append("Write contract with >3 files must include change_summary")
            
            if not self.rollback_plan:
                errors.append("Write contract must include rollback_plan")
            
            if AcceptanceTest.DIFF_SANITY.value not in self.acceptance_tests:
                errors.append("Write contract must include DIFF_SANITY acceptance test")
        
        # Research intent requirements
        elif intent in {IntentType.RESEARCH_MOD_ISSUES, IntentType.RESEARCH_BUGREPORT}:
            # Read-only - no special requirements beyond intent_type
            if self.targets:
                errors.append("Research contract cannot have write targets")
        
        # Script intent requirements
        elif intent == IntentType.SCRIPT_WIP:
            if not self.script_hash:
                errors.append("Script contract must include script_hash")
        
        return len(errors) == 0, errors
    
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
    # CK3Lens-specific parameters
    intent_type: Optional[str] = None,
    targets: Optional[list[dict[str, str]]] = None,
    before_after_snippets: Optional[list[dict[str, Any]]] = None,
    change_summary: Optional[str] = None,
    rollback_plan: Optional[str] = None,
    acceptance_tests: Optional[list[str]] = None,
    script_hash: Optional[str] = None,
    declared_reads: Optional[list[str]] = None,
    declared_writes: Optional[list[str]] = None,
    findings_evidence: Optional[str] = None,
    ck3raven_source_access: bool = False,
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
        
        # CK3Lens-specific (required when agent_mode="ck3lens" and writing)
        intent_type: One of COMPATCH, BUGPATCH, RESEARCH_MOD_ISSUES, RESEARCH_BUGREPORT, SCRIPT_WIP
        targets: List of {mod_id, rel_path, operation} for write contracts
        before_after_snippets: List of {file, before, after} for change preview
        change_summary: Summary of changes (required if >3 files)
        rollback_plan: How to undo the changes
        acceptance_tests: List including DIFF_SANITY for writes
        script_hash: SHA256 of script (for SCRIPT_WIP)
        declared_reads: Files script will read
        declared_writes: Files script will write
        findings_evidence: Evidence for research intents
        ck3raven_source_access: Whether to allow reading ck3raven source
    
    Returns:
        The opened contract
    
    Raises:
        ValueError: If CK3Lens contract requirements not met
    """
    # Default capabilities
    if capabilities is None:
        capabilities = list(TIER_STANDARD)
    
    # Default paths based on domains and mode
    if allowed_paths is None:
        allowed_paths = []
        
        if agent_mode == "ck3lens":
            # CK3Lens paths are based on mod roots - handled at runtime
            # Just add WIP workspace for script intents
            if intent_type == IntentType.SCRIPT_WIP.value:
                allowed_paths.append("~/.ck3raven/wip/**")
        else:
            # ck3raven-dev domain paths
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
    
    # For CK3Lens write intents, default acceptance tests
    if agent_mode == "ck3lens" and intent_type in {IntentType.COMPATCH.value, IntentType.BUGPATCH.value}:
        if acceptance_tests is None:
            acceptance_tests = [AcceptanceTest.DIFF_SANITY.value, AcceptanceTest.VALIDATION.value]
        elif AcceptanceTest.DIFF_SANITY.value not in acceptance_tests:
            acceptance_tests = list(acceptance_tests) + [AcceptanceTest.DIFF_SANITY.value]
    
    contract = WorkContract(
        contract_id=WorkContract.generate_id(),
        intent=intent,
        canonical_domains=canonical_domains,
        allowed_paths=allowed_paths,
        capabilities=capabilities,
        expires_at=(datetime.now().replace(microsecond=0) + 
                   timedelta(hours=expires_hours)).isoformat(),
        agent_mode=agent_mode,
        notes=notes,
        # CK3Lens fields
        intent_type=intent_type,
        targets=targets or [],
        before_after_snippets=before_after_snippets or [],
        change_summary=change_summary,
        rollback_plan=rollback_plan,
        acceptance_tests=acceptance_tests or [],
        script_hash=script_hash,
        declared_reads=declared_reads or [],
        declared_writes=declared_writes or [],
        findings_evidence=findings_evidence,
        ck3raven_source_access=ck3raven_source_access,
    )
    
    # Validate CK3Lens requirements before saving
    if agent_mode == "ck3lens":
        valid, errors = contract.validate_ck3lens_requirements()
        if not valid:
            raise ValueError(f"CK3Lens contract validation failed: {errors}")
    
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


# =============================================================================
# CK3LENS CONTRACT HELPERS
# =============================================================================

def open_ck3lens_write_contract(
    intent: str,
    intent_type: str,
    targets: list[dict[str, str]],
    before_after_snippets: list[dict[str, Any]],
    rollback_plan: str,
    change_summary: Optional[str] = None,
    expires_hours: float = 4.0,
    notes: Optional[str] = None,
) -> WorkContract:
    """
    Open a CK3Lens write contract (COMPATCH or BUGPATCH).
    
    This is a convenience wrapper that sets all required fields for write contracts.
    
    Args:
        intent: Human-readable description of the work
        intent_type: "compatch" or "bugpatch"
        targets: List of {mod_id, rel_path, operation} for files to modify
        before_after_snippets: List of {file, before, after} showing changes
        rollback_plan: How to undo the changes
        change_summary: Summary of changes (required if >3 files)
        expires_hours: Hours until contract expires (default 4)
        notes: Optional notes
    
    Returns:
        The opened contract
    
    Raises:
        ValueError: If intent_type is not a write type
    """
    if intent_type not in {IntentType.COMPATCH.value, IntentType.BUGPATCH.value}:
        raise ValueError(f"intent_type must be 'compatch' or 'bugpatch', got: {intent_type}")
    
    # Determine domains from targets
    domains = ["active_local_mods"]  # Write contracts always touch local mods
    
    return open_contract(
        intent=intent,
        canonical_domains=domains,
        agent_mode="ck3lens",
        intent_type=intent_type,
        targets=targets,
        before_after_snippets=before_after_snippets,
        change_summary=change_summary,
        rollback_plan=rollback_plan,
        acceptance_tests=[AcceptanceTest.DIFF_SANITY.value, AcceptanceTest.VALIDATION.value],
        expires_hours=expires_hours,
        notes=notes,
    )


def open_ck3lens_research_contract(
    intent: str,
    intent_type: str = "research_mod_issues",
    findings_evidence: str = "",
    ck3raven_source_access: bool = False,
    expires_hours: float = 2.0,
    notes: Optional[str] = None,
) -> WorkContract:
    """
    Open a CK3Lens research contract (read-only).
    
    Args:
        intent: Human-readable description of the research
        intent_type: "research_mod_issues" or "research_bugreport"
        findings_evidence: Initial evidence or description
        ck3raven_source_access: Whether to allow reading ck3raven source
        expires_hours: Hours until contract expires (default 2)
        notes: Optional notes
    
    Returns:
        The opened contract
    """
    if intent_type not in {IntentType.RESEARCH_MOD_ISSUES.value, IntentType.RESEARCH_BUGREPORT.value}:
        raise ValueError(f"intent_type must be 'research_mod_issues' or 'research_bugreport', got: {intent_type}")
    
    domains = ["active_local_mods", "active_workshop_mods", "vanilla"]
    if ck3raven_source_access:
        # Note: ck3raven_source is read-only but we track it
        pass  # Handled via ck3raven_source_access flag
    
    return open_contract(
        intent=intent,
        canonical_domains=domains,
        agent_mode="ck3lens",
        intent_type=intent_type,
        findings_evidence=findings_evidence,
        ck3raven_source_access=ck3raven_source_access,
        expires_hours=expires_hours,
        notes=notes,
    )


def open_ck3lens_script_contract(
    intent: str,
    script_hash: str,
    declared_reads: list[str],
    declared_writes: list[str],
    expires_hours: float = 1.0,
    notes: Optional[str] = None,
) -> WorkContract:
    """
    Open a CK3Lens script contract (SCRIPT_WIP).
    
    Args:
        intent: Human-readable description of what the script does
        script_hash: SHA256 hash of the script content
        declared_reads: Files the script will read
        declared_writes: Files the script will write (WIP or local mods)
        expires_hours: Hours until contract expires (default 1)
        notes: Optional notes
    
    Returns:
        The opened contract
    """
    domains = ["wip_workspace"]
    
    # If writing to local mods, add that domain
    for w in declared_writes:
        if not w.startswith("wip:") and not w.startswith("~/.ck3raven/wip/"):
            domains.append("active_local_mods")
            break
    
    return open_contract(
        intent=intent,
        canonical_domains=list(set(domains)),
        agent_mode="ck3lens",
        intent_type=IntentType.SCRIPT_WIP.value,
        script_hash=script_hash,
        declared_reads=declared_reads,
        declared_writes=declared_writes,
        expires_hours=expires_hours,
        notes=notes,
    )


def bind_token_to_contract(contract_id: str, token_id: str) -> WorkContract:
    """
    Bind an approval token to a contract.
    
    Tokens bound to contracts are validated together.
    
    Args:
        contract_id: Contract to bind to
        token_id: Token to bind
    
    Returns:
        Updated contract
    """
    contract = WorkContract.load(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    if not contract.is_active():
        raise ValueError(f"Contract is not active: {contract.status}")
    
    if token_id not in contract.bound_tokens:
        contract.bound_tokens.append(token_id)
        contract.save()
    
    return contract


def update_contract_targets(
    contract_id: str,
    targets: list[dict[str, str]],
    before_after_snippets: Optional[list[dict[str, Any]]] = None,
) -> WorkContract:
    """
    Update the targets of an active contract.
    
    Use this to add/modify targets as work progresses.
    
    Args:
        contract_id: Contract to update
        targets: New list of targets
        before_after_snippets: Optional new snippets
    
    Returns:
        Updated contract
    """
    contract = WorkContract.load(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    if not contract.is_active():
        raise ValueError(f"Contract is not active: {contract.status}")
    
    contract.targets = targets
    if before_after_snippets is not None:
        contract.before_after_snippets = before_after_snippets
    
    # Re-validate if CK3Lens
    if contract.agent_mode == "ck3lens":
        valid, errors = contract.validate_ck3lens_requirements()
        if not valid:
            raise ValueError(f"Updated contract validation failed: {errors}")
    
    contract.save()
    return contract


def record_findings(contract_id: str, findings: str) -> WorkContract:
    """
    Record research findings for a research contract.
    
    Args:
        contract_id: Contract to update
        findings: Findings evidence to record
    
    Returns:
        Updated contract
    """
    contract = WorkContract.load(contract_id)
    if contract is None:
        raise ValueError(f"Contract not found: {contract_id}")
    
    if not contract.is_active():
        raise ValueError(f"Contract is not active: {contract.status}")
    
    if contract.intent_type not in {IntentType.RESEARCH_MOD_ISSUES.value, IntentType.RESEARCH_BUGREPORT.value}:
        raise ValueError(f"record_findings only for research contracts, not {contract.intent_type}")
    
    contract.findings_evidence = findings
    contract.save()
    return contract


def get_active_ck3lens_contract() -> Optional[WorkContract]:
    """
    Get the currently active CK3Lens contract.
    
    Returns:
        Active ck3lens contract or None
    """
    contract = get_active_contract()
    if contract and contract.agent_mode == "ck3lens":
        return contract
    return None


def validate_target_in_contract(
    mod_id: str,
    rel_path: str,
    contract: WorkContract,
) -> tuple[bool, str]:
    """
    Check if a target is allowed by the CK3Lens contract.
    
    Args:
        mod_id: Mod identifier
        rel_path: Relative path within mod
        contract: Active contract
    
    Returns:
        (allowed: bool, reason: str)
    """
    if not contract.is_active():
        return False, "Contract is not active"
    
    if contract.agent_mode != "ck3lens":
        return True, "Not a ck3lens contract"
    
    # Check if this target is in the declared targets
    for target in contract.targets:
        if target.get("mod_id") == mod_id and target.get("rel_path") == rel_path:
            return True, "Target is declared in contract"
    
    # For research contracts, no targets needed
    if contract.intent_type in {IntentType.RESEARCH_MOD_ISSUES.value, IntentType.RESEARCH_BUGREPORT.value}:
        return True, "Research contract - read only"
    
    return False, f"Target {mod_id}/{rel_path} not declared in contract"
