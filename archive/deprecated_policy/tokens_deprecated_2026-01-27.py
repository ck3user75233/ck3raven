"""
DEPRECATED Token System - Stub for Backward Compatibility

This module has been deprecated in favor of the canonical token system.

CANONICAL TOKEN SYSTEM: tools/compliance/tokens.py
  - NST (New Symbol Token): Declares intentionally new identifiers
  - LXE (Lint Exception Token): Grants temporary lint rule exceptions

This stub maintains API compatibility during transition. All functions
return success to allow existing code to continue working while the
codebase migrates away from the deprecated token model.

DEPRECATED TOKEN TYPES (no longer used):
  - FS_DELETE_CODE, FS_WRITE_OUTSIDE_CONTRACT
  - CMD_RUN_DESTRUCTIVE, CMD_RUN_ARBITRARY
  - GIT_PUSH, GIT_REWRITE_HISTORY, GIT_FORCE_PUSH
  - DB_SCHEMA_MIGRATE, DB_DELETE_DATA
  - BYPASS_CONTRACT, BYPASS_POLICY
  - DELETE_MOD_FILE, INACTIVE_MOD_ACCESS, SCRIPT_EXECUTE, GIT_PUSH_MOD

NEW MODEL:
  - File deletion: Requires `confirm=True` parameter in tool call
  - Git push: Allowed with active contract (no token needed)
  - Dangerous commands: Evaluated by enforcement.py, may require confirmation

Migration:
  Remove token validation from calling code. Use enforcement.py directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


# ============================================================================
# DEPRECATED - Token types preserved for backward compatibility only
# ============================================================================

TOKEN_TYPES: dict = {}  # Empty - no deprecated tokens active

CK3LENS_TOKEN_TYPES: dict = {}  # Empty - no deprecated tokens active


# ============================================================================
# STUB DATA STRUCTURE
# ============================================================================

@dataclass
class ApprovalToken:
    """
    DEPRECATED - Stub for backward compatibility.
    
    Use tools/compliance/tokens.py for canonical NST/LXE tokens.
    """
    token_id: str = ""
    token_type: str = ""
    capability: str = ""
    path_patterns: list[str] = field(default_factory=list)
    command_patterns: list[str] = field(default_factory=list)
    script_hash: Optional[str] = None
    mod_name: Optional[str] = None
    user_prompt_evidence: Optional[str] = None
    issued_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: str = ""
    consumed: bool = False
    consumed_at: Optional[str] = None
    reason: str = ""
    issued_by: str = "system"
    contract_id: Optional[str] = None
    signature: str = ""
    
    def is_expired(self) -> bool:
        """Always returns False - deprecated tokens don't expire."""
        return False
    
    def is_valid(self) -> bool:
        """Always returns True - deprecated system accepts all."""
        return True
    
    def to_dict(self) -> dict:
        return {"deprecated": True, "token_id": self.token_id}
    
    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalToken":
        return cls(token_id=data.get("token_id", ""))
    
    def save(self) -> Path:
        """No-op - deprecated tokens are not persisted."""
        return Path.home() / ".ck3raven" / "approvals" / "deprecated.json"
    
    @classmethod
    def load(cls, token_id: str) -> Optional["ApprovalToken"]:
        """Returns a valid stub token for any ID."""
        return cls(token_id=token_id)


# ============================================================================
# STUB FUNCTIONS - All return success for backward compatibility
# ============================================================================

def issue_token(
    token_type: str,
    capability: str,
    reason: str,
    path_patterns: Optional[list[str]] = None,
    command_patterns: Optional[list[str]] = None,
    contract_id: Optional[str] = None,
    issued_by: str = "system",
    ttl_minutes: Optional[int] = None,
) -> ApprovalToken:
    """DEPRECATED - Returns stub token. Use tools/compliance/tokens.py for NST/LXE."""
    return ApprovalToken(
        token_id=f"deprecated-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        token_type=token_type,
        capability=capability,
        reason=reason,
    )


def consume_token(token_id: str) -> bool:
    """DEPRECATED - Always returns True."""
    return True


def validate_token(
    token_id: str,
    required_capability: str,
    path: Optional[str] = None,
    command: Optional[str] = None,
) -> tuple[bool, str]:
    """
    DEPRECATED - Always returns (True, "Deprecated token system - always valid").
    
    The deprecated token system no longer validates. Operations that previously
    required tokens now use either:
    - confirm=True parameter (for destructive operations)
    - Active contract scope (for git push, file writes)
    
    Use tools/compliance/tokens.py for canonical NST/LXE validation.
    """
    return True, "Deprecated token system - validation bypassed"


def list_tokens(
    include_expired: bool = False,
    include_consumed: bool = False,
) -> list[ApprovalToken]:
    """DEPRECATED - Returns empty list."""
    return []


def cleanup_expired_tokens() -> int:
    """DEPRECATED - No-op, returns 0."""
    return 0


def revoke_token(token_id: str) -> bool:
    """DEPRECATED - Always returns True."""
    return True


# ============================================================================
# DEPRECATED CK3Lens-specific helpers - All return stubs
# ============================================================================

def issue_delete_token(
    mod_name: str,
    file_path: str,
    user_prompt_evidence: str,
    reason: str,
    contract_id: Optional[str] = None,
) -> ApprovalToken:
    """DEPRECATED - Use confirm=True parameter instead."""
    return ApprovalToken(token_id="deprecated-delete", token_type="DELETE_MOD_FILE")


def issue_inactive_mod_token(
    mod_name: str,
    user_prompt_evidence: str,
    reason: str,
    path_patterns: Optional[list[str]] = None,
) -> ApprovalToken:
    """DEPRECATED - Inactive mod access now allowed without token."""
    return ApprovalToken(token_id="deprecated-inactive", token_type="INACTIVE_MOD_ACCESS")


def issue_script_execute_token(
    script_hash: str,
    script_path: str,
    reason: str,
    contract_id: Optional[str] = None,
) -> ApprovalToken:
    """DEPRECATED - Script execution allowed in WIP workspace without token."""
    return ApprovalToken(token_id="deprecated-script", token_type="SCRIPT_EXECUTE")


def validate_script_token(
    token_id: str,
    current_hash: str,
) -> tuple[bool, str]:
    """DEPRECATED - Always returns valid."""
    return True, "Deprecated - script tokens no longer required"


def issue_git_push_mod_token(
    mod_name: str,
    user_prompt_evidence: str,
    reason: str,
) -> ApprovalToken:
    """DEPRECATED - Git push allowed with active contract."""
    return ApprovalToken(token_id="deprecated-push", token_type="GIT_PUSH_MOD")


def check_user_prompt_required(token_type: str) -> bool:
    """DEPRECATED - Always returns False (no prompts required via token system)."""
    return False


def check_script_hash_required(token_type: str) -> bool:
    """DEPRECATED - Always returns False."""
    return False
