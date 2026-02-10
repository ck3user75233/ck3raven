"""
Sigil — Session-scoped cryptographic signing foundation.

Sigil provides the ONLY interface for signing and verifying artifacts
in CK3 Lens. All authentication subsystems (MIT, HAT, contracts) call
Sigil's public API. No caller may import hmac, hashlib, or read
CK3LENS_SIGIL_SECRET directly — all cryptographic operations are
encapsulated here.

Architecture:
    - Extension generates a random 16-byte secret per VS Code window activation
    - Secret is held in extension memory only (never on disk)
    - Passed to MCP subprocess as CK3LENS_SIGIL_SECRET env var
    - New window = new secret = all prior signatures invalidated

Public API:
    sigil_available() -> bool       Check if signing is possible
    sigil_sign(payload) -> str      HMAC-SHA256 sign, returns hex
    sigil_verify(payload, sig) -> bool  Constant-time HMAC verification

Consumers:
    MIT  — mode initialization token verification (server.py)
    HAT  — human authorization token approval (tokens.py)
    Contracts — contract file integrity (contract_v1.py)

Authority: docs/SIGIL_ARCHITECTURE.md
"""
from __future__ import annotations

import hashlib
import hmac
import os

# =============================================================================
# PRIVATE — nobody outside this module touches these
# =============================================================================

_ENV_VAR = "CK3LENS_SIGIL_SECRET"


def _get_secret_bytes() -> bytes | None:
    """
    Read the session secret from the environment.

    Returns None if the env var is not set or is not valid hex.
    """
    secret_hex = os.environ.get(_ENV_VAR, "")
    if not secret_hex:
        return None
    try:
        return bytes.fromhex(secret_hex)
    except ValueError:
        return None


# =============================================================================
# PUBLIC API — the ONLY interface callers may use
# =============================================================================


def sigil_available() -> bool:
    """
    Check whether Sigil is operational.

    Returns True if the session secret is present and valid.
    If False, the MCP server was not started by the extension
    (e.g., standalone testing or misconfiguration).
    """
    return _get_secret_bytes() is not None


def sigil_sign(payload: str) -> str:
    """
    Sign a payload string, returning a hex-encoded HMAC-SHA256 signature.

    Args:
        payload: The string to sign. Callers are responsible for building
                 a canonical, deterministic representation of their data.

    Returns:
        Hex string signature.

    Raises:
        RuntimeError: If the session secret is not available.
    """
    secret = _get_secret_bytes()
    if secret is None:
        raise RuntimeError(
            f"Sigil secret not available ({_ENV_VAR} not set). "
            "MCP server must be launched by the CK3 Lens extension."
        )
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def sigil_verify(payload: str, signature: str) -> bool:
    """
    Verify that a signature matches a payload.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        payload: The original string that was signed.
        signature: The hex-encoded signature to verify.

    Returns:
        True if the signature is valid, False otherwise.
        Returns False (not raises) if the secret is unavailable.
    """
    secret = _get_secret_bytes()
    if secret is None:
        return False
    expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
