"""
TASL — Tool Architecture Standards Linter

Every MCP tool in ck3raven must tick a set of architecture boxes.
TASL checks them statically, fast, no imports required.

Subsumes the former reply_linter.py (merged Feb 12 2026).

Current standards (v1):
  ── Reply System ──────────────────────────────────────────────────
  SAFE_WRAPPER   — @mcp_safe_tool decorator present
  REPLY_TYPE     — -> Reply return annotation
  PREAMBLE       — trace_info + ReplyBuilder initialization
  REPLY_CODES    — code strings match LAYER-AREA-TYPE-NNN format
  LAYER_OWNERSHIP— layer can emit declared reply type
  NO_PARALLEL    — forbidden parallel types (EnforcementResult, etc.)
  DICT_RETURN    — impl functions returning dict instead of Reply
  ORPHAN_CODES   — codes used in source but missing from registries

  ── Logging System ────────────────────────────────────────────────
  TRACE_CATEGORY — trace.log() using canonical log categories

Future candidates (not yet enforced):
  LOG_CANONICAL  — use canonical logger (info/warn/error) not trace.log()
  REDUNDANT_TRACE— trace.log() calls that duplicate mcp_safe_tool decorator
  RETURN_PATHS   — every branch returns via rb.success/invalid/denied/error
  NO_BARE_DICT   — no dict() construction in return position
  ENFORCEMENT_ONLY_DENY — only EN layer code appears in rb.denied() calls
  TEST_COVERAGE  — every tool has a corresponding test
  DOCSTRING      — all tools have MCP-facing docstring

Run:
    python -m tools.compliance.tasl
    python tools/compliance/tasl.py

Exit codes:
    0 = all standards met
    1 = violations found
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import NamedTuple


# ============================================================================
# Configuration
# ============================================================================

# Scan these directories for tool source
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

VALID_LAYERS = {"WA", "EN", "CT", "MCP"}
LAYER_ALLOWED_TYPES = {
    "WA":  {"S", "I", "E"},
    "EN":  {"S", "D", "E"},
    "CT":  {"S", "I", "E"},
    "MCP": {"S", "E", "I"},
}
FORBIDDEN_AREAS = {"OPEN", "CLOSE"}

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


# ============================================================================
# Types
# ============================================================================

class Violation(NamedTuple):
    file: str
    line: int
    rule: str
    message: str


class ToolInfo(NamedTuple):
    """Parsed info about a single @mcp_safe_tool function."""
    name: str
    file: str
    decorator_line: int
    def_line: int
    has_reply_annotation: bool
    has_trace_info: bool
    has_reply_builder: bool
    rb_tool_name: str | None     # tool='...' value in ReplyBuilder()
    body_preview: str            # first ~800 chars of body


# ============================================================================
# Tool Discovery
# ============================================================================

_TOOL_PATTERN = re.compile(
    r"@mcp_safe_tool\s*\n"           # decorator line
    r"def\s+(\w+)\s*\(",             # function name
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

        # Grab body (from def line to next top-level def or decorator, max 100 lines)
        body_start_idx = def_offset  # 1-indexed line of def
        body_lines: list[str] = []
        for i in range(body_start_idx, min(body_start_idx + 100, len(lines))):
            ln = lines[i]
            # Stop at next top-level definition (non-indented def/class/@)
            if body_lines and ln and not ln[0].isspace() and not ln.startswith("#"):
                break
            body_lines.append(ln)
        body = "\n".join(body_lines)
        body_preview = body[:800]

        # Check -> Reply annotation on the def line (may span a few lines)
        def_region = source[m.start():m.start() + 500]
        has_reply = bool(re.search(r"->\s*Reply\s*:", def_region))

        has_trace = "get_current_trace_info()" in body_preview
        has_rb = "ReplyBuilder(" in body_preview

        rb_name_match = _RB_TOOL_NAME.search(body_preview)
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
            body_preview=body_preview,
        ))

    return tools


# ============================================================================
# Standard Checks
# ============================================================================

def check_safe_wrapper_and_preamble(tools: list[ToolInfo]) -> list[Violation]:
    """SAFE_WRAPPER + REPLY_TYPE + PREAMBLE: every tool must have the trifecta."""
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
        # ReplyBuilder tool= should match function name
        if t.has_reply_builder and t.rb_tool_name and t.rb_tool_name != t.name:
            violations.append(Violation(
                t.file, t.def_line, "PREAMBLE",
                f"Tool '{t.name}' has ReplyBuilder(tool='{t.rb_tool_name}') — "
                f"should be '{t.name}'",
            ))
    return violations


def check_reply_codes_in_source(root: Path) -> list[Violation]:
    """REPLY_CODES + LAYER_OWNERSHIP: validate all code strings in source."""
    violations = []
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        for pyfile in dirpath.rglob("*.py"):
            if _should_skip(pyfile, root):
                continue
            source = pyfile.read_text(encoding="utf-8")
            relpath = str(pyfile.relative_to(root))
            for i, line in enumerate(source.splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for cm in CODE_IN_SOURCE.finditer(line):
                    code = cm.group(1)
                    violations.extend(_validate_code(code, relpath, i))
    return violations


def check_registry_codes(root: Path) -> list[Violation]:
    """REPLY_CODES: validate codes in both registry files."""
    violations = []

    # ck3lens registry
    rp = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    if rp.exists():
        lines = rp.read_text(encoding="utf-8").splitlines()
        relpath = str(rp.relative_to(root))
        for i, line in enumerate(lines, 1):
            m = re.search(r'ReplyCode\("([^"]+)"', line)
            if m:
                violations.extend(_validate_code(m.group(1), relpath, i))

    # core registry
    rp = root / "src" / "ck3raven" / "core" / "reply_registry.py"
    if rp.exists():
        lines = rp.read_text(encoding="utf-8").splitlines()
        relpath = str(rp.relative_to(root))
        for i, line in enumerate(lines, 1):
            m = re.search(r'code="([^"]+)"', line)
            if m:
                violations.extend(_validate_code(m.group(1), relpath, i))

    return violations


def check_no_parallel_types(root: Path) -> list[Violation]:
    """NO_PARALLEL: forbidden parallel result types must not exist."""
    violations = []
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        for pyfile in dirpath.rglob("*.py"):
            if _should_skip(pyfile, root):
                continue
            relpath = str(pyfile.relative_to(root))
            for i, line in enumerate(
                pyfile.read_text(encoding="utf-8").splitlines(), 1
            ):
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


def check_dict_return_signatures(root: Path) -> list[Violation]:
    """DICT_RETURN: flag impl functions with -> dict or -> Reply | dict."""
    violations = []
    pattern = re.compile(
        r"def\s+(\w+)\s*\([^)]*\)\s*->\s*"
        r"(dict(?:\[.*?\])?|Reply\s*\|\s*dict|dict\s*\|\s*Reply)"
    )
    # Only check impl files, not the decorator/safety layer
    impl_files = [
        root / "tools" / "ck3lens_mcp" / "unified_tools.py",
        root / "tools" / "ck3lens_mcp" / "server.py",
    ]
    for filepath in impl_files:
        if not filepath.exists():
            continue
        relpath = str(filepath.relative_to(root))
        for i, line in enumerate(
            filepath.read_text(encoding="utf-8").splitlines(), 1
        ):
            m = pattern.search(line)
            if m:
                violations.append(Violation(
                    relpath, i, "DICT_RETURN",
                    f"'{m.group(1)}' returns {m.group(2)} — should return Reply",
                ))
    return violations


def check_trace_categories(root: Path) -> list[Violation]:
    """TRACE_CATEGORY: flag trace.log() calls with non-canonical categories."""
    violations = []
    pattern = re.compile(r'trace\.log\(\s*"([^"]+)"')
    server = root / "tools" / "ck3lens_mcp" / "server.py"
    if not server.exists():
        return violations
    relpath = str(server.relative_to(root))
    for i, line in enumerate(server.read_text(encoding="utf-8").splitlines(), 1):
        m = pattern.search(line)
        if m:
            cat = m.group(1)
            if cat not in CANONICAL_CATEGORIES:
                violations.append(Violation(
                    relpath, i, "TRACE_CATEGORY",
                    f"Non-canonical trace category: '{cat}' "
                    f"(suggest: {_suggest_canonical(cat)})",
                ))
    return violations


def check_orphan_codes(root: Path) -> list[Violation]:
    """ORPHAN_CODES: codes used in source but not registered in either registry."""
    violations = []
    registered = _collect_registered_codes(root)
    if not registered:
        return violations  # Can't check orphans without registries

    # Collect all codes used in source
    for scan_dir in SCAN_DIRS:
        dirpath = root / scan_dir
        if not dirpath.exists():
            continue
        for pyfile in dirpath.rglob("*.py"):
            if _should_skip(pyfile, root):
                continue
            # Skip the registry files themselves — they define, not use
            relpath = str(pyfile.relative_to(root)).replace("\\", "/")
            if relpath.endswith("reply_codes.py") or relpath.endswith("reply_registry.py"):
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
                            f"Code {code!r} used in source but not in either registry",
                        ))
    return violations


# ============================================================================
# Helpers
# ============================================================================

def _collect_registered_codes(root: Path) -> set[str]:
    """Collect all codes from both registries."""
    codes: set[str] = set()

    # ck3lens registry
    rp = root / "tools" / "ck3lens_mcp" / "ck3lens" / "reply_codes.py"
    if rp.exists():
        for m in re.finditer(r'ReplyCode\("([^"]+)"', rp.read_text(encoding="utf-8")):
            codes.add(m.group(1))

    # core registry
    rp = root / "src" / "ck3raven" / "core" / "reply_registry.py"
    if rp.exists():
        for m in re.finditer(r'code="([^"]+)"', rp.read_text(encoding="utf-8")):
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

    layer, area, rtype, _num = m.groups()

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

    if area in FORBIDDEN_AREAS:
        violations.append(Violation(
            filepath, line, "REPLY_CODES",
            f"AREA {area!r} is forbidden (use GATE) — {code}",
        ))

    return violations


def _suggest_canonical(category: str) -> str:
    """Suggest a canonical category for a non-canonical one."""
    cat_lower = category.lower()
    if "contract" in cat_lower:
        for c in ("contract.open", "contract.close", "contract.cancel",
                   "contract.flush", "contract.archive"):
            if c.split(".")[-1] in cat_lower:
                return c
        return "contract.*"
    if "mode" in cat_lower:
        return "session.mode"
    if "repair" in cat_lower:
        return "mcp.repair"
    if any(kw in cat_lower for kw in ("db", "delete", "grep", "search", "parse",
                                       "file_search", "report", "close_db")):
        return "mcp.tool (redundant — decorator already logs)"
    return "mcp.tool (likely redundant — decorator logs this)"


def _should_skip(filepath: Path, root: Path) -> bool:
    rel = str(filepath.relative_to(root)).replace("\\", "/")
    return any(pat in rel for pat in SKIP_PATTERNS)


# ============================================================================
# Main Entry Point
# ============================================================================

def tasl(root: Path | None = None) -> list[Violation]:
    """
    Run all Tool Architecture Standards checks.

    Returns list of violations. Empty list = all standards met.
    """
    if root is None:
        root = Path(__file__).resolve().parent.parent.parent

    violations: list[Violation] = []

    # 1. Discover tools and check per-tool standards
    tools = discover_tools(root)
    violations.extend(check_safe_wrapper_and_preamble(tools))

    # 2. Reply code format + layer ownership (registries)
    violations.extend(check_registry_codes(root))

    # 3. Reply code format + layer ownership (source usage)
    violations.extend(check_reply_codes_in_source(root))

    # 4. No parallel result types
    violations.extend(check_no_parallel_types(root))

    # 5. Dict-returning impl functions (migration frontier)
    violations.extend(check_dict_return_signatures(root))

    # 6. Trace category compliance
    violations.extend(check_trace_categories(root))

    # 7. Orphan codes (used in source but not registered)
    violations.extend(check_orphan_codes(root))

    return violations


def main():
    root = Path(__file__).resolve().parent.parent.parent
    violations = tasl(root)

    # ── Summary ─────────────────────────────────────────────────────────
    tools = discover_tools(root)

    if not violations:
        print(f"TASL: CLEAN — {len(tools)} tools, all standards met")
        sys.exit(0)

    # Group by rule
    by_rule: dict[str, list[Violation]] = defaultdict(list)
    for v in violations:
        by_rule[v.rule].append(v)

    print(f"TASL: {len(violations)} violation(s) across {len(tools)} tools\n")

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
