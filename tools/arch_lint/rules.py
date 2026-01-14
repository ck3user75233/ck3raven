"""
arch_lint v2.35 — Rule implementations.

This module applies patterns (from patterns.py) to source files.
Each rule function takes a source file and returns findings.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Optional

from .config import LintConfig, in_allowlist
from .patterns import (
    BANNED_DIRECT_TERMS,
    BANNED_CONTEXTUAL,
    COMPOSITE_RULES,
    NEAR_WINDOW_RULES,
    SUSPICIOUS_COMMENT_KEYWORDS,
    FORBIDDEN_FILENAME_GLOBS,
    FILENAME_ALLOWED_PATHS,
    FORBIDDEN_PATH_APIS_ALWAYS,
    SEMANTIC_PATH_OPS,
    PATH_API_ALLOWLIST_FILES,
    PATH_API_ALLOWLIST_DIRS,
    ALLOWED_RESOLVE_BASE_NAMES,
    ENFORCEMENT_CALL_TOKENS,
    ENFORCEMENT_CALLER_ALLOWLIST,
    RAW_IO_NAME_CALLS,
    RAW_IO_DOTTED_CALLS,
    DANGEROUS_IO_TOKENS,
    IO_SAFE_DIRS,
    PATH_ARITH_DOTTED,
    IO_ALLOWLIST,
    MUTATOR_ALLOWLIST,
    BANNED_CONTEXT_HINTS,
    DEPRECATED_HINTS,
    RAW_ALLOWLIST_SUBSTRINGS,
    ALLOWLIST_TOKEN_SEQUENCES,
    WAIVER_TAG,
)
from .scanner import (
    SourceFile,
    get_line,
    tokenize_line,
    tokenize_window,
    python_tokenize_names,
    in_banned_context,
    contains_allowlisted_raw,
    is_deprecated_line,
    is_sql_context,
    has_benign_phrase,
)
from .analysis import ModuleIndex, DefSymbol
from .reporting import Finding


# =============================================================================
# Oracle pattern regexes (for AST-based detection)
# =============================================================================

_RX_ORACLE_NAME = [
    re.compile(r"^can_", re.IGNORECASE),
    re.compile(r"^may_", re.IGNORECASE),
    re.compile(r"^allowed_", re.IGNORECASE),
    re.compile(r"is_.*(writable|editable|allowed|permitted|authorized|mutable|write_ok|writeable)", re.IGNORECASE),
]

_RX_PARALLEL_TRUTH = re.compile(
    r"(editable_mods_list|active_mods|enabled_mods|local_mods|live_mods|"
    r"write_mods|allowed_mods|mutable_mods|visible_cvids|db_visibility)",
    re.IGNORECASE
)

_RX_LENS_CTOR = re.compile(
    r"\b([A-Za-z_]*Lens[A-Za-z_]*|PlaysetLens|Lens)\s*\(",
    re.IGNORECASE
)

# Fallback patterns (else/or with banned concepts)
_FALLBACK_PATTERNS = [
    re.compile(r"else\s*:\s*.*(?:visibility|visible_cvids|lens|legacy|scope)", re.IGNORECASE),
    re.compile(r"\s+or\s+.*(?:visibility|visible_cvids|legacy)", re.IGNORECASE),
    re.compile(r"getattr\s*\(.*(?:visibility|visible_cvids|legacy)", re.IGNORECASE),
]

# SQL/file/subprocess mutators
_SQL_MUTATOR_RX = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|VACUUM|REINDEX)\b",
    re.IGNORECASE
)
_SUBPROCESS_RX = re.compile(r"\b(subprocess\.run|subprocess\.Popen|os\.system)\b")
_FS_WRITE_RX = re.compile(r"\b(Path\.write_text|Path\.write_bytes|Path\.open|open\()\b")

# Path(...).resolve() pattern
_RE_PATH_RESOLVE = re.compile(r"Path\s*\([^)]*\)\s*\.\s*resolve\s*\(")
# attr.resolve() pattern
_RE_ATTR_RESOLVE = re.compile(r"(?P<base>[A-Za-z_][A-Za-z0-9_]*)\s*\.\s*resolve\s*\(")


def _severity_adjusted(cfg: LintConfig, suppressed: bool, default: str) -> str:
    """Adjust severity if suppressed."""
    if suppressed:
        return "INFO" if default == "ERROR" else default
    return default


def _relpath_str(root: Path, p: Path) -> str:
    """Get relative path as posix string."""
    try:
        return p.relative_to(root).as_posix()
    except Exception:
        return p.as_posix()


# =============================================================================
# Composite/Near-Window Matching
# =============================================================================

def match_composite_tokens(tokens: list[str], pattern: str) -> Optional[tuple[int, int]]:
    """
    Match a composite pattern like 'a%b%c'.
    Returns (start_idx, end_idx) or None.
    """
    parts = [p.strip().lower() for p in pattern.split("%") if p.strip()]
    if not parts:
        return None
    
    start = 0
    first_pos = None
    last_pos = None
    
    for p in parts:
        try:
            idx = tokens.index(p, start)
        except ValueError:
            return None
        if first_pos is None:
            first_pos = idx
        last_pos = idx
        start = idx + 1
    
    return (first_pos or 0, (last_pos or 0) + 1)


def window_equals_allowlisted(tokens: list[str], span: tuple[int, int]) -> bool:
    """Check if the token window matches an allowlisted sequence."""
    s, e = span
    window = tuple(tokens[s:e])
    return window in ALLOWLIST_TOKEN_SEQUENCES


def match_near_window(tokens: list[str], required: frozenset[str], window: int) -> Optional[tuple[int, int]]:
    """
    Check if all required tokens appear within a window.
    Returns span or None.
    """
    req = set(t.lower() for t in required)
    n = len(tokens)
    
    for i in range(n):
        if tokens[i] not in req:
            continue
        seen = set()
        for j in range(i, min(n, i + window)):
            if tokens[j] in req:
                seen.add(tokens[j])
            if seen == req:
                return (i, j + 1)
    return None


# =============================================================================
# Rule Functions
# =============================================================================

def check_direct_terms(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for banned direct terms using Python tokenizer."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Skip lint files and docs
    if "lint" in rel.lower() and ("arch_lint" in rel.lower() or "canonical" in rel.lower()):
        return findings
    if "/docs/" in rel or rel.startswith("docs/"):
        return findings
    
    for name, line, col in python_tokenize_names(src.path):
        name_lower = name.lower()
        
        if name_lower in BANNED_DIRECT_TERMS:
            line_text = get_line(src.lines, line)
            
            # Check allowlist
            if contains_allowlisted_raw(line_text, RAW_ALLOWLIST_SUBSTRINGS):
                continue
            
            # Check context suppression
            lo = max(0, line - 1 - 4)
            hi = min(len(src.lines), line - 1 + 5)
            window_text = "\n".join(src.lines[lo:hi])
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text + window_text, BANNED_CONTEXT_HINTS)
            
            severity = "WARN" if is_deprecated_line(line_text, DEPRECATED_HINTS) else "ERROR"
            if suppressed:
                severity = "INFO"
            
            findings.append(Finding(
                rule_id="BANNED_TERM",
                severity=severity,
                path=rel,
                line=line,
                col=col,
                symbol=name,
                message=f"Banned term '{name}' used.",
                evidence=line_text.strip()[:240],
                suggested_fix="Remove/rename to canonical architecture.",
            ))
        
        elif name_lower in BANNED_CONTEXTUAL:
            # Contextually banned (e.g., local_mods only allowed as local_mods_folder)
            line_text = get_line(src.lines, line)
            allowed_context = BANNED_CONTEXTUAL[name_lower]
            
            if allowed_context in line_text:
                continue
            
            findings.append(Finding(
                rule_id="BANNED_TERM",
                severity="ERROR",
                path=rel,
                line=line,
                col=col,
                symbol=name,
                message=f"Banned term '{name}' used. Only '{allowed_context}' is allowed.",
                evidence=line_text.strip()[:240],
            ))
    
    return findings


def check_composites(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for composite and near-window patterns."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    for i, line in enumerate(src.lines, start=1):
        if contains_allowlisted_raw(line, RAW_ALLOWLIST_SUBSTRINGS):
            continue
        
        lo = max(0, i - 1 - 4)
        hi = min(len(src.lines), i - 1 + 5)
        window_lines = src.lines[lo:hi]
        window_text = "\n".join(window_lines)
        
        if cfg.suppress_in_banned_context and in_banned_context(line + window_text, BANNED_CONTEXT_HINTS):
            continue
        
        # Strip comments to avoid false positives from "may write" in comments
        tokens = tokenize_window(window_lines, strip_comments=True)
        
        # Composite rules
        for kind, code, pattern, reason in COMPOSITE_RULES:
            span = match_composite_tokens(tokens, pattern)
            if span is None:
                continue
            if window_equals_allowlisted(tokens, span):
                continue
            # Narrow fix: suppress mod%root in SQL context or benign phrases like "root causes"
            if pattern == "mod%root" and (is_sql_context(window_text) or has_benign_phrase(window_text)):
                continue
            findings.append(Finding(
                rule_id=code,
                severity=kind,
                path=rel,
                line=i,
                col=1,
                message=f"{reason} — matched pattern '{pattern}'.",
                evidence=line.strip()[:240],
            ))
        
        # Near-window rules
        for kind, code, required, win, reason in NEAR_WINDOW_RULES:
            span = match_near_window(tokens, required, win)
            if span is None:
                continue
            if window_equals_allowlisted(tokens, span):
                continue
            # Narrow fix: suppress mod/root near-matches in SQL context or benign phrases
            if required == frozenset({"mod", "root"}) and (is_sql_context(window_text) or has_benign_phrase(window_text)):
                continue
            findings.append(Finding(
                rule_id=code,
                severity=kind,
                path=rel,
                line=i,
                col=1,
                message=f"{reason} — near-window match {sorted(required)} within {win} tokens.",
                evidence=line.strip()[:240],
            ))
    
    return findings


def check_comments(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for suspicious comment keywords (v2.32 Comment Intelligence)."""
    if not cfg.check_comments:
        return []
    
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    for i, line in enumerate(src.lines, start=1):
        if "#" not in line:
            continue
        
        # Check for waiver
        if WAIVER_TAG in line:
            continue
        
        # Extract comment part
        comment_idx = line.find("#")
        comment = line[comment_idx + 1:].lower()
        
        for kw, reason in SUSPICIOUS_COMMENT_KEYWORDS.items():
            if kw in comment:
                findings.append(Finding(
                    rule_id="SUSPECT_COMMENT",
                    severity="WARN",
                    path=rel,
                    line=i,
                    col=comment_idx,
                    message=f"{reason} (keyword: '{kw}')",
                    evidence=line.strip()[:240],
                ))
                break  # One per line
    
    return findings


