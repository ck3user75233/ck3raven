"""
Approval Tokens for CLI Wrapping

HMAC-SHA256 signed tokens granting specific capabilities for risky operations.
Tokens are time-limited and path-constrained.

Token Lifecycle:
1. Agent requests approval for risky operation
2. Approver (human or system) issues signed token
3. Agent presents token to CLW policy engine
4. Policy engine validates signature, expiry, and scope
5. Token is consumed or expires

Storage:
- Tokens stored in ~/.ck3raven/approvals/
- Expired tokens cleaned up automatically
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Optional


# ============================================================================
# Configuration
# ============================================================================

def _get_approvals_dir() -> Path:
    """Get the approvals directory, creating if needed."""
    path = Path.home() / ".ck3raven" / "approvals"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_secret_key() -> bytes:
    """
    Get the HMAC signing key.
    
    Stored in ~/.ck3raven/token_secret.key
    Generated automatically on first use.
    """
    key_path = Path.home() / ".ck3raven" / "token_secret.key"
    
    if key_path.exists():
        return key_path.read_bytes()
    
    # Generate new key
    key = secrets.token_bytes(32)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(key)
    
    # Restrict permissions (best effort on Windows)
    try:
        os.chmod(key_path, 0o600)
    except Exception:
        pass
    
    return key


# Token types with risk levels
TOKEN_TYPES = {
    # Filesystem tokens
    "FS_DELETE_CODE": {"risk": "high", "ttl_minutes": 30},
    "FS_WRITE_OUTSIDE_CONTRACT": {"risk": "high", "ttl_minutes": 60},
    
    # Command tokens
    "CMD_RUN_DESTRUCTIVE": {"risk": "high", "ttl_minutes": 15},
    "CMD_RUN_ARBITRARY": {"risk": "critical", "ttl_minutes": 10},
    
    # Git tokens
    "GIT_PUSH": {"risk": "medium", "ttl_minutes": 60},
    "GIT_REWRITE_HISTORY": {"risk": "critical", "ttl_minutes": 15},
    "GIT_FORCE_PUSH": {"risk": "critical", "ttl_minutes": 10},
    
    # DB tokens
    "DB_SCHEMA_MIGRATE": {"risk": "high", "ttl_minutes": 30},
    "DB_DELETE_DATA": {"risk": "critical", "ttl_minutes": 15},
    
    # Emergency bypass
    "BYPASS_CONTRACT": {"risk": "critical", "ttl_minutes": 5},
    "BYPASS_POLICY": {"risk": "critical", "ttl_minutes": 5},
}


# ============================================================================
# CK3Lens Token Types
# ============================================================================

# CK3Lens-specific tokens (from types.py CK3LensTokenType enum)
CK3LENS_TOKEN_TYPES = {
    # Delete operations require explicit user approval
    "DELETE_MOD_FILE": {"risk": "high", "ttl_minutes": 30, "requires_user_prompt": True},
    
    # Access to inactive mods (not in current playset)
    "INACTIVE_MOD_ACCESS": {"risk": "medium", "ttl_minutes": 60, "requires_user_prompt": True},
    
    # Script execution in WIP workspace
    "SCRIPT_EXECUTE": {"risk": "high", "ttl_minutes": 15, "requires_script_hash": True},
    
    # Git push for live mods
    "GIT_PUSH_MOD": {"risk": "medium", "ttl_minutes": 60, "requires_user_prompt": True},
}

# Merge into main TOKEN_TYPES for unified lookup
TOKEN_TYPES.update(CK3LENS_TOKEN_TYPES)


# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class ApprovalToken:
    """
    HMAC-signed approval token for risky operations.
    """
    # Identity
    token_id: str
    
    # What this token authorizes
    token_type: str  # From TOKEN_TYPES
    capability: str  # Specific capability granted
    
    # Scope constraints
    path_patterns: list[str] = field(default_factory=list)  # Allowed paths
    command_patterns: list[str] = field(default_factory=list)  # Allowed commands
    
    # CK3Lens-specific constraints
    script_hash: Optional[str] = None  # SHA256 hash of approved script content
    mod_name: Optional[str] = None  # Target mod name
    user_prompt_evidence: Optional[str] = None  # Evidence user explicitly requested this
    
    # Lifecycle
    issued_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: str = ""  # Set based on token type
    consumed: bool = False
    consumed_at: Optional[str] = None
    
    # Metadata
    reason: str = ""  # Why token was issued
    issued_by: str = "system"  # Who issued it
    contract_id: Optional[str] = None  # Associated work contract
    
    # Signature (computed)
    signature: str = ""
    
    def __post_init__(self):
        # Set expiry based on token type if not set
        if not self.expires_at:
            ttl_minutes = TOKEN_TYPES.get(self.token_type, {}).get("ttl_minutes", 60)
            expires = datetime.now() + timedelta(minutes=ttl_minutes)
            self.expires_at = expires.isoformat()
    
    @classmethod
    def generate_id(cls) -> str:
        """Generate a unique token ID."""
        return f"tok-{secrets.token_hex(8)}"
    
    def is_expired(self) -> bool:
        """Check if token has expired."""
        if not self.expires_at:
            return True
        expires = datetime.fromisoformat(self.expires_at)
        return datetime.now() > expires
    
    def is_valid(self) -> bool:
        """Check if token is valid (not expired, not consumed, signature OK)."""
        if self.is_expired():
            return False
        if self.consumed:
            return False
        return verify_signature(self)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ApprovalToken":
        """Create from dictionary."""
        return cls(**data)
    
    def signing_payload(self) -> str:
        """Get the payload to sign (excludes signature field)."""
        data = self.to_dict()
        data.pop("signature", None)
        return json.dumps(data, sort_keys=True)
    
    def save(self) -> Path:
        """Save token to disk."""
        approvals_dir = _get_approvals_dir()
        path = approvals_dir / f"{self.token_id}.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
    
    @classmethod
    def load(cls, token_id: str) -> Optional["ApprovalToken"]:
        """Load token by ID from disk."""
        approvals_dir = _get_approvals_dir()
        path = approvals_dir / f"{token_id}.json"
        
        if not path.exists():
            return None
        
        try:
            data = json.loads(path.read_text())
            return cls.from_dict(data)
        except Exception:
            return None


# ============================================================================
# Signing Functions
# ============================================================================

def sign_token(token: ApprovalToken) -> str:
    """
    Sign a token with HMAC-SHA256.
    
    Args:
        token: Token to sign
    
    Returns:
        Base64-encoded signature
    """
    key = _get_secret_key()
    payload = token.signing_payload().encode("utf-8")
    
    sig = hmac.new(key, payload, hashlib.sha256).digest()
    return base64.b64encode(sig).decode("ascii")


def verify_signature(token: ApprovalToken) -> bool:
    """
    Verify a token's signature.
    
    Args:
        token: Token to verify
    
    Returns:
        True if signature is valid
    """
    if not token.signature:
        return False
    
    expected = sign_token(token)
    return hmac.compare_digest(token.signature, expected)


# ============================================================================
# Token Management
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
    """
    Issue a new approval token.
    
    Args:
        token_type: Type from TOKEN_TYPES
        capability: Specific capability granted
        reason: Why this token is being issued
        path_patterns: Allowed path patterns
        command_patterns: Allowed command patterns
        contract_id: Associated work contract
        issued_by: Who is issuing the token
        ttl_minutes: Override default TTL
    
    Returns:
        Signed token
    """
    if token_type not in TOKEN_TYPES:
        raise ValueError(f"Unknown token type: {token_type}")
    
    # Create token
    token = ApprovalToken(
        token_id=ApprovalToken.generate_id(),
        token_type=token_type,
        capability=capability,
        path_patterns=path_patterns or [],
        command_patterns=command_patterns or [],
        reason=reason,
        issued_by=issued_by,
        contract_id=contract_id,
    )
    
    # Override TTL if specified
    if ttl_minutes:
        token.expires_at = (datetime.now() + timedelta(minutes=ttl_minutes)).isoformat()
    
    # Sign
    token.signature = sign_token(token)
    
    # Save
    token.save()
    
    return token


def consume_token(token_id: str) -> bool:
    """
    Consume (use) a token, marking it as consumed.
    
    Args:
        token_id: Token to consume
    
    Returns:
        True if token was valid and consumed
    """
    token = ApprovalToken.load(token_id)
    
    if not token:
        return False
    
    if not token.is_valid():
        return False
    
    token.consumed = True
    token.consumed_at = datetime.now().isoformat()
    token.save()
    
    return True


def validate_token(
    token_id: str,
    required_capability: str,
    path: Optional[str] = None,
    command: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Validate a token for a specific operation.
    
    Args:
        token_id: Token to validate
        required_capability: Capability needed
        path: Path to check against path_patterns
        command: Command to check against command_patterns
    
    Returns:
        (is_valid, reason) tuple
    """
    token = ApprovalToken.load(token_id)
    
    if not token:
        return False, "Token not found"
    
    if token.is_expired():
        return False, "Token has expired"
    
    if token.consumed:
        return False, "Token has already been consumed"
    
    if not verify_signature(token):
        return False, "Token signature is invalid"
    
    if token.capability != required_capability:
        return False, f"Token grants '{token.capability}', not '{required_capability}'"
    
    # Check path constraints
    if path and token.path_patterns:
        import fnmatch
        if not any(fnmatch.fnmatch(path, p) for p in token.path_patterns):
            return False, f"Path '{path}' not allowed by token"
    
    # Check command constraints
    if command and token.command_patterns:
        import fnmatch
        if not any(fnmatch.fnmatch(command, p) for p in token.command_patterns):
            return False, f"Command not allowed by token"
    
    return True, "Token valid"


