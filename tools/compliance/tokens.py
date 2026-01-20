"""
Token Management for Phase 1.5C - NST and LXE Tokens

This module implements the token lifecycle for the Canonical Contract System:
- NST (New Symbol Token): Declares intentionally new identifiers
- LXE (Lint Exception Token): Grants temporary lint rule exceptions

Token Lifecycle:
1. Agent proposes token → artifacts/tokens_proposed/<id>.token.json
2. Human approves → moves to policy/tokens/<id>.token.json
3. Token validated at contract close
4. Token expires after TTL

Location: tools/compliance/tokens.py
Authority: CANONICAL CONTRACT SYSTEM Phase 1.5C
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Any


# =============================================================================
# TOKEN TYPES (Unified - NOT mode-specific)
# =============================================================================

class TokenType(str, Enum):
    """Token types for exception handling."""
    NST = "NST"  # New Symbol Token
    LXE = "LXE"  # Lint Exception Token


class TokenStatus(str, Enum):
    """Token lifecycle status."""
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


# Default TTLs in hours
TOKEN_TTLS = {
    TokenType.NST: 24,  # 24 hours
    TokenType.LXE: 8,   # 8 hours (work session)
}


# =============================================================================
# TOKEN SCHEMA
# =============================================================================

@dataclass
class TokenScope:
    """Scope definition for a token."""
    root_category: str  # ROOT_REPO, ROOT_USER_DOCS, etc.
    target_paths: list[str] = field(default_factory=list)
    symbol_names: list[str] = field(default_factory=list)  # For NST
    rule_codes: list[str] = field(default_factory=list)    # For LXE
    max_violations: Optional[int] = None  # For LXE - cap on violations covered
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "root_category": self.root_category,
            "target_paths": self.target_paths,
            "symbol_names": self.symbol_names,
            "rule_codes": self.rule_codes,
            "max_violations": self.max_violations,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TokenScope":
        return cls(
            root_category=data.get("root_category", ""),
            target_paths=data.get("target_paths", []),
            symbol_names=data.get("symbol_names", []),
            rule_codes=data.get("rule_codes", []),
            max_violations=data.get("max_violations"),
        )


@dataclass
class Token:
    """A signed exception token."""
    schema_version: str = "v1"
    token_type: TokenType = TokenType.NST
    token_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    contract_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: str = ""
    status: TokenStatus = TokenStatus.PROPOSED
    justification: str = ""
    scope: TokenScope = field(default_factory=lambda: TokenScope(root_category=""))
    signature: str = ""
    
    def __post_init__(self):
        if not self.expires_at:
            ttl_hours = TOKEN_TTLS.get(self.token_type, 8)
            expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
            self.expires_at = expires.isoformat()
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "token_type": self.token_type.value if isinstance(self.token_type, TokenType) else self.token_type,
            "token_id": self.token_id,
            "contract_id": self.contract_id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status.value if isinstance(self.status, TokenStatus) else self.status,
            "justification": self.justification,
            "scope": self.scope.to_dict() if isinstance(self.scope, TokenScope) else self.scope,
            "signature": self.signature,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Token":
        scope_data = data.get("scope", {})
        scope = TokenScope.from_dict(scope_data) if isinstance(scope_data, dict) else scope_data
        
        return cls(
            schema_version=data.get("schema_version", "v1"),
            token_type=TokenType(data.get("token_type", "NST")),
            token_id=data.get("token_id", ""),
            contract_id=data.get("contract_id", ""),
            created_at=data.get("created_at", ""),
            expires_at=data.get("expires_at", ""),
            status=TokenStatus(data.get("status", "proposed")),
            justification=data.get("justification", ""),
            scope=scope,
            signature=data.get("signature", ""),
        )
    
    def is_expired(self) -> bool:
        """Check if token has expired."""
        try:
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > expires
        except (ValueError, AttributeError):
            return True  # Invalid date = expired
    
    def canonical_json(self) -> str:
        """Get canonical JSON for signing (excludes signature field)."""
        data = self.to_dict()
        data.pop("signature", None)
        return json.dumps(data, sort_keys=True, separators=(",", ":"))


# =============================================================================
# SIGNING
# =============================================================================

def _get_signing_key() -> bytes:
    """
    Get the signing key for token signatures.
    
    In production, this should be a proper secret.
    For now, we use a deterministic key from environment or default.
    """
    key = os.environ.get("CK3RAVEN_TOKEN_KEY", "ck3raven-phase-1.5-token-signing-key")
    return key.encode("utf-8")


def sign_token(token: Token) -> str:
    """Generate HMAC-SHA256 signature for a token."""
    canonical = token.canonical_json()
    signature = hmac.new(
        _get_signing_key(),
        canonical.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


def verify_token_signature(token: Token) -> bool:
    """Verify token signature is valid."""
    if not token.signature:
        return False
    expected = sign_token(token)
    return hmac.compare_digest(token.signature, expected)


# =============================================================================
# TOKEN PATHS
# =============================================================================

def _get_repo_root() -> Path:
    """Get repository root."""
    return Path(__file__).parents[2]  # tools/compliance/tokens.py -> repo root


def get_proposed_tokens_dir() -> Path:
    """Get directory for proposed tokens."""
    return _get_repo_root() / "artifacts" / "tokens_proposed"


def get_approved_tokens_dir() -> Path:
    """Get directory for approved tokens."""
    return _get_repo_root() / "policy" / "tokens"


def get_token_path(token_id: str, status: TokenStatus = TokenStatus.PROPOSED) -> Path:
    """Get path to token file."""
    if status == TokenStatus.APPROVED:
        return get_approved_tokens_dir() / f"{token_id}.token.json"
    else:
        return get_proposed_tokens_dir() / f"{token_id}.token.json"


# =============================================================================
# TOKEN CREATION
# =============================================================================

def propose_nst(
    contract_id: str,
    root_category: str,
    symbol_names: list[str],
    target_paths: list[str],
    justification: str,
    ttl_hours: Optional[int] = None,
) -> Token:
    """
    Propose a New Symbol Token (NST).
    
    Args:
        contract_id: Parent contract ID
        root_category: Geographic scope (ROOT_REPO, ROOT_USER_DOCS, etc.)
        symbol_names: List of new symbol names being declared
        target_paths: Paths where symbols will be defined
        justification: Human-readable reason for new symbols
        ttl_hours: Optional override for TTL
    
    Returns:
        Token object (not yet saved)
    """
    scope = TokenScope(
        root_category=root_category,
        target_paths=target_paths,
        symbol_names=symbol_names,
    )
    
    token = Token(
        token_type=TokenType.NST,
        contract_id=contract_id,
        justification=justification,
        scope=scope,
        status=TokenStatus.PROPOSED,
    )
    
    if ttl_hours:
        expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        token.expires_at = expires.isoformat()
    
    token.signature = sign_token(token)
    return token


def propose_lxe(
    contract_id: str,
    root_category: str,
    target_paths: list[str],
    rule_codes: list[str],
    justification: str,
    max_violations: Optional[int] = None,
    ttl_hours: Optional[int] = None,
) -> Token:
    """
    Propose a Lint Exception Token (LXE).
    
    Args:
        contract_id: Parent contract ID
        root_category: Geographic scope
        target_paths: Paths where exceptions apply
        rule_codes: Lint rule codes to exempt (e.g., ["ORACLE-01", "TRUTH-01"])
        justification: Reason exceptions are needed
        max_violations: Optional cap on number of violations covered
        ttl_hours: Optional override for TTL
    
    Returns:
        Token object (not yet saved)
    """
    scope = TokenScope(
        root_category=root_category,
        target_paths=target_paths,
        rule_codes=rule_codes,
        max_violations=max_violations,
    )
    
    token = Token(
        token_type=TokenType.LXE,
        contract_id=contract_id,
        justification=justification,
        scope=scope,
        status=TokenStatus.PROPOSED,
    )
    
    if ttl_hours:
        expires = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        token.expires_at = expires.isoformat()
    
    token.signature = sign_token(token)
    return token


def save_proposed_token(token: Token) -> Path:
    """
    Save a proposed token to artifacts/tokens_proposed/.
    
    Returns:
        Path to saved token file
    """
    proposed_dir = get_proposed_tokens_dir()
    proposed_dir.mkdir(parents=True, exist_ok=True)
    
    path = proposed_dir / f"{token.token_id}.token.json"
    path.write_text(json.dumps(token.to_dict(), indent=2))
    return path


# =============================================================================
# TOKEN VALIDATION
# =============================================================================

@dataclass
class TokenValidationResult:
    """Result of token validation."""
    valid: bool
    token: Optional[Token] = None
    errors: list[str] = field(default_factory=list)


def load_token(token_id: str) -> Optional[Token]:
    """Load a token by ID, checking both proposed and approved locations."""
    # Check approved first
    approved_path = get_approved_tokens_dir() / f"{token_id}.token.json"
    if approved_path.exists():
        data = json.loads(approved_path.read_text())
        return Token.from_dict(data)
    
    # Check proposed
    proposed_path = get_proposed_tokens_dir() / f"{token_id}.token.json"
    if proposed_path.exists():
        data = json.loads(proposed_path.read_text())
        return Token.from_dict(data)
    
    return None


def validate_token(token_or_id: Token | str) -> tuple[bool, str | None]:
    """
    Validate a token for contract closure.
    
    Checks:
    1. Signature is valid
    2. Status is APPROVED (not proposed/rejected)
    3. Not expired
    
    Args:
        token_or_id: Either a Token object or token ID string
    
    Returns:
        (is_valid, error_message) - error_message is None if valid
    """
    # Handle both Token objects and string IDs
    if isinstance(token_or_id, str):
        token = load_token(token_or_id)
        if not token:
            return False, f"Token not found: {token_or_id}"
    else:
        token = token_or_id
    
    # Check signature
    if not verify_token_signature(token):
        return False, "Token signature invalid - token may have been tampered with"
    
    # Check status
    if token.status != TokenStatus.APPROVED:
        return False, f"Token status is {token.status.value}, must be 'approved'"
    
    # Check expiration
    if token.is_expired():
        return False, f"Token expired at {token.expires_at}"
    
    return True, None


def validate_token_detailed(token_id: str) -> TokenValidationResult:
    """
    Detailed validation of a token for CLI display.
    
    Returns a TokenValidationResult with full details.
    """
    errors = []
    
    token = load_token(token_id)
    if not token:
        return TokenValidationResult(
            valid=False,
            errors=[f"Token not found: {token_id}"]
        )
    
    # Check signature
    if not verify_token_signature(token):
        errors.append("Token signature invalid - token may have been tampered with")
    
    # Check status
    if token.status != TokenStatus.APPROVED:
        errors.append(f"Token status is {token.status.value}, must be 'approved'")
    
    # Check expiration
    if token.is_expired():
        errors.append(f"Token expired at {token.expires_at}")
    
    return TokenValidationResult(
        valid=len(errors) == 0,
        token=token,
        errors=errors,
    )


def check_nst_coverage(
    tokens: list[Token],
    actual_new_symbols: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Verify NST tokens cover all new symbols in the diff.
    
    Args:
        tokens: List of NST tokens to check
        actual_new_symbols: List of {\"name\": \"...\", \"symbol_type\": \"...\", \"scope\": \"...\"}
    
    Returns:
        {
            \"fully_covered\": bool,
            \"covered_count\": int,
            \"uncovered_symbols\": list[str],
        }
    """
    # Gather all declared symbols from all tokens
    declared_symbols = set()
    for token in tokens:
        if token.token_type == TokenType.NST:
            declared_symbols.update(token.scope.symbol_names)
    
    # Get actual symbol names
    actual_names = {s.get("name", "") for s in actual_new_symbols}
    
    uncovered = actual_names - declared_symbols
    covered = actual_names - uncovered
    
    return {
        "fully_covered": len(uncovered) == 0,
        "covered_count": len(covered),
        "uncovered_symbols": list(uncovered),
    }


