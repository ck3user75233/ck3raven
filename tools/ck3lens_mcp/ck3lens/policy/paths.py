"""
Centralized Path Normalization Utilities

This module is the SINGLE source of truth for all path normalization
and path containment checks. All modules MUST use these utilities
instead of inline .replace("\\", "/") calls.

Key Functions:
- normalize_path(path) -> str: Convert any path to forward-slash format
- is_under(root, path) -> bool: Check if path is under root (containment check)
- make_relative(path, base) -> str: Convert absolute path to relative

Why This Exists:
- Windows uses backslashes, Unix uses forward slashes
- fnmatch patterns require consistent separators
- Path containment checks require consistent casing on Windows
- 50+ scattered .replace("\\", "/") calls are an anti-pattern

Rules:
1. All paths stored/compared should use forward slashes
2. Case-insensitive comparison on Windows
3. All paths normalized before containment checks
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union


# =============================================================================
# PATH NORMALIZATION (Core Function)
# =============================================================================

def normalize_path(path: Union[str, Path, None]) -> str:
    """
    Normalize a path to use forward slashes consistently.
    
    This is the ONLY function that should convert backslashes to forward slashes.
    All other code should call this function instead of inline .replace().
    
    Args:
        path: A path string or Path object (can be Windows or Unix format)
        
    Returns:
        Path string with forward slashes only
        
    Examples:
        normalize_path("C:\\Users\\foo\\bar.txt")  -> "C:/Users/foo/bar.txt"
        normalize_path("common/traits/00_traits.txt")  -> "common/traits/00_traits.txt"
        normalize_path(Path("foo/bar"))  -> "foo/bar"
    """
    if path is None:
        return ""
    return str(path).replace("\\", "/")


def normalize_path_lower(path: Union[str, Path, None]) -> str:
    """
    Normalize path and convert to lowercase for case-insensitive comparison.
    
    Use this for containment checks on Windows where paths are case-insensitive.
    
    Args:
        path: A path string or Path object
        
    Returns:
        Lowercase path string with forward slashes
    """
    return normalize_path(path).lower()


# =============================================================================
# PATH CONTAINMENT (is_under)
# =============================================================================

def is_under(root: Union[str, Path], path: Union[str, Path], case_sensitive: bool = False) -> bool:
    """
    Check if path is contained under root directory.
    
    This is a cross-platform path containment check that:
    - Normalizes both paths to forward slashes
    - Handles case sensitivity properly
    - Resolves symlinks to prevent traversal attacks
    
    Args:
        root: The root directory to check against
        path: The path to check
        case_sensitive: If False (default on Windows), compare case-insensitively
        
    Returns:
        True if path is under root, False otherwise
        
    Examples:
        is_under("/home/user", "/home/user/docs/file.txt")  -> True
        is_under("C:/Users/foo", "C:\\Users\\foo\\bar.txt")  -> True
        is_under("/home/user", "/home/other/file.txt")  -> False
        is_under("/home/user", "/home/user/../other/file.txt")  -> False (after resolution)
    """
    if not root or not path:
        return False
    
    # Resolve to absolute paths and normalize
    try:
        root_resolved = Path(root).resolve()
        path_resolved = Path(path).resolve()
    except (OSError, ValueError):
        # Invalid paths
        return False
    
    # Normalize to forward slashes
    root_str = normalize_path(root_resolved)
    path_str = normalize_path(path_resolved)
    
    # Case-insensitive on Windows by default
    if not case_sensitive and os.name == 'nt':
        root_str = root_str.lower()
        path_str = path_str.lower()
    
    # Ensure root ends with / for proper prefix matching
    if not root_str.endswith("/"):
        root_str = root_str + "/"
    
    # Check if path starts with root
    return path_str.startswith(root_str) or path_str.rstrip("/") == root_str.rstrip("/")


def is_under_any(roots: list, path: Union[str, Path], case_sensitive: bool = False) -> bool:
    """
    Check if path is contained under any of the root directories.
    
    Args:
        roots: List of root directories to check
        path: The path to check
        case_sensitive: If False, compare case-insensitively
        
    Returns:
        True if path is under any root, False otherwise
    """
    return any(is_under(root, path, case_sensitive) for root in roots)


# =============================================================================
# PATH RESOLUTION
# =============================================================================

def make_relative(path: Union[str, Path], base: Union[str, Path]) -> str:
    """
    Convert an absolute path to be relative to a base directory.
    
    Args:
        path: The absolute path to convert
        base: The base directory
        
    Returns:
        Relative path with forward slashes, or the original path if not under base
        
    Examples:
        make_relative("/home/user/docs/file.txt", "/home/user")  -> "docs/file.txt"
        make_relative("C:\\foo\\bar.txt", "C:\\foo")  -> "bar.txt"
    """
    try:
        path_resolved = Path(path).resolve()
        base_resolved = Path(base).resolve()
        rel = path_resolved.relative_to(base_resolved)
        return normalize_path(rel)
    except ValueError:
        # Path is not under base
        return normalize_path(path)


def join_path(*parts: Union[str, Path]) -> str:
    """
    Join path parts using forward slashes.
    
    Args:
        *parts: Path parts to join
        
    Returns:
        Joined path with forward slashes
        
    Examples:
        join_path("common", "traits", "00_traits.txt")  -> "common/traits/00_traits.txt"
        join_path("C:/Users", "foo", "bar.txt")  -> "C:/Users/foo/bar.txt"
    """
    parts_normalized = [normalize_path(p).rstrip("/") for p in parts if p]
    return "/".join(parts_normalized)


# =============================================================================
# PATH PATTERN MATCHING
# =============================================================================

def _glob_match(path: str, pattern: str) -> bool:
    """
    Match path against a glob pattern with proper ** support.
    
    Unlike fnmatch, this handles ** as "zero or more directories":
    - "builder/**/*.py" matches "builder/daemon.py" (zero directories)
    - "builder/**/*.py" matches "builder/sub/file.py" (one directory)
    - "builder/**/*.py" matches "builder/a/b/c.py" (three directories)
    
    Args:
        path: Normalized path (forward slashes)
        pattern: Glob pattern with optional **
        
    Returns:
        True if path matches pattern
    """
    import fnmatch
    import re
    
    # Split pattern and path into parts
    pattern_parts = pattern.split("/")
    path_parts = path.split("/")
    
    def match_recursive(p_idx: int, path_idx: int) -> bool:
        """Recursively match pattern parts against path parts."""
        # If we've consumed all pattern parts
        if p_idx >= len(pattern_parts):
            # Path must also be fully consumed
            return path_idx >= len(path_parts)
        
        current_pattern = pattern_parts[p_idx]
        
        # Handle ** - matches zero or more directories
        if current_pattern == "**":
            # If ** is the last pattern part, it matches everything remaining
            if p_idx == len(pattern_parts) - 1:
                return True
            
            # Try matching zero directories (skip **)
            if match_recursive(p_idx + 1, path_idx):
                return True
            
            # Try matching one or more directories
            for i in range(path_idx, len(path_parts)):
                if match_recursive(p_idx + 1, i + 1):
                    return True
            return False
        
        # Handle normal pattern part
        if path_idx >= len(path_parts):
            return False
        
        # Use fnmatch for the individual part (handles * and ?)
        if fnmatch.fnmatch(path_parts[path_idx], current_pattern):
            return match_recursive(p_idx + 1, path_idx + 1)
        
        return False
    
    return match_recursive(0, 0)


def matches_pattern(path: Union[str, Path], pattern: str) -> bool:
    """
    Check if path matches a glob pattern.
    
    Properly handles:
    - * matches any single path component (not including /)
    - ** matches zero or more directories
    - ? matches any single character
    
    Args:
        path: The path to check
        pattern: Glob pattern (e.g., "**/*.py", "builder/**/*.py", "common/traits/*")
        
    Returns:
        True if path matches pattern
        
    Examples:
        matches_pattern("builder/daemon.py", "builder/**/*.py")  -> True
        matches_pattern("builder/sub/file.py", "builder/**/*.py")  -> True
        matches_pattern("tools/server.py", "tools/*.py")  -> True
        matches_pattern("tools/sub/server.py", "tools/*.py")  -> False
    """
    path_normalized = normalize_path(path)
    pattern_normalized = normalize_path(pattern)
    
    # Always use _glob_match for proper path-segment matching
    return _glob_match(path_normalized, pattern_normalized)


def matches_any_pattern(path: Union[str, Path], patterns: list) -> bool:
    """
    Check if path matches any of the glob patterns.
    
    Args:
        path: The path to check
        patterns: List of glob patterns
        
    Returns:
        True if path matches any pattern
    """
    return any(matches_pattern(path, p) for p in patterns)


# =============================================================================
# LEGACY COMPATIBILITY
# =============================================================================

# These functions provide compatibility with existing code during migration.
# New code should use the functions above directly.

def posixify(path: Union[str, Path, None]) -> str:
    """
    Alias for normalize_path. Converts path to POSIX format (forward slashes).
    
    This name matches the common convention in other codebases.
    """
    return normalize_path(path)


def normalize_for_comparison(path: Union[str, Path, None]) -> str:
    """
    Alias for normalize_path_lower. Prepares path for case-insensitive comparison.
    """
    return normalize_path_lower(path)