def list_tokens(
    include_expired: bool = False,
    include_consumed: bool = False,
) -> list[ApprovalToken]:
    """
    List tokens with optional filters.
    
    Args:
        include_expired: Include expired tokens
        include_consumed: Include consumed tokens
    
    Returns:
        List of matching tokens
    """
    tokens = []
    approvals_dir = _get_approvals_dir()
    
    for path in approvals_dir.glob("tok-*.json"):
        try:
            token = ApprovalToken.from_dict(json.loads(path.read_text()))
            
            if not include_expired and token.is_expired():
                continue
            if not include_consumed and token.consumed:
                continue
            
            tokens.append(token)
        except Exception:
            continue
    
    # Sort by issued_at descending
    tokens.sort(key=lambda t: t.issued_at, reverse=True)
    return tokens


def cleanup_expired_tokens() -> int:
    """
    Remove expired tokens from disk.
    
    Returns:
        Number of tokens removed
    """
    removed = 0
    approvals_dir = _get_approvals_dir()
    
    for path in approvals_dir.glob("tok-*.json"):
        try:
            token = ApprovalToken.from_dict(json.loads(path.read_text()))
            
            # Remove if expired for more than 24 hours
            if token.is_expired():
                expires = datetime.fromisoformat(token.expires_at)
                if datetime.now() - expires > timedelta(hours=24):
                    path.unlink()
                    removed += 1
        except Exception:
            continue
    
    return removed