def check_forbidden_filenames(cfg: LintConfig, files: list[Path]) -> list[Finding]:
    """Check for forbidden filename patterns (from Phase 1)."""
    if not cfg.check_forbidden_filenames:
        return []
    
    findings: list[Finding] = []
    
    for p in files:
        rel = _relpath_str(cfg.root, p)
        
        # Skip allowed paths
        if in_allowlist(rel, FILENAME_ALLOWED_PATHS):
            continue
        
        for glob_pat in FORBIDDEN_FILENAME_GLOBS:
            if fnmatch.fnmatch(p.name, glob_pat):
                findings.append(Finding(
                    rule_id="FORBIDDEN_FILENAME",
                    severity="ERROR",
                    path=rel,
                    line=1,
                    col=0,
                    message=f"Forbidden filename pattern '{glob_pat}' matched. "
                            f"Canonical architecture forbids duplicate gates/approval/policy-engine modules.",
                ))
                break
    
    return findings


def check_path_apis(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for forbidden path APIs outside canonical modules (from Phase 1)."""
    if not cfg.check_path_apis:
        return []
    
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Check if this file is allowed
    if src.path.name in PATH_API_ALLOWLIST_FILES:
        return findings
    if in_allowlist(rel, PATH_API_ALLOWLIST_DIRS):
        return findings
    
    text = src.text
    
    # Check always-forbidden patterns
    for pat in FORBIDDEN_PATH_APIS_ALWAYS:
        idx = 0
        while True:
            idx = text.find(pat, idx)
            if idx == -1:
                break
            
            # Check waiver
            line_start = text.rfind("\n", 0, idx) + 1
            line_end = text.find("\n", idx)
            line_text = text[line_start:line_end if line_end != -1 else len(text)]
            
            if WAIVER_TAG in line_text:
                idx += 1
                continue
            
            prefix = text[:idx]
            line = prefix.count("\n") + 1
            col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
            
            findings.append(Finding(
                rule_id="FORBIDDEN_PATH_API",
                severity="ERROR",
                path=rel,
                line=line,
                col=col,
                message=f"Forbidden path API '{pat}' outside canonical modules.",
                evidence=line_text.strip()[:240],
                suggested_fix="Route through WorldAdapter.",
            ))
            idx += 1
    
    # Check Path(...).resolve() pattern
    for m in _RE_PATH_RESOLVE.finditer(text):
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line_text = text[line_start:line_end if line_end != -1 else len(text)]
        
        if WAIVER_TAG in line_text:
            continue
        
        prefix = text[:m.start()]
        line = prefix.count("\n") + 1
        col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
        
        findings.append(Finding(
            rule_id="FORBIDDEN_PATH_API",
            severity="ERROR",
            path=rel,
            line=line,
            col=col,
            message="Path(...).resolve() used outside canonical modules. Use WorldAdapter.resolve().",
            evidence=line_text.strip()[:240],
        ))
    
    # Check base.resolve() - allow if base is in ALLOWED_RESOLVE_BASE_NAMES
    for m in _RE_ATTR_RESOLVE.finditer(text):
        base_name = m.group("base").lower()
        if base_name in ALLOWED_RESOLVE_BASE_NAMES:
            continue
        
        # Skip if already caught by Path(...).resolve()
        match_context = text[max(0, m.start() - 20):m.end()]
        if _RE_PATH_RESOLVE.search(match_context):
            continue
        
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.start())
        line_text = text[line_start:line_end if line_end != -1 else len(text)]
        
        if WAIVER_TAG in line_text:
            continue
        
        prefix = text[:m.start()]
        line = prefix.count("\n") + 1
        col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
        
        findings.append(Finding(
            rule_id="SUSPECT_RESOLVE",
            severity="WARN",
            path=rel,
            line=line,
            col=col,
            message=f"Suspicious .resolve() call on '{m.group('base')}'. "
                    f"Only WorldAdapter (world.resolve()) is allowed.",
            evidence=line_text.strip()[:240],
        ))
    
    return findings


def check_enforcement_sites(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check that enforcement calls only occur in allowed boundary modules (from Phase 1)."""
    if not cfg.check_enforcement_sites:
        return []
    
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Check if this file is allowed
    if in_allowlist(rel, ENFORCEMENT_CALLER_ALLOWLIST):
        return findings
    
    text = src.text
    
    for func in ENFORCEMENT_CALL_TOKENS:
        idx = text.find(func)
        if idx == -1:
            continue
        
        prefix = text[:idx]
        line = prefix.count("\n") + 1
        col = len(prefix.split("\n")[-1]) if "\n" in prefix else len(prefix)
        
        line_text = get_line(src.lines, line)
        
        findings.append(Finding(
            rule_id="ENFORCEMENT_SITE",
            severity="ERROR",
            path=rel,
            line=line,
            col=col,
            message=f"Enforcement call '{func}' found outside allowed boundary modules.",
            evidence=line_text.strip()[:240],
            suggested_fix="Move enforcement calls to tool boundary/dispatcher.",
        ))
    
    return findings


def check_io_and_mutators(cfg: LintConfig, src: SourceFile, idx: ModuleIndex) -> list[Finding]:
    """Check for raw I/O and mutators outside allowed modules."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Use full path string for allowlist matching (includes parent dirs)
    full_path_str = str(src.path).replace("\\", "/")
    
    allow_raw_io = in_allowlist(rel, IO_ALLOWLIST) or in_allowlist(full_path_str, IO_ALLOWLIST)
    allow_mutators = in_allowlist(rel, MUTATOR_ALLOWLIST) or in_allowlist(full_path_str, MUTATOR_ALLOWLIST)
    is_io_safe = any(safe in src.path.parts for safe in IO_SAFE_DIRS)
    
    # Check raw I/O calls
    if cfg.check_io and not allow_raw_io:
        # Name calls (e.g., open())
        for callee, ln, col in idx.calls:
            if callee in RAW_IO_NAME_CALLS:
                line_text = get_line(src.lines, ln)
                if WAIVER_TAG in line_text:
                    continue
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="IO-01",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=ln,
                    col=col,
                    symbol=callee,
                    message=f"Raw I/O call '{callee}(...)' outside allowed modules.",
                    evidence=line_text.strip()[:240],
                    suggested_fix="Route I/O through handles minted by WorldAdapter.",
                ))
        
        # Dotted calls (e.g., Path.read_text())
        for dotted, ln, col in idx.dotted_calls:
            if dotted in RAW_IO_DOTTED_CALLS:
                line_text = get_line(src.lines, ln)
                if WAIVER_TAG in line_text:
                    continue
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="IO-01",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=ln,
                    col=col,
                    symbol=dotted,
                    message=f"Raw I/O call '{dotted}(...)' outside allowed modules.",
                    evidence=line_text.strip()[:240],
                    suggested_fix="Route I/O through handles minted by WorldAdapter.",
                ))
            
            # Path arithmetic
            if dotted in PATH_ARITH_DOTTED and not allow_raw_io:
                line_text = get_line(src.lines, ln)
                if WAIVER_TAG in line_text:
                    continue
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="PATH-ARITH-01",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=ln,
                    col=col,
                    symbol=dotted,
                    message=f"Path arithmetic '{dotted}(...)' must be centralized in WorldAdapter.",
                    evidence=line_text.strip()[:240],
                    suggested_fix="Call WorldAdapter for canonical path operations.",
                ))
    
    # Check dangerous I/O outside safe dirs (v2.32)
    if cfg.check_io and not is_io_safe:
        for i, line in enumerate(src.lines, start=1):
            l = line.strip()
            if WAIVER_TAG in line:
                continue
            for d_tok in DANGEROUS_IO_TOKENS:
                if d_tok in l:
                    findings.append(Finding(
                        rule_id="DANGEROUS_IO",
                        severity="ERROR",
                        path=rel,
                        line=i,
                        col=1,
                        message=f"Dangerous I/O '{d_tok}' allowed only in builder/tools.",
                        evidence=l[:240],
                    ))
    
    # Check mutators outside allowed modules
    if cfg.check_mutators and not allow_mutators:
        for i, line in enumerate(src.lines, start=1):
            l = line.strip()
            if not l or WAIVER_TAG in line:
                continue
            
            # SQL mutators
            if _SQL_MUTATOR_RX.search(l) and ("execute" in l or "executescript" in l or "executemany" in l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="MUTATOR-01",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=i,
                    col=0,
                    message="SQL mutator detected outside builder/write-handle modules.",
                    evidence=l[:240],
                    suggested_fix="Route DB writes through builder handles only.",
                ))
            
            # File write mutators
            if _FS_WRITE_RX.search(l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="MUTATOR-02",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=i,
                    col=0,
                    message="Filesystem write mutator detected outside builder/write-handle modules.",
                    evidence=l[:240],
                    suggested_fix="Route file writes through builder handles only.",
                ))
            
            # Subprocess mutators
            if _SUBPROCESS_RX.search(l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="MUTATOR-03",
                    severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                    path=rel,
                    line=i,
                    col=0,
                    message="Subprocess/system call detected outside builder/write-handle modules.",
                    evidence=l[:240],
                    suggested_fix="Route side-effecting exec through builder handles only.",
                ))
    
    return findings


def check_oracle_patterns(cfg: LintConfig, src: SourceFile, idx: ModuleIndex) -> list[Finding]:
    """Check for oracle patterns in definitions and if-conditions."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Check definitions
    for d in idx.defs:
        if any(rx.search(d.name) for rx in _RX_ORACLE_NAME):
            line_text = get_line(src.lines, d.line)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="ORACLE-01",
                severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                path=rel,
                line=d.line,
                col=d.col,
                symbol=d.name,
                message=f"Oracle-style symbol '{d.name}' is banned outside enforcement.",
                evidence=line_text.strip()[:240],
                suggested_fix="Delete oracle helpers; gate mutations via handles/policy at boundary.",
            ))
        
        if _RX_PARALLEL_TRUTH.search(d.name):
            line_text = get_line(src.lines, d.line)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="TRUTH-01",
                severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                path=rel,
                line=d.line,
                col=d.col,
                symbol=d.name,
                message=f"Parallel truth symbol '{d.name}' suggests recomputing scope outside handles.",
                evidence=line_text.strip()[:240],
                suggested_fix="Delete parallel lists; derive visibility via WorldAdapter/Builder handles.",
            ))
    
    # Check if-conditions
    for test_src, ln, col in idx.if_tests:
        if not test_src:
            continue
        if any(rx.search(test_src) for rx in _RX_ORACLE_NAME) or _RX_PARALLEL_TRUTH.search(test_src):
            line_text = get_line(src.lines, ln)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="ORACLE-02",
                severity=_severity_adjusted(cfg, suppressed, "ERROR"),
                path=rel,
                line=ln,
                col=col,
                message="Permission branching / oracle-style gating detected in if-condition.",
                evidence=line_text.strip()[:240],
                suggested_fix="Remove permission pre-checks; use canonical boundary gates at mutation sites.",
            ))
    
    return findings