def check_lxe_coverage(
    tokens: list[Token],
    lint_violations: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Verify LXE tokens cover lint violations being exempted.
    
    Args:
        tokens: List of LXE tokens to check
        lint_violations: List of {\"rule_code\": \"...\", \"path\": \"...\", \"message\": \"...\"}
    
    Returns:
        {
            \"fully_covered\": bool,
            \"covered_count\": int,
            \"uncovered_violations\": list[str],
        }
    """
    # Gather all declared rules and paths from all tokens
    declared_rules = set()
    declared_paths = set()
    max_violations_cap = None
    
    for token in tokens:
        if token.token_type == TokenType.LXE:
            declared_rules.update(token.scope.rule_codes)
            declared_paths.update(token.scope.target_paths)
            if token.scope.max_violations:
                if max_violations_cap is None:
                    max_violations_cap = token.scope.max_violations
                else:
                    max_violations_cap = max(max_violations_cap, token.scope.max_violations)
    
    uncovered = []
    covered_count = 0
    
    for v in lint_violations:
        rule = v.get("rule_code", "")
        path = v.get("path", "")
        
        # Check if rule is covered
        rule_covered = rule in declared_rules or not declared_rules
        
        # Check if path is covered (prefix match)
        path_covered = any(path.startswith(p) for p in declared_paths) if declared_paths else True
        
        if rule_covered and path_covered:
            covered_count += 1
        else:
            uncovered.append(f"{rule} at {path}")
    
    # Check max_violations cap
    if max_violations_cap and covered_count > max_violations_cap:
        uncovered.append(
            f"Exceeds max_violations cap: {covered_count} > {max_violations_cap}"
        )
    
    return {
        "fully_covered": len(uncovered) == 0,
        "covered_count": covered_count,
        "uncovered_violations": uncovered,
    }


def list_proposed_tokens() -> list[Token]:
    """List all proposed tokens."""
    proposed_dir = get_proposed_tokens_dir()
    if not proposed_dir.exists():
        return []
    
    tokens = []
    for path in proposed_dir.glob("*.token.json"):
        try:
            data = json.loads(path.read_text())
            tokens.append(Token.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    
    return tokens


def load_tokens_for_contract(
    contract_id: str,
    token_type: TokenType,
    include_proposed: bool = False,
) -> list[Token]:
    """
    Load all tokens of a specific type for a contract.
    
    Args:
        contract_id: Contract ID to filter by
        token_type: NST or LXE
        include_proposed: If True, also search artifacts/tokens_proposed/
    
    Returns:
        List of matching tokens
    """
    tokens = []
    
    # Always check approved tokens
    approved_dir = get_approved_tokens_dir()
    if approved_dir.exists():
        for path in approved_dir.glob("*.token.json"):
            try:
                data = json.loads(path.read_text())
                token = Token.from_dict(data)
                if token.contract_id == contract_id and token.token_type == token_type:
                    tokens.append(token)
            except (json.JSONDecodeError, KeyError):
                continue
    
    # Optionally check proposed tokens
    if include_proposed:
        proposed_dir = get_proposed_tokens_dir()
        if proposed_dir.exists():
            for path in proposed_dir.glob("*.token.json"):
                try:
                    data = json.loads(path.read_text())
                    token = Token.from_dict(data)
                    if token.contract_id == contract_id and token.token_type == token_type:
                        tokens.append(token)
                except (json.JSONDecodeError, KeyError):
                    continue
    
    return tokens


def list_approved_tokens() -> list[Token]:
    """List all approved tokens."""
    approved_dir = get_approved_tokens_dir()
    if not approved_dir.exists():
        return []
    
    tokens = []
    for path in approved_dir.glob("*.token.json"):
        try:
            data = json.loads(path.read_text())
            tokens.append(Token.from_dict(data))
        except (json.JSONDecodeError, KeyError):
            continue
    
    return tokens


def approve_token(token_id: str) -> tuple[bool, str]:
    """
    Approve a proposed token (human action).
    
    This:
    1. Loads the token from proposed/
    2. Updates status to APPROVED
    3. Re-signs the token
    4. Moves to policy/tokens/
    5. Deletes the proposed file
    
    Returns:
        (success, message)
    """
    proposed_path = get_proposed_tokens_dir() / f"{token_id}.token.json"
    if not proposed_path.exists():
        return False, f"Token not found in proposed: {token_id}"
    
    try:
        data = json.loads(proposed_path.read_text())
        token = Token.from_dict(data)
    except (json.JSONDecodeError, KeyError) as e:
        return False, f"Failed to parse token: {e}"
    
    # Update status
    token.status = TokenStatus.APPROVED
    
    # Re-sign with new status
    token.signature = sign_token(token)
    
    # Save to approved location
    approved_dir = get_approved_tokens_dir()
    approved_dir.mkdir(parents=True, exist_ok=True)
    approved_path = approved_dir / f"{token_id}.token.json"
    approved_path.write_text(json.dumps(token.to_dict(), indent=2))
    
    # Remove proposed file
    proposed_path.unlink()
    
    return True, f"Token approved and moved to {approved_path}"


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """CLI entry point for token management."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Token management for Phase 1.5C")
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # propose-nst
    nst_parser = subparsers.add_parser("propose-nst", help="Propose a New Symbol Token")
    nst_parser.add_argument("--contract-id", required=True, help="Parent contract ID")
    nst_parser.add_argument("--root", required=True, help="Root category (e.g., ROOT_REPO)")
    nst_parser.add_argument("--symbols", required=True, nargs="+", help="Symbol names")
    nst_parser.add_argument("--paths", required=True, nargs="+", help="Target paths")
    nst_parser.add_argument("--justification", required=True, help="Reason for new symbols")
    
    # propose-lxe
    lxe_parser = subparsers.add_parser("propose-lxe", help="Propose a Lint Exception Token")
    lxe_parser.add_argument("--contract-id", required=True, help="Parent contract ID")
    lxe_parser.add_argument("--root", required=True, help="Root category")
    lxe_parser.add_argument("--paths", required=True, nargs="+", help="Target paths")
    lxe_parser.add_argument("--rules", required=True, nargs="+", help="Rule codes to exempt")
    lxe_parser.add_argument("--justification", required=True, help="Reason for exceptions")
    lxe_parser.add_argument("--max-violations", type=int, help="Max violations cap")
    
    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate a token")
    validate_parser.add_argument("token_id", help="Token ID to validate")
    
    # approve (human action)
    approve_parser = subparsers.add_parser("approve", help="Approve a proposed token (human action)")
    approve_parser.add_argument("token_id", help="Token ID to approve")
    
    # list
    list_parser = subparsers.add_parser("list", help="List tokens")
    list_parser.add_argument("--proposed", action="store_true", help="List proposed only")
    list_parser.add_argument("--approved", action="store_true", help="List approved only")
    
    args = parser.parse_args()
    
    if args.command == "propose-nst":
        token = propose_nst(
            contract_id=args.contract_id,
            root_category=args.root,
            symbol_names=args.symbols,
            target_paths=args.paths,
            justification=args.justification,
        )
        path = save_proposed_token(token)
        print(f"Created NST token: {token.token_id}")
        print(f"Saved to: {path}")
        print(f"Symbols: {token.scope.symbol_names}")
        print(f"\nTo approve, move to: {get_approved_tokens_dir()}")
    
    elif args.command == "propose-lxe":
        token = propose_lxe(
            contract_id=args.contract_id,
            root_category=args.root,
            target_paths=args.paths,
            rule_codes=args.rules,
            justification=args.justification,
            max_violations=getattr(args, "max_violations", None),
        )
        path = save_proposed_token(token)
        print(f"Created LXE token: {token.token_id}")
        print(f"Saved to: {path}")
        print(f"Rules exempted: {token.scope.rule_codes}")
        print(f"\nTo approve, move to: {get_approved_tokens_dir()}")
    
    elif args.command == "validate":
        result = validate_token_detailed(args.token_id)
        if result.valid:
            print(f"[OK] Token {args.token_id} is valid")
            print(f"  Type: {result.token.token_type.value}")
            print(f"  Expires: {result.token.expires_at}")
        else:
            print(f"[INVALID] Token {args.token_id} is INVALID")
            for err in result.errors:
                print(f"  - {err}")
    
    elif args.command == "approve":
        success, message = approve_token(args.token_id)
        if success:
            print(f"[OK] {message}")
        else:
            print(f"[ERROR] {message}")
    
    elif args.command == "list":
        if args.proposed or not args.approved:
            proposed = list_proposed_tokens()
            print(f"\nProposed tokens ({len(proposed)}):")
            for t in proposed:
                print(f"  {t.token_id[:8]}... {t.token_type.value} ({t.status.value})")
        
        if args.approved or not args.proposed:
            approved = list_approved_tokens()
            print(f"\nApproved tokens ({len(approved)}):")
            for t in approved:
                expired = " [EXPIRED]" if t.is_expired() else ""
                print(f"  {t.token_id[:8]}... {t.token_type.value}{expired}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