def revoke_token(token_id: str) -> bool:
    """
    Revoke a token by deleting it.
    
    Args:
        token_id: Token to revoke
    
    Returns:
        True if token was found and deleted
    """
    approvals_dir = _get_approvals_dir()
    path = approvals_dir / f"{token_id}.json"
    
    if path.exists():
        path.unlink()
        return True
    
    return False


# ============================================================================
# CK3Lens Token Helpers
# ============================================================================

def issue_delete_token(
    mod_name: str,
    file_path: str,
    user_prompt_evidence: str,
    reason: str,
    contract_id: Optional[str] = None,
) -> ApprovalToken:
    """
    Issue a token for deleting a mod file.
    
    Requires user prompt evidence showing explicit request to delete.
    
    Args:
        mod_name: Target mod name
        file_path: Relative path of file to delete
        user_prompt_evidence: Quote from user message requesting deletion
        reason: Why this deletion is happening
        contract_id: Associated work contract
    
    Returns:
        Signed token
    """
    if not user_prompt_evidence:
        raise ValueError("DELETE_MOD_FILE tokens require user_prompt_evidence")
    
    token = ApprovalToken(
        token_id=ApprovalToken.generate_id(),
        token_type="DELETE_MOD_FILE",
        capability=f"delete:{mod_name}:{file_path}",
        path_patterns=[file_path],
        mod_name=mod_name,
        user_prompt_evidence=user_prompt_evidence,
        reason=reason,
        contract_id=contract_id,
    )
    
    token.signature = sign_token(token)
    token.save()
    
    return token


