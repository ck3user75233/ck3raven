"""
TASL — Tool Architecture Standards Linter

The single, combined linter for the Reply System and Logging System.
There is no separate reply linter. There is no separate logging linter.
This is it.

Every MCP tool in ck3raven must meet these standards.
TASL checks them statically, fast, no imports required.

NO WHITELISTING. Every violation is reported unconditionally.
The linter does not hide, suppress, or accept anything less than
correct code. Humans decide priority; the linter reports everything.

Check categories:

  ── Reply System ──────────────────────────────────────────────────
  SAFE_WRAPPER     — @mcp_safe_tool decorator present
  REPLY_TYPE       — -> Reply return annotation
  PREAMBLE         — trace_info + ReplyBuilder init + correct tool= name
  REPLY_CODES      — code strings match LAYER-AREA-TYPE-NNN format
  LAYER_OWNERSHIP  — layer can emit declared reply type
  NO_PARALLEL      — forbidden parallel types (EnforcementResult, etc.)
  DICT_RETURN      — any function returning dict/Dict instead of Reply
  ORPHAN_CODES     — codes in source but not in canonical registry
  CODES_VIA_RB     — reply codes must go through rb.success/invalid/denied/error
  ALL_RETURNS_VIA_RB — every return in tool functions via rb.*()
  NO_GHOST_REPLY   — warn on 'reply' in definitions, error on rogue builders
  NO_FAKE_METHODS  — rb.info(), rb.warn(), rb.fail() must not exist
  SINGLE_REGISTRY  — only reply_codes.py; no reply_registry imports
  RB_CONSTRUCTOR   — ReplyBuilder first arg must be TraceInfo, not dict literal
  RB_SCHEMA        — rb.*() calls must include required 'data' positional arg
  REPLY_ATTR       — no non-existent Reply attributes (e.g., .code_type)
  IMPL_REPLY       — _impl/_internal functions must return Reply, not dicts

  ── Logging System ────────────────────────────────────────────────
  TRACE_CATEGORY   — trace.log() using canonical categories
  CANONICAL_LOGGER — must use ck3lens.logging, not stdlib/print/raw writes
  REDUNDANT_TRACE  — trace.log() that duplicates decorator output
  AREA_HEURISTIC   — tool name → expected AREA mapping

Run:
    python -m tools.compliance.tasl
    python tools/compliance/tasl.py
    python tools/compliance/tasl.py --files path/to/file1.py path/to/file2.py

Exit codes:
    0 = all standards met
    1 = violations found
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple


# ============================================================================
# Configuration
# ============================================================================

# Default scan: MCP toolchain end-to-end
DEFAULT_SCAN_FILES = [
    "tools/ck3lens_mcp/server.py",
    "tools/ck3lens_mcp/safety.py",
    "tools/ck3lens_mcp/ck3lens/unified_tools.py",
    "tools/ck3lens_mcp/ck3lens/reply_codes.py",
    "tools/ck3lens_mcp/ck3lens/logging.py",
    "tools/ck3lens_mcp/ck3lens/enforcement.py",
    "tools/ck3lens_mcp/ck3lens/world_adapter.py",
]

# Additional dirs to scan when no --files given
SCAN_DIRS = [
    "tools/ck3lens_mcp",
    "src/ck3raven/core",
]

SCAN_EXTENSIONS = {".py"}

SKIP_PATTERNS = [
    "exports/",
    "archive/",
    "deprecated_policy/",
    "__pycache__/",
    ".wip/",
    "node_modules/",
    "tasl.py",       # Don't lint ourselves
]

# ── Reply code rules ────────────────────────────────────────────────────────

CODE_PATTERN = re.compile(r"^([A-Z]+)-([A-Z]+)-([SIDE])-(\d{3})$")
CODE_IN_SOURCE = re.compile(r"""['"]([A-Z]+-[A-Z]+-[SIDE]-\d{3})['"]""")

# ── Reply call-site compliance ──────────────────────────────────────────────

# RB_CONSTRUCTOR: dict literal passed as first arg (must be TraceInfo)
_RB_CONSTRUCTOR_DICT = re.compile(r'ReplyBuilder\(\s*\{')

# RB_SCHEMA: rb.method('CODE', message=...) — data arg skipped
_RB_SKIP_DATA = re.compile(
    r"rb\.(success|invalid|denied|error)\(\s*"
    r"['\"][^'\"]+['\"]\s*,"       # code string, comma
    r"\s*(message|layer)\s*=",     # immediately followed by non-data keyword
)

# RB_SCHEMA: rb.method('CODE') — no data at all
_RB_NO_DATA_ARG = re.compile(
    r"rb\.(success|invalid|denied|error)\(\s*"
    r"['\"][^'\"]+['\"]\s*,?\s*\)",  # code string, optional trailing comma, close paren
)

# REPLY_ATTR: known-wrong attribute names on Reply objects
_WRONG_REPLY_ATTR = re.compile(r'\.(code_type)\b')
WRONG_ATTR_FIXES = {"code_type": "reply_type"}