def check_fallback_patterns(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for fallback patterns that retain banned concepts."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    for i, line in enumerate(src.lines, start=1):
        for pattern in _FALLBACK_PATTERNS:
            if pattern.search(line):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, BANNED_CONTEXT_HINTS)
                findings.append(Finding(
                    rule_id="FALLBACK-01",
                    severity=_severity_adjusted(cfg, suppressed, "WARN"),
                    path=rel,
                    line=i,
                    col=0,
                    message="Fallback pattern detected - fallbacks often retain banned ideas during refactor.",
                    evidence=line.strip()[:240],
                    suggested_fix="Review: if this falls back to deprecated visibility/scope patterns, delete it.",
                ))
                break
    
    return findings


def check_concept_explosion(cfg: LintConfig, src: SourceFile, idx: ModuleIndex) -> list[Finding]:
    """Check for Lens concept explosion."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    # Skip WorldAdapter itself
    if "world_adapter" in rel.lower():
        return findings
    
    severity = "ERROR" if cfg.concept_explosion_is_error else "WARN"
    
    # Check definitions
    for d in idx.defs:
        n = d.name.lower()
        if "lens" in n or "playset" in n and "world" in n:
            line_text = get_line(src.lines, d.line)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line_text, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="CONCEPT-01",
                severity=_severity_adjusted(cfg, suppressed, severity),
                path=rel,
                line=d.line,
                col=d.col,
                symbol=d.name,
                message=f"Concept explosion: Lens-like noun '{d.name}' overlaps Session/WorldAdapter/handles.",
                evidence=line_text.strip()[:240],
                suggested_fix="Do not introduce Lens wrappers. Use Session + WorldAdapter + canonical handles.",
            ))
    
    # Check for Lens(...) constructor calls
    for i, line in enumerate(src.lines, start=1):
        m = _RX_LENS_CTOR.search(line)
        if m:
            token = m.group(1)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="CONCEPT-03",
                severity=_severity_adjusted(cfg, suppressed, severity),
                path=rel,
                line=i,
                col=m.start(1),
                symbol=token,
                message=f"Concept explosion: constructor '{token}(...)' suggests creating Lens objects.",
                evidence=line.strip()[:240],
                suggested_fix="Do not create Lens objects. Use WorldAdapter + canonical handles.",
            ))
    
    return findings


def check_unused_symbols(cfg: LintConfig, sources: list[SourceFile], all_refs: set[str]) -> list[Finding]:
    """Check for unused top-level symbols."""
    if not cfg.warn_unused:
        return []
    
    findings: list[Finding] = []
    
    for src in sources:
        if not src.is_python:
            continue
        
        from .analysis import build_index
        idx = build_index(src)
        rel = _relpath_str(cfg.root, src.path)
        
        for d in idx.defs:
            # Skip private and test symbols
            if any(d.name.startswith(pref) for pref in cfg.unused_name_allowlist_prefixes):
                continue
            if d.name in cfg.unused_name_allowlist_exact:
                continue
            
            if d.name not in all_refs:
                findings.append(Finding(
                    rule_id="UNUSED-01",
                    severity=cfg.unused_severity,
                    path=rel,
                    line=d.line,
                    col=d.col,
                    symbol=d.name,
                    message=f"Top-level {d.kind} '{d.name}' appears unused (no repo references found).",
                ))
    
    return findings


def check_deprecated_symbols(cfg: LintConfig, src: SourceFile, idx: ModuleIndex) -> list[Finding]:
    """Check for deprecated symbols still present."""
    if not cfg.warn_deprecated_symbols:
        return []
    
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    for d in idx.defs:
        if d.deprecated:
            line_text = get_line(src.lines, d.line)
            findings.append(Finding(
                rule_id="DEPRECATED-01",
                severity="WARN",
                path=rel,
                line=d.line,
                col=d.col,
                symbol=d.name,
                deprecated=True,
                message=f"Symbol '{d.name}' is marked #deprecated but still resident.",
                evidence=line_text.strip()[:240],
            ))
    
    return findings


def check_doc_terms(cfg: LintConfig, src: SourceFile) -> list[Finding]:
    """Check for banned terms in documentation files."""
    findings: list[Finding] = []
    rel = _relpath_str(cfg.root, src.path)
    
    banned_doc_terms = [
        "playsetlens", "getlens", "get.lens", "lensworld",
        "editable_mods", "live_mods", "local_mods",
        "is_writable", "can_write",
        "legacyvisibility", "legacy_visibility",
        "visible_cvids", "db_visibility",
        "active_playset_data", "active_playset_file",
    ]
    
    for i, line in enumerate(src.lines, start=1):
        lc = line.lower()
        if any(t in lc for t in banned_doc_terms):
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, BANNED_CONTEXT_HINTS)
            findings.append(Finding(
                rule_id="DOC-TERM",
                severity="DOC-WARN",
                path=rel,
                line=i,
                col=0,
                is_doc=True,
                message="Banned/concept-expansion term mentioned in documentation.",
                evidence=line.strip()[:240] if not suppressed else line.strip()[:120],
            ))
    
    return findings