def issue_inactive_mod_token(
    mod_name: str,
    user_prompt_evidence: str,
    reason: str,
    path_patterns: Optional[list[str]] = None,
) -> ApprovalToken:
    """
    Issue a token for accessing an inactive mod (not in playset).
    
    Requires user prompt evidence showing explicit request to access.
    
    Args:
        mod_name: Name of the inactive mod
        user_prompt_evidence: Quote from user message requesting access
        reason: Why this access is needed
        path_patterns: Optional path restrictions within the mod
    
    Returns:
        Signed token
    """
    if not user_prompt_evidence:
        raise ValueError("INACTIVE_MOD_ACCESS tokens require user_prompt_evidence")
    
    token = ApprovalToken(
        token_id=ApprovalToken.generate_id(),
        token_type="INACTIVE_MOD_ACCESS",
        capability=f"read:{mod_name}",
        path_patterns=path_patterns or [],
        mod_name=mod_name,
        user_prompt_evidence=user_prompt_evidence,
        reason=reason,
    )
    
    token.signature = sign_token(token)
    token.save()
    
    return token


def issue_script_execute_token(
    script_hash: str,
    script_path: str,
    reason: str,
    contract_id: Optional[str] = None,
) -> ApprovalToken:
    """
    Issue a token for executing a script in the WIP workspace.
    
    Token is bound to specific script hash - content changes invalidate it.
    
    Args:
        script_hash: SHA256 hash of script content
        script_path: Path to script in WIP workspace
        reason: Why this script is being executed
        contract_id: Associated work contract
    
    Returns:
        Signed token
    """
    if not script_hash:
        raise ValueError("SCRIPT_EXECUTE tokens require script_hash")
    
    token = ApprovalToken(
        token_id=ApprovalToken.generate_id(),
        token_type="SCRIPT_EXECUTE",
        capability=f"execute:{script_path}",
        path_patterns=[script_path],
        script_hash=script_hash,
        reason=reason,
        contract_id=contract_id,
    )
    
    token.signature = sign_token(token)
    token.save()
    
    return token


def validate_script_token(
    token_id: str,
    current_hash: str,
) -> tuple[bool, str]:
    """
    Validate a script execution token against current script content.
    
    Args:
        token_id: Token to validate
        current_hash: Current SHA256 hash of script content
    
    Returns:
        (is_valid, reason) tuple
    """
    token = ApprovalToken.load(token_id)
    
    if not token:
        return False, "Token not found"
    
    if token.token_type != "SCRIPT_EXECUTE":
        return False, f"Token type is {token.token_type}, not SCRIPT_EXECUTE"
    
    if token.is_expired():
        return False, "Token has expired"
    
    if token.consumed:
        return False, "Token has already been consumed"
    
    if not verify_signature(token):
        return False, "Token signature is invalid"
    
    if not token.script_hash:
        return False, "Token has no script_hash bound"
    
    if token.script_hash != current_hash:
        return False, "Script content has changed since token was issued"
    
    return True, "Token valid"


def issue_git_push_mod_token(
    mod_name: str,
    user_prompt_evidence: str,
    reason: str,
) -> ApprovalToken:
    """
    Issue a token for pushing changes to a mod's git remote.
    
    Args:
        mod_name: Target mod name
        user_prompt_evidence: Quote from user message requesting push
        reason: Why this push is happening
    
    Returns:
        Signed token
    """
    if not user_prompt_evidence:
        raise ValueError("GIT_PUSH_MOD tokens require user_prompt_evidence")
    
    token = ApprovalToken(
        token_id=ApprovalToken.generate_id(),
        token_type="GIT_PUSH_MOD",
        capability=f"git_push:{mod_name}",
        mod_name=mod_name,
        user_prompt_evidence=user_prompt_evidence,
        reason=reason,
    )
    
    token.signature = sign_token(token)
    token.save()
    
    return token


def check_user_prompt_required(token_type: str) -> bool:
    """
    Check if a token type requires user prompt evidence.
    
    Args:
        token_type: Token type to check
    
    Returns:
        True if user prompt evidence is required
    """
    type_info = TOKEN_TYPES.get(token_type, {})
    return type_info.get("requires_user_prompt", False)


def check_script_hash_required(token_type: str) -> bool:
    """
    Check if a token type requires script hash binding.
    
    Args:
        token_type: Token type to check
    
    Returns:
        True if script hash is required
    """
    type_info = TOKEN_TYPES.get(token_type, {})
    return type_info.get("requires_script_hash", False)