VALID_LAYERS = {"WA", "EN", "CT", "MCP"}
LAYER_ALLOWED_TYPES = {
    "WA":  {"S", "I", "E"},
    "EN":  {"S", "D", "E"},
    "CT":  {"S", "I", "E"},
    "MCP": {"S", "E", "I"},
}

# ── Parallel type ban ───────────────────────────────────────────────────────

FORBIDDEN_TYPES = [
    "EnforcementResult",
]

# ── Canonical trace categories (from CANONICAL_LOGS.md) ─────────────────────

CANONICAL_CATEGORIES = {
    # MCP lifecycle
    "mcp.init", "mcp.tool", "mcp.dispose", "mcp.bootstrap",
    # Contracts
    "contract.open", "contract.close", "contract.cancel",
    "contract.flush", "contract.archive",
    # Session
    "session.mode", "session.playset",
    # Policy
    "policy.enforce", "policy.token",
    # Domain (approved non-mcp.tool audit events)
    "mcp.repair",
}

# ── Canonical reply class/helper names (for NO_GHOST_REPLY) ─────────────────

CANONICAL_REPLY_NAMES = {
    "Reply", "ReplyBuilder", "ReplyCode", "ReplyType",
    "reply_type", "reply_codes", "LEGACY_TO_CANONICAL",
    "_ALL_CODES", "validate_code_format", "get_code", "get_message",
    "validate_registry",
}

# ── Tool name → expected AREAs mapping (for AREA_HEURISTIC) ────────────────

TOOL_AREA_MAP = {
    "ck3_file": {"READ", "WRITE", "RES", "PARSE"},
    "ck3_folder": {"READ", "RES"},
    "ck3_playset": {"VIS"},
    "ck3_git": {"GIT"},
    "ck3_exec": {"EXEC"},
    "ck3_search": {"RES", "READ"},
    "ck3_search_mods": {"RES", "READ"},
    "ck3_logs": {"LOG", "READ"},
    "ck3_journal": {"LOG"},
    "ck3_conflicts": {"READ", "RES"},
    "ck3_validate": {"VAL", "PARSE"},
    "ck3_parse_content": {"PARSE"},
    "ck3_repair": {"SYS"},
    "ck3_contract": {"OPEN", "CLOSE"},
    "ck3_db": {"DB"},
    "ck3_db_query": {"DB"},
    "ck3_db_delete": {"DB"},
    "ck3_close_db": {"DB"},
    "ck3_vscode": {"IO", "SYS"},
    "ck3_qbuilder": {"SYS"},
    "ck3_protect": {"WRITE", "GATE"},
    "ck3_token": {"CFG", "SYS"},
}

# AREAs that are always allowed (infrastructure / catch-all)
UNIVERSAL_AREAS = {"SYS", "DB", "GATE", "CFG"}


# ============================================================================
# Types
# ============================================================================

class Violation(NamedTuple):
    file: str
    line: int
    rule: str
    message: str


class ToolInfo(NamedTuple):
    """Parsed info about a single @mcp_safe_tool function or _impl/_internal helper."""
    name: str
    file: str
    decorator_line: int      # 0 for impl functions (no decorator)
    def_line: int
    has_reply_annotation: bool
    has_trace_info: bool
    has_reply_builder: bool
    rb_tool_name: str | None
    body: str                   # Full body of the function
    is_impl: bool = False       # True for _impl/_internal helpers


# ============================================================================
# File Collection
# ============================================================================

def collect_files(root: Path, explicit_files: list[str] | None = None) -> list[Path]:
    """Collect Python files to scan."""
    if explicit_files:
        files = []
        for f in explicit_files:
            p = root / f if not Path(f).is_absolute() else Path(f)
            if p.exists() and p.suffix == ".py":
                files.append(p)
        return files

    # Default: scan all .py files in SCAN_DIRS
    files = []
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        for pyfile in dirpath.rglob("*.py"):
            if not _should_skip(pyfile, root):
                files.append(pyfile)
    return files


# ============================================================================
# Tool Discovery
# ============================================================================

_TOOL_PATTERN = re.compile(
    r"@mcp_safe_tool\s*\n"
    r"def\s+(\w+)\s*\(",
    re.MULTILINE,
)

_RB_TOOL_NAME = re.compile(r"""ReplyBuilder\([^)]*tool\s*=\s*['"](\w+)['"]""")


