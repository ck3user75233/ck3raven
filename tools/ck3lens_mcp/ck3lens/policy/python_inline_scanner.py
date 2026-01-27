"""
Python Inline Code Scanner - Phase 1.5 Remediation

Detects potentially mutating operations in python -c inline code.
Used by classify_command() to determine if python -c is safe or needs enforcement.

Architecture:
- is_python_inline_safe(code: str) -> bool - Quick check if code matches safe allowlist
- scan_python_inline(code: str) -> InlineIntent - Full analysis with reasons
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class InlineIntentType(Enum):
    """Intent classification for python -c inline code."""
    SAFE = auto()           # Matches safe allowlist (env checks, prints)
    READ_ONLY = auto()      # No mutations detected
    POTENTIALLY_WRITE = auto()  # May write files/dirs
    DESTRUCTIVE = auto()    # Deletes, removes, etc.


@dataclass(frozen=True)
class InlineIntent:
    """Result of scanning python -c inline code."""
    intent: InlineIntentType
    reasons: tuple[str, ...] = field(default_factory=tuple)
    matched_allowlist: Optional[str] = None


# =============================================================================
# SAFE ALLOWLIST - Exact patterns that are always safe
# =============================================================================

# Patterns matched exactly (after whitespace normalization)
SAFE_EXACT_PATTERNS = frozenset({
    # Version/env checks
    "import sys; print(sys.version)",
    "import sys; print(sys.executable)",
    "import sys; print(sys.prefix)",
    "import sys; print(sys.version_info)",
    "import sys; print(sys.platform)",
    "import os; print(os.getcwd())",
    "import os; print(os.name)",
    "print('hello')",
    'print("hello")',
})

# Regex patterns for safe variations (compiled for efficiency)
SAFE_REGEX_PATTERNS = [
    # Simple print statements
    re.compile(r'^print\(["\'][^"\']*["\']\)$'),
    # sys.version family
    re.compile(r'^import sys;\s*print\(sys\.(version|executable|prefix|version_info|platform)\)$'),
    # os.getcwd/name
    re.compile(r'^import os;\s*print\(os\.(getcwd\(\)|name)\)$'),
    # Help on modules (read-only introspection)
    re.compile(r'^help\([a-zA-Z_][a-zA-Z0-9_]*\)$'),
    # Environment variable reads
    re.compile(r'^import os;\s*print\(os\.environ\.get\(["\'][^"\']+["\'](,\s*["\'][^"\']*["\'])?\)\)$'),
]


# =============================================================================
# MUTATION PATTERNS - Patterns that indicate potential writes
# =============================================================================

WRITE_PATTERNS = [
    # File writing
    (r'\.write\s*\(', "file.write() call detected"),
    (r'open\s*\([^)]*["\'][wax+]["\']', "open() with write mode"),
    (r'open\s*\([^)]*mode\s*=\s*["\'][wax+]', "open() with mode='w/a/x'"),
    
    # pathlib writes
    (r'\.write_text\s*\(', "Path.write_text() call"),
    (r'\.write_bytes\s*\(', "Path.write_bytes() call"),
    (r'\.mkdir\s*\(', "Path.mkdir() call"),
    (r'\.touch\s*\(', "Path.touch() call"),
    (r'\.rename\s*\(', "Path.rename() call"),
    (r'\.replace\s*\(', "Path.replace() call"),
    (r'\.symlink_to\s*\(', "Path.symlink_to() call"),
    
    # shutil operations
    (r'shutil\.(copy|copy2|copytree|move|rmtree|make_archive)', "shutil mutation"),
    
    # os file operations
    (r'os\.(mkdir|makedirs|rename|remove|unlink|rmdir|symlink|link)', "os file mutation"),
    (r'os\.chmod\s*\(', "os.chmod() call"),
    (r'os\.chown\s*\(', "os.chown() call"),
    
    # Subprocess/exec (can do anything)
    (r'subprocess\.(run|call|Popen|check_output|check_call)', "subprocess execution"),
    (r'\bexec\s*\(', "exec() call"),
    (r'\beval\s*\(', "eval() call"),
    (r'os\.system\s*\(', "os.system() call"),
    (r'os\.popen\s*\(', "os.popen() call"),
]

DESTRUCTIVE_PATTERNS = [
    # File deletion
    (r'os\.(remove|unlink)\s*\(', "file deletion (os.remove/unlink)"),
    (r'os\.rmdir\s*\(', "directory deletion (os.rmdir)"),
    (r'shutil\.rmtree\s*\(', "recursive deletion (shutil.rmtree)"),
    (r'\.unlink\s*\(', "Path.unlink() deletion"),
    (r'\.rmdir\s*\(', "Path.rmdir() deletion"),
    
    # Database
    (r'(drop|truncate)\s+table', "SQL destructive"),
    (r'delete\s+from', "SQL delete"),
]


# =============================================================================
# PUBLIC API
# =============================================================================

def normalize_code(code: str) -> str:
    """Normalize Python code for comparison (strip, collapse whitespace)."""
    # Remove surrounding quotes if present
    if len(code) >= 2:
        if (code.startswith('"') and code.endswith('"')) or \
           (code.startswith("'") and code.endswith("'")):
            code = code[1:-1]
    # Normalize whitespace
    return ' '.join(code.split())


def is_python_inline_safe(code: str) -> bool:
    """
    Quick check if python -c code matches the safe allowlist.
    
    Args:
        code: The Python code string (after -c)
    
    Returns:
        True if code matches safe allowlist exactly
    """
    normalized = normalize_code(code)
    
    # Check exact matches
    if normalized in SAFE_EXACT_PATTERNS:
        return True
    
    # Check regex patterns
    for pattern in SAFE_REGEX_PATTERNS:
        if pattern.match(normalized):
            return True
    
    return False


def scan_python_inline(code: str) -> InlineIntent:
    """
    Full scan of python -c inline code for mutation patterns.
    
    Args:
        code: The Python code string (after -c)
    
    Returns:
        InlineIntent with classification and reasons
    """
    normalized = normalize_code(code)
    
    # Check safe allowlist first
    if normalized in SAFE_EXACT_PATTERNS:
        return InlineIntent(
            intent=InlineIntentType.SAFE,
            matched_allowlist=normalized,
        )
    
    for pattern in SAFE_REGEX_PATTERNS:
        if pattern.match(normalized):
            return InlineIntent(
                intent=InlineIntentType.SAFE,
                matched_allowlist=pattern.pattern,
            )
    
    # Check destructive patterns
    reasons = []
    for pattern, reason in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            reasons.append(reason)
    
    if reasons:
        return InlineIntent(
            intent=InlineIntentType.DESTRUCTIVE,
            reasons=tuple(reasons),
        )
    
    # Check write patterns
    for pattern, reason in WRITE_PATTERNS:
        if re.search(pattern, normalized, re.IGNORECASE):
            reasons.append(reason)
    
    if reasons:
        return InlineIntent(
            intent=InlineIntentType.POTENTIALLY_WRITE,
            reasons=tuple(reasons),
        )
    
    # No mutations detected
    return InlineIntent(intent=InlineIntentType.READ_ONLY)


def extract_inline_code(command: str) -> Optional[str]:
    """
    Extract the Python code from a python -c command.
    
    Args:
        command: Full shell command like 'python -c "print(1)"'
    
    Returns:
        The code string, or None if not a python -c command
    """
    # Match python/python3 -c with quoted code
    match = re.match(
        r'python[3]?\s+-c\s+(["\'])(.*?)\1',
        command,
        re.IGNORECASE | re.DOTALL
    )
    if match:
        return match.group(2)
    
    # Match unquoted code (less common)
    match = re.match(
        r'python[3]?\s+-c\s+(\S+)',
        command,
        re.IGNORECASE
    )
    if match:
        return match.group(1)
    
    return None


# =============================================================================
# CLASSIFICATION HELPER (for classify_command integration)
# =============================================================================

def classify_python_inline(command: str) -> tuple[bool, InlineIntent | None]:
    """
    Classify a python -c command for enforcement.
    
    Args:
        command: Full shell command
    
    Returns:
        (is_python_c, intent) where:
        - is_python_c: True if this is a python -c command
        - intent: InlineIntent if is_python_c, else None
    """
    cmd_lower = command.lower()
    
    # Check if this is a python -c command
    if not re.match(r'python[3]?\s+-c\s', cmd_lower):
        return (False, None)
    
    # Extract and scan the code
    code = extract_inline_code(command)
    if code is None:
        # Could not extract code - treat as unsafe
        return (True, InlineIntent(
            intent=InlineIntentType.POTENTIALLY_WRITE,
            reasons=("Could not parse inline code",),
        ))
    
    intent = scan_python_inline(code)
    return (True, intent)