def discover_tools(root: Path) -> list[ToolInfo]:
    """Find all @mcp_safe_tool-decorated functions in server.py."""
    tools: list[ToolInfo] = []

    server = root / "tools" / "ck3lens_mcp" / "server.py"
    if not server.exists():
        return tools

    source = server.read_text(encoding="utf-8")
    lines = source.splitlines()

    for m in _TOOL_PATTERN.finditer(source):
        func_name = m.group(1)
        dec_offset = source[:m.start()].count("\n") + 1
        def_offset = source[:m.end()].count("\n") + 1

        # Grab full body (from def line to next top-level def or decorator)
        body_start_idx = def_offset
        body_lines: list[str] = []
        past_signature = False  # Track whether we've passed the function signature
        for i in range(body_start_idx, len(lines)):
            ln = lines[i]
            # First, skip past the function signature (parameters + closing ")")
            if not past_signature:
                body_lines.append(ln)
                # Signature ends when we hit a line containing "):' or ") ->"
                if re.search(r'^\s*\).*:\s*$', ln) or re.search(r'\)\s*->\s*\w+.*:\s*$', ln):
                    past_signature = True
                continue
            # After signature, break on next top-level construct
            if ln and not ln[0].isspace() and not ln.startswith("#"):
                break
            body_lines.append(ln)
        body = "\n".join(body_lines)

        # Check for -> Reply in the full body (includes signature lines)
        has_reply = bool(re.search(r"->\s*Reply\s*:", body))
        has_trace = "get_current_trace_info()" in body
        has_rb = "ReplyBuilder(" in body

        rb_name_match = _RB_TOOL_NAME.search(body)
        rb_tool_name = rb_name_match.group(1) if rb_name_match else None

        tools.append(ToolInfo(
            name=func_name,
            file="tools/ck3lens_mcp/server.py",
            decorator_line=dec_offset,
            def_line=def_offset,
            has_reply_annotation=has_reply,
            has_trace_info=has_trace,
            has_reply_builder=has_rb,
            rb_tool_name=rb_tool_name,
            body=body,
        ))

    return tools


# ============================================================================
# Impl/Internal Function Discovery
# ============================================================================

# Pattern: def ck3_*_impl( or def _ck3_*_internal(
_IMPL_PATTERN = re.compile(
    r"^def\s+(ck3_\w+_impl|_ck3_\w+_internal)\s*\(",
    re.MULTILINE,
)


def discover_impl_functions(root: Path, files: list[Path]) -> list[ToolInfo]:
    """Find all ck3_*_impl and _ck3_*_internal functions in scanned files.

    These are the helper functions that do the actual work for MCP tools.
    Per Canonical Reply System 2.0 §1, they are in scope for Reply compliance.
    """
    impls: list[ToolInfo] = []

    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        source = pyfile.read_text(encoding="utf-8")
        lines = source.splitlines()

        for m in _IMPL_PATTERN.finditer(source):
            func_name = m.group(1)
            def_offset = source[:m.end()].count("\n") + 1

            # Grab full body (same logic as discover_tools)
            body_start_idx = def_offset
            body_lines: list[str] = []
            past_signature = False
            for i in range(body_start_idx, len(lines)):
                ln = lines[i]
                if not past_signature:
                    body_lines.append(ln)
                    if re.search(r'^\s*\).*:\s*$', ln) or re.search(r'\)\s*->\s*\w+.*:\s*$', ln):
                        past_signature = True
                    continue
                if ln and not ln[0].isspace() and not ln.startswith("#"):
                    break
                body_lines.append(ln)
            body = "\n".join(body_lines)

            has_reply = bool(re.search(r"->\s*Reply\s*:", body))
            has_dict = bool(re.search(r"->\s*(dict|Dict)", body))
            has_rb = "ReplyBuilder(" in body or "rb." in body

            impls.append(ToolInfo(
                name=func_name,
                file=relpath,
                decorator_line=0,
                def_line=def_offset,
                has_reply_annotation=has_reply,
                has_trace_info=False,
                has_reply_builder=has_rb,
                rb_tool_name=None,
                body=body,
                is_impl=True,
            ))

    return impls


# ============================================================================
# Check: IMPL_REPLY — impl/internal functions must return Reply, not dicts
# ============================================================================

_RETURN_BARE_DICT_IMPL = re.compile(r"return\s+\{")
_RETURN_RB_IMPL = re.compile(r"return\s+rb\.(success|invalid|denied|error)\(")
_RETURN_REPLY_VAR = re.compile(r"return\s+(result|reply|response)\b")


def check_impl_reply(impls: list[ToolInfo]) -> list[Violation]:
    """Impl/internal functions must comply with Reply System.

    Checks:
    - Must have -> Reply annotation (not -> dict or missing)
    - Must not return bare dicts
    - Returns should go through rb.*() or return a Reply variable
    """
    violations = []
    for impl in impls:
        # Check 1: Must have -> Reply annotation
        if not impl.has_reply_annotation:
            has_dict_annotation = bool(re.search(r"->\s*(dict|Dict)", impl.body))
            if has_dict_annotation:
                violations.append(Violation(
                    impl.file, impl.def_line, "IMPL_REPLY",
                    f"'{impl.name}' returns dict — must return Reply "
                    f"(Canonical Reply System 2.0 §12)",
                ))
            else:
                violations.append(Violation(
                    impl.file, impl.def_line, "IMPL_REPLY",
                    f"'{impl.name}' missing -> Reply annotation "
                    f"(Canonical Reply System 2.0 §1)",
                ))

        # Check 2: Bare dict returns
        body_lines = impl.body.splitlines()
        for i, line in enumerate(body_lines, impl.def_line):
            stripped = line.strip()
            if not stripped.startswith("return"):
                continue
            if stripped.startswith("#"):
                continue
            # OK: return rb.*()
            if _RETURN_RB_IMPL.search(line):
                continue
            # OK: return result/reply/response variable
            if _RETURN_REPLY_VAR.search(stripped):
                continue
            # Bare dict
            if _RETURN_BARE_DICT_IMPL.search(line):
                violations.append(Violation(
                    impl.file, i, "IMPL_REPLY",
                    f"'{impl.name}': return {{...}} — must return Reply",
                ))

    return violations


# ============================================================================
# Check: SAFE_WRAPPER + REPLY_TYPE + PREAMBLE
# ============================================================================

def check_safe_wrapper_and_preamble(tools: list[ToolInfo]) -> list[Violation]:
    violations = []
    for t in tools:
        if not t.has_reply_annotation:
            violations.append(Violation(
                t.file, t.def_line, "REPLY_TYPE",
                f"Tool '{t.name}' missing -> Reply return annotation",
            ))
        if not t.has_trace_info:
            violations.append(Violation(
                t.file, t.def_line, "PREAMBLE",
                f"Tool '{t.name}' missing trace_info = get_current_trace_info()",
            ))
        if not t.has_reply_builder:
            violations.append(Violation(
                t.file, t.def_line, "PREAMBLE",
                f"Tool '{t.name}' missing rb = ReplyBuilder(...)",
            ))
        if t.has_reply_builder and t.rb_tool_name and t.rb_tool_name != t.name:
            violations.append(Violation(
                t.file, t.def_line, "PREAMBLE",
                f"Tool '{t.name}' has ReplyBuilder(tool='{t.rb_tool_name}') — "
                f"should be '{t.name}'",
            ))
    return violations


# ============================================================================
# Check: REPLY_CODES + LAYER_OWNERSHIP (in source)
# ============================================================================

def check_reply_codes_in_source(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        source = pyfile.read_text(encoding="utf-8")
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(source.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            # Skip lines inside LEGACY_TO_CANONICAL dict
            if "LEGACY_TO_CANONICAL" in source and _in_legacy_table(source, i):
                continue
            for cm in CODE_IN_SOURCE.finditer(line):
                code = cm.group(1)
                violations.extend(_validate_code(code, relpath, i))
    return violations


# ============================================================================
# Check: REPLY_CODES + LAYER_OWNERSHIP (in registry)
# ============================================================================

def check_registry_codes(root: Path) -> list[Violation]:
    violations = []
    rp = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    if rp.exists():
        lines = rp.read_text(encoding="utf-8").splitlines()
        relpath = str(rp.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(lines, 1):
            m = re.search(r'ReplyCode\("([^"]+)"', line)
            if m:
                violations.extend(_validate_code(m.group(1), relpath, i))
    return violations


# ============================================================================
# Check: NO_PARALLEL
# ============================================================================

def check_no_parallel_types(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            for forbidden in FORBIDDEN_TYPES:
                if re.search(rf"\bclass\s+{forbidden}\b", line):
                    violations.append(Violation(
                        relpath, i, "NO_PARALLEL",
                        f"Forbidden parallel type: class {forbidden} (use Reply)",
                    ))
                elif re.search(rf"\b{forbidden}\b", line) and "import" in line:
                    violations.append(Violation(
                        relpath, i, "NO_PARALLEL",
                        f"Import of forbidden parallel type: {forbidden}",
                    ))
    return violations


# ============================================================================
# Check: DICT_RETURN — any function returning dict instead of Reply
# ============================================================================

def check_dict_return(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    pattern = re.compile(
        r"def\s+(\w+)\s*\([^)]*\)\s*->\s*"
        r"(dict(?:\[.*?\])?|Dict(?:\[.*?\])?|Reply\s*\|\s*dict|dict\s*\|\s*Reply)"
    )
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            if m:
                violations.append(Violation(
                    relpath, i, "DICT_RETURN",
                    f"'{m.group(1)}' returns {m.group(2)} — should return Reply",
                ))
    return violations


# ============================================================================
# Check: TRACE_CATEGORY
# ============================================================================

def check_trace_categories(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    pattern = re.compile(r'trace\.log\(\s*"([^"]+)"')
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            m = pattern.search(line)
            if m:
                cat = m.group(1)
                if cat not in CANONICAL_CATEGORIES:
                    violations.append(Violation(
                        relpath, i, "TRACE_CATEGORY",
                        f"Non-canonical trace category: '{cat}'",
                    ))
    return violations


# ============================================================================
# Check: ORPHAN_CODES — codes used but not in canonical registry
# ============================================================================

def check_orphan_codes(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    registered = _collect_registered_codes(root)
    if not registered:
        return violations

    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        # Skip the registry file itself
        if relpath.endswith("reply_codes.py"):
            continue
        source = pyfile.read_text(encoding="utf-8")
        for i, line in enumerate(source.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for cm in CODE_IN_SOURCE.finditer(line):
                code = cm.group(1)
                if code not in registered:
                    violations.append(Violation(
                        relpath, i, "ORPHAN_CODES",
                        f"Code {code!r} used but not in canonical registry (reply_codes.py)",
                    ))
    return violations


# ============================================================================
# Check: CODES_VIA_RB — codes must go through rb.success/invalid/denied/error
# ============================================================================

_RB_CALL = re.compile(r"rb\.(success|invalid|denied|error)\(\s*['\"]([A-Z]+-[A-Z]+-[SIDE]-\d{3})['\"]")
_REPLY_DIRECT = re.compile(r"Reply\.(success|invalid|denied|error)\(\s*['\"]([A-Z]+-[A-Z]+-[SIDE]-\d{3})['\"]")


def check_codes_via_rb(tools: list[ToolInfo]) -> list[Violation]:
    """Codes in tool functions must go through rb.*(), not Reply.*() directly."""
    violations = []
    for t in tools:
        # Find Reply.success/invalid/denied/error direct calls
        for i, line in enumerate(t.body.splitlines(), t.def_line):
            if _REPLY_DIRECT.search(line):
                violations.append(Violation(
                    t.file, i, "CODES_VIA_RB",
                    f"Tool '{t.name}': Direct Reply.*() call — use rb.*() instead",
                ))
    return violations


# ============================================================================
# Check: ALL_RETURNS_VIA_RB — every return in tool funcs via rb.*()
# ============================================================================

_RETURN_RB = re.compile(r"return\s+rb\.(success|invalid|denied|error)\(")
_RETURN_ANY = re.compile(r"^\s+return\s+")
_RETURN_BARE_DICT = re.compile(r"return\s+\{")
_RETURN_NONE = re.compile(r"return\s*$")


def check_all_returns_via_rb(tools: list[ToolInfo]) -> list[Violation]:
    """Every return in a tool function must go through rb.*()."""
    violations = []
    for t in tools:
        body_lines = t.body.splitlines()
        # Detect if tool has Reply passthrough pattern (isinstance check)
        has_reply_passthrough = "isinstance(result, Reply)" in t.body
        # Track nested function depth to skip inner function returns
        in_nested_def = False
        nested_indent = 0
        for i, line in enumerate(body_lines, t.def_line):
            stripped = line.strip()
            # Track nested function definitions
            if re.match(r"\s+def\s+\w+\(", line):
                in_nested_def = True
                nested_indent = len(line) - len(line.lstrip())
                continue
            # Exit nested function when indentation returns to or above nested def level
            if in_nested_def and stripped and (len(line) - len(line.lstrip())) <= nested_indent:
                if not re.match(r"\s+def\s+\w+\(", line):
                    in_nested_def = False
            # Skip returns inside nested functions
            if in_nested_def:
                continue
            if not stripped.startswith("return"):
                continue
            # Skip docstring lines or comments
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # OK: return rb.*()
            if _RETURN_RB.search(line):
                continue
            # OK: Reply passthrough — return result (guarded by isinstance check)
            if has_reply_passthrough and re.match(r"return\s+result\s*$", stripped):
                continue
            # Bare dict
            if _RETURN_BARE_DICT.search(line):
                violations.append(Violation(
                    t.file, i, "ALL_RETURNS_VIA_RB",
                    f"Tool '{t.name}': return {{...}} — must use rb.*() to return Reply",
                ))
            # return None
            elif _RETURN_NONE.match(stripped):
                violations.append(Violation(
                    t.file, i, "ALL_RETURNS_VIA_RB",
                    f"Tool '{t.name}': bare return — must use rb.*() to return Reply",
                ))
            # return <variable> (not rb.*)
            elif _RETURN_ANY.match(line) and not _RETURN_RB.search(line):
                # Could be 'return rb.success(...)' split across lines — check
                if "rb." not in stripped:
                    violations.append(Violation(
                        t.file, i, "ALL_RETURNS_VIA_RB",
                        f"Tool '{t.name}': return not via rb.*() — '{stripped[:60]}'",
                    ))
    return violations


# ============================================================================
# Check: NO_GHOST_REPLY — warn on 'reply' in definitions, error on rogue builders
# ============================================================================

_CLASS_DEF = re.compile(r"^\s*class\s+(\w*[Rr]eply\w*)")
_FUNC_DEF = re.compile(r"^\s*def\s+(\w*[Rr]eply\w*)")
_VAR_DEF = re.compile(r"^\s*(\w*[Rr]eply\w*)\s*=")
_BUILDER_PATTERN = re.compile(r"[Rr]eply.*[Bb]uilder|[Bb]uilder.*[Rr]eply", re.IGNORECASE)


def check_no_ghost_reply(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            # Check class definitions
            m = _CLASS_DEF.search(line)
            if m:
                name = m.group(1)
                if name not in CANONICAL_REPLY_NAMES:
                    if _BUILDER_PATTERN.search(name):
                        violations.append(Violation(
                            relpath, i, "NO_GHOST_REPLY",
                            f"ERROR: Rogue reply builder class '{name}' — "
                            f"only canonical ReplyBuilder is allowed",
                        ))
                    else:
                        violations.append(Violation(
                            relpath, i, "NO_GHOST_REPLY",
                            f"WARN: Class '{name}' contains 'reply' — "
                            f"verify this is not reimplementing Reply infrastructure",
                        ))
            # Check function definitions
            m = _FUNC_DEF.search(line)
            if m:
                name = m.group(1)
                if name not in CANONICAL_REPLY_NAMES:
                    if _BUILDER_PATTERN.search(name):
                        violations.append(Violation(
                            relpath, i, "NO_GHOST_REPLY",
                            f"ERROR: Rogue reply builder function '{name}'",
                        ))
                    else:
                        violations.append(Violation(
                            relpath, i, "NO_GHOST_REPLY",
                            f"WARN: Function '{name}' contains 'reply'",
                        ))
    return violations


# ============================================================================
# Check: NO_FAKE_METHODS — rb.info(), rb.warn(), rb.fail() must not exist
# ============================================================================

_FAKE_RB = re.compile(r"\brb\.(info|warn|fail)\(")


def check_no_fake_methods(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            m = _FAKE_RB.search(line)
            if m:
                violations.append(Violation(
                    relpath, i, "NO_FAKE_METHODS",
                    f"rb.{m.group(1)}() does not exist — "
                    f"use rb.success/invalid/denied/error only",
                ))
    return violations


# ============================================================================
# Check: SINGLE_REGISTRY — only reply_codes.py; no reply_registry imports
# ============================================================================

_REGISTRY_IMPORT = re.compile(r"reply_registry")


def check_single_registry(root: Path, files: list[Path]) -> list[Violation]:
    violations = []

    # Check that reply_registry.py doesn't exist
    legacy = root / "src" / "ck3raven" / "core" / "reply_registry.py"
    if legacy.exists():
        violations.append(Violation(
            str(legacy.relative_to(root)).replace("\\", "/"), 1, "SINGLE_REGISTRY",
            "Legacy reply_registry.py still exists — must be deleted",
        ))

    # Check no files import from it
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if _REGISTRY_IMPORT.search(line):
                violations.append(Violation(
                    relpath, i, "SINGLE_REGISTRY",
                    f"Reference to legacy reply_registry — use reply_codes only",
                ))
    return violations


# ============================================================================
# Check: CANONICAL_LOGGER — must use ck3lens.logging, not stdlib/print
# ============================================================================

_STDLIB_LOGGING = re.compile(r"^\s*import\s+logging\b|^\s*from\s+logging\s+import")
_PRINT_CALL = re.compile(r"\bprint\s*\(")
# Acceptable print usages: in __main__ block, exception handler stderr fallback
_IN_MAIN = re.compile(r"^if\s+__name__\s*==")


def check_canonical_logger(root: Path, files: list[Path]) -> list[Violation]:
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        # Skip logging.py itself (it IS the canonical logger)
        if relpath.endswith("logging.py"):
            continue
        source = pyfile.read_text(encoding="utf-8")
        in_main_block = False
        for i, line in enumerate(source.splitlines(), 1):
            if _IN_MAIN.match(line):
                in_main_block = True
            # stdlib logging import
            if _STDLIB_LOGGING.match(line):
                violations.append(Violation(
                    relpath, i, "CANONICAL_LOGGER",
                    "Import of stdlib logging — use ck3lens.logging instead",
                ))
            # print() calls (except in __main__ blocks and safety.py exception handler)
            if _PRINT_CALL.search(line) and not in_main_block:
                if "stderr" not in line and "sys.stderr" not in line:
                    violations.append(Violation(
                        relpath, i, "CANONICAL_LOGGER",
                        f"print() call — use canonical logger (ck3lens.logging) instead",
                    ))
    return violations


# ============================================================================
# Check: REDUNDANT_TRACE — trace.log() that duplicates decorator output
# ============================================================================

_TRACE_LOG = re.compile(r'trace\.log\(\s*"([^"]+)"')


def check_redundant_trace(tools: list[ToolInfo]) -> list[Violation]:
    """Flag trace.log() calls in tool functions that duplicate decorator logging."""
    violations = []
    for t in tools:
        lines = t.body.splitlines()
        for idx, line in enumerate(lines):
            m = _TRACE_LOG.search(line)
            if not m:
                continue
            cat = m.group(1)
            # If trace.log is right before a return rb.*(), it's likely redundant
            if idx + 1 < len(lines):
                next_line = lines[idx + 1].strip()
                if next_line.startswith("return rb."):
                    violations.append(Violation(
                        t.file, t.def_line + idx, "REDUNDANT_TRACE",
                        f"Tool '{t.name}': trace.log('{cat}') immediately before "
                        f"return rb.*() — decorator already logs tool_end",
                    ))
    return violations


# ============================================================================
# Check: AREA_HEURISTIC — tool name → expected AREA mapping
# ============================================================================

def check_area_heuristic(tools: list[ToolInfo]) -> list[Violation]:
    """Flag codes using unexpected AREAs for their tool."""
    violations = []
    for t in tools:
        expected_areas = TOOL_AREA_MAP.get(t.name)
        if expected_areas is None:
            continue  # No mapping = no check
        allowed = expected_areas | UNIVERSAL_AREAS

        for i, line in enumerate(t.body.splitlines(), t.def_line):
            for cm in _RB_CALL.finditer(line):
                code = cm.group(2)
                m = CODE_PATTERN.match(code)
                if m:
                    area = m.group(2)
                    if area not in allowed:
                        violations.append(Violation(
                            t.file, i, "AREA_HEURISTIC",
                            f"Tool '{t.name}': code {code} uses AREA '{area}' — "
                            f"expected one of {sorted(allowed)}",
                        ))
    return violations


# ============================================================================
# Check: RB_CONSTRUCTOR — ReplyBuilder first arg must be TraceInfo
# ============================================================================

def check_rb_constructor(root: Path, files: list[Path]) -> list[Violation]:
    """ReplyBuilder first arg must be TraceInfo, not dict literal."""
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        # Skip safety.py — it defines ReplyBuilder and has docstring examples
        if relpath.endswith("safety.py"):
            continue
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if _RB_CONSTRUCTOR_DICT.search(line):
                violations.append(Violation(
                    relpath, i, "RB_CONSTRUCTOR",
                    "ReplyBuilder({...}) — first arg must be TraceInfo, not dict",
                ))
    return violations


# ============================================================================
# Check: RB_SCHEMA — rb.*() must include required 'data' positional arg
# ============================================================================

def check_rb_data_required(root: Path, files: list[Path]) -> list[Violation]:
    """rb.success/invalid/denied/error must have data as 2nd positional arg."""
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        # Skip safety.py — it defines the methods
        if relpath.endswith("safety.py"):
            continue
        source = pyfile.read_text(encoding="utf-8")

        # Pattern 1: rb.method('CODE', message=...) — data skipped or mispositioned
        for m in _RB_SKIP_DATA.finditer(source):
            line_num = source[:m.start()].count("\n") + 1
            violations.append(Violation(
                relpath, line_num, "RB_SCHEMA",
                f"rb.{m.group(1)}(code, {m.group(2)}=...) — 'data' must be 2nd arg "
                f"(before {m.group(2)}=)",
            ))

        # Pattern 2: rb.method('CODE') — no data at all
        for m in _RB_NO_DATA_ARG.finditer(source):
            line_num = source[:m.start()].count("\n") + 1
            violations.append(Violation(
                relpath, line_num, "RB_SCHEMA",
                f"rb.{m.group(1)}(code) — missing required 'data' arg",
            ))
    return violations


# ============================================================================
# Check: REPLY_ATTR — no non-existent Reply attribute names
# ============================================================================

def check_reply_wrong_attr(root: Path, files: list[Path]) -> list[Violation]:
    """Flag known-wrong Reply attribute names like .code_type."""
    violations = []
    for pyfile in files:
        if _should_skip(pyfile, root):
            continue
        relpath = str(pyfile.relative_to(root)).replace("\\", "/")
        for i, line in enumerate(pyfile.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            m = _WRONG_REPLY_ATTR.search(line)
            if m:
                wrong = m.group(1)
                fix = WRONG_ATTR_FIXES.get(wrong, "???")
                violations.append(Violation(
                    relpath, i, "REPLY_ATTR",
                    f".{wrong} is not a Reply attribute — use .{fix}",
                ))
    return violations


# ============================================================================
# Helpers
# ============================================================================

def _collect_registered_codes(root: Path) -> set[str]:
    """Collect all codes from the canonical registry (reply_codes.py only)."""
    codes: set[str] = set()
    rp = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    if rp.exists():
        for m in re.finditer(r'ReplyCode\("([^"]+)"', rp.read_text(encoding="utf-8")):
            codes.add(m.group(1))
    return codes


def _validate_code(code: str, filepath: str, line: int) -> list[Violation]:
    """Validate a single reply code string."""
    violations = []
    m = CODE_PATTERN.match(code)
    if not m:
        violations.append(Violation(
            filepath, line, "REPLY_CODES",
            f"Code {code!r} doesn't match LAYER-AREA-TYPE-NNN",
        ))
        return violations

    layer, _area, rtype, _num = m.groups()

    if layer not in VALID_LAYERS:
        violations.append(Violation(
            filepath, line, "REPLY_CODES",
            f"Unknown layer {layer!r} in {code}",
        ))

    if layer in LAYER_ALLOWED_TYPES and rtype not in LAYER_ALLOWED_TYPES[layer]:
        allowed = sorted(LAYER_ALLOWED_TYPES[layer])
        violations.append(Violation(
            filepath, line, "LAYER_OWNERSHIP",
            f"{layer} cannot emit {rtype} (allowed: {allowed}) — {code}",
        ))

    return violations


def _in_legacy_table(source: str, line_num: int) -> bool:
    """Check if a line is inside the LEGACY_TO_CANONICAL dict."""
    lines = source.splitlines()
    # Walk backwards from line to find if we're inside LEGACY_TO_CANONICAL = {
    in_dict = False
    brace_depth = 0
    for i in range(line_num - 1, max(0, line_num - 80), -1):
        ln = lines[i] if i < len(lines) else ""
        if "LEGACY_TO_CANONICAL" in ln and "{" in ln:
            return True
        if "}" in ln:
            brace_depth += 1
        if "{" in ln:
            brace_depth -= 1
            if brace_depth < 0:
                return False
    return False


def _should_skip(filepath: Path, root: Path) -> bool:
    rel = str(filepath.relative_to(root)).replace("\\", "/")
    return any(pat in rel for pat in SKIP_PATTERNS)


# ============================================================================
# Main Entry Point
# ============================================================================

def tasl(root: Path | None = None, explicit_files: list[str] | None = None) -> list[Violation]:
    """
    Run all Tool Architecture Standards checks.

    Args:
        root: Repository root path.
        explicit_files: If provided, scan only these files (relative to root).

    Returns list of violations. Empty list = all standards met.
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent

    files = collect_files(root, explicit_files)
    violations: list[Violation] = []

    # 1. Discover tools and check per-tool standards
    tools = discover_tools(root)
    violations.extend(check_safe_wrapper_and_preamble(tools))

    # 2. Reply code format + layer ownership (registry itself)
    violations.extend(check_registry_codes(root))

    # 3. Reply code format + layer ownership (in source)
    violations.extend(check_reply_codes_in_source(root, files))

    # 4. No parallel result types
    violations.extend(check_no_parallel_types(root, files))

    # 5. Dict-returning functions
    violations.extend(check_dict_return(root, files))

    # 6. Trace category compliance
    violations.extend(check_trace_categories(root, files))

    # 7. Orphan codes
    violations.extend(check_orphan_codes(root, files))

    # 8. Codes must go through rb.*()
    violations.extend(check_codes_via_rb(tools))

    # 9. Every return in tool functions via rb.*()
    violations.extend(check_all_returns_via_rb(tools))

    # 10. No ghost Reply/Builder reimplementations
    violations.extend(check_no_ghost_reply(root, files))

    # 11. No fake rb methods
    violations.extend(check_no_fake_methods(root, files))

    # 12. Single registry enforcement
    violations.extend(check_single_registry(root, files))

    # 13. Canonical logger (no stdlib logging, no print)
    violations.extend(check_canonical_logger(root, files))

    # 14. Redundant trace.log() calls
    violations.extend(check_redundant_trace(tools))

    # 15. AREA heuristic
    violations.extend(check_area_heuristic(tools))

    # 16. ReplyBuilder constructor arg validation
    violations.extend(check_rb_constructor(root, files))

    # 17. rb.*() data param required
    violations.extend(check_rb_data_required(root, files))

    # 18. Wrong Reply attribute names
    violations.extend(check_reply_wrong_attr(root, files))

    # 19. Impl/internal function Reply compliance
    impls = discover_impl_functions(root, files)
    violations.extend(check_impl_reply(impls))

    return violations


def main():
    parser = argparse.ArgumentParser(
        description="TASL — Tool Architecture Standards Linter",
    )
    parser.add_argument(
        "--files", nargs="*",
        help="Specific files to scan (relative to repo root). "
             "If omitted, scans the full MCP toolchain.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent.parent
    violations = tasl(root, explicit_files=args.files)

    # ── Summary ─────────────────────────────────────────────────────────
    tools = discover_tools(root)
    files_for_summary = collect_files(root, explicit_files=args.files)
    impls = discover_impl_functions(root, files_for_summary)

    if not violations:
        print(f"TASL: CLEAN — {len(tools)} tools, {len(impls)} impl functions, all standards met")
        sys.exit(0)

    # Group by rule
    by_rule: dict[str, list[Violation]] = defaultdict(list)
    for v in violations:
        by_rule[v.rule].append(v)

    print(f"TASL: {len(violations)} violation(s) across {len(tools)} tools + {len(impls)} impl functions\n")

    # Show per-rule breakdown
    for rule in sorted(by_rule):
        items = by_rule[rule]
        print(f"  [{rule}] {len(items)} violation(s)")
    print()

    # Detail
    for rule in sorted(by_rule):
        items = by_rule[rule]
        print(f"[{rule}] ({len(items)})")
        for v in items:
            print(f"  {v.file}:{v.line} — {v.message}")
        print()

    sys.exit(1)


if __name__ == "__main__":
    main()
