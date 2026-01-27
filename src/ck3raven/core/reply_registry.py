"""
Canonical Reply Registry - Single Source of Truth for Reply Codes.

This registry defines all valid reply codes. Codes are stable identifiers;
messages may evolve but codes must not change meaning.

Code Format: LAYER-SUBSYSTEM-REPLYTYPE-NNN
    Layers: MCP, WA, EN, CT, DB, PARSE, LEARN, GIT

Rules:
    - Never reuse codes
    - Never change semantics of an existing code
    - If message needs to change, change message only, not code
    - Agents must branch on code or reply_type, NEVER on message text
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


ReplyType = Literal["S", "I", "D", "E"]
Layer = Literal["MCP", "WA", "EN", "CT", "DB", "PARSE", "LEARN", "GIT"]


@dataclass(frozen=True)
class ReplyCode:
    """Definition of a reply code in the registry."""
    code: str
    reply_type: ReplyType
    layer: Layer
    semantics: str
    message_template: str
    required_data_fields: tuple[str, ...] = ()
    
    def format_message(self, **params) -> str:
        """Format the message template with provided parameters."""
        try:
            return self.message_template.format(**params)
        except KeyError:
            return self.message_template


# =============================================================================
# Registry Definition
# =============================================================================

_REGISTRY_LIST: List[ReplyCode] = [
    # =========================================================================
    # MCP / System (Transport & Wrapper)
    # =========================================================================
    ReplyCode(
        code="MCP-SYS-S-900",
        reply_type="S",
        layer="MCP",
        semantics="Tool completed successfully.",
        message_template="Tool completed successfully.",
    ),
    ReplyCode(
        code="MCP-SYS-I-901",
        reply_type="I",
        layer="MCP",
        semantics="Tool completed; no changes required.",
        message_template="Tool completed; no changes required.",
    ),
    ReplyCode(
        code="MCP-SYS-D-902",
        reply_type="D",
        layer="MCP",
        semantics="Tool refused due to missing required input fields.",
        message_template="Missing required fields: {missing}",
        required_data_fields=("missing",),
    ),
    ReplyCode(
        code="MCP-SYS-D-903",
        reply_type="D",
        layer="MCP",
        semantics="Tool refused because operation not supported in this mode.",
        message_template="Operation not supported in {mode} mode.",
        required_data_fields=("mode",),
    ),
    ReplyCode(
        code="MCP-SYS-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Unhandled exception occurred during tool execution.",
        message_template="Unhandled exception: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="MCP-SYS-E-002",
        reply_type="E",
        layer="MCP",
        semantics="Serialization failure: Reply could not be converted to transport dict.",
        message_template="Serialization failure: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="MCP-SYS-E-003",
        reply_type="E",
        layer="MCP",
        semantics="Tool returned non-Reply type (contract violation).",
        message_template="Tool returned {actual_type}, expected Reply.",
        required_data_fields=("actual_type",),
    ),
    ReplyCode(
        code="MCP-SYS-E-004",
        reply_type="E",
        layer="MCP",
        semantics="Trace/session context unavailable or invalid.",
        message_template="Trace context unavailable.",
    ),
    
    # =========================================================================
    # WorldAdapter / Resolution
    # =========================================================================
    ReplyCode(
        code="WA-RES-S-001",
        reply_type="S",
        layer="WA",
        semantics="Resolved input path to canonical address successfully.",
        message_template="Resolved path to {canonical_path}.",
        required_data_fields=("canonical_path",),
    ),
    ReplyCode(
        code="WA-RES-I-001",
        reply_type="I",
        layer="WA",
        semantics="Resolve produced no match (not found).",
        message_template="No match for path: {input_path}",
        required_data_fields=("input_path",),
    ),
    ReplyCode(
        code="WA-RES-D-001",
        reply_type="D",
        layer="WA",
        semantics="Resolve denied: path is outside configured roots.",
        message_template="Path outside configured roots: {input_path}",
        required_data_fields=("input_path",),
    ),
    ReplyCode(
        code="WA-RES-D-002",
        reply_type="D",
        layer="WA",
        semantics="Resolve denied: root is disabled by configuration.",
        message_template="Root {root_domain} is disabled.",
        required_data_fields=("root_domain",),
    ),
    ReplyCode(
        code="WA-RES-E-001",
        reply_type="E",
        layer="WA",
        semantics="Resolve failed due to internal inconsistency (unexpected state).",
        message_template="Internal resolution error: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="WA-RES-E-002",
        reply_type="E",
        layer="WA",
        semantics="Resolve failed due to invalid input path format.",
        message_template="Invalid path format: {input_path}",
        required_data_fields=("input_path",),
    ),
    
    # =========================================================================
    # Enforcement / Policy + Contracts
    # =========================================================================
    ReplyCode(
        code="EN-WRITE-S-001",
        reply_type="S",
        layer="EN",
        semantics="Write authorized by policy and contract.",
        message_template="Write authorized to {canonical_path}.",
        required_data_fields=("canonical_path",),
    ),
    ReplyCode(
        code="EN-WRITE-D-001",
        reply_type="D",
        layer="EN",
        semantics="Write denied: no active contract permits write.",
        message_template="Write denied: no active contract.",
    ),
    ReplyCode(
        code="EN-WRITE-D-002",
        reply_type="D",
        layer="EN",
        semantics="Write denied: contract scope does not cover this path.",
        message_template="Write denied: path {canonical_path} outside contract scope.",
        required_data_fields=("canonical_path",),
    ),
    ReplyCode(
        code="EN-WRITE-D-003",
        reply_type="D",
        layer="EN",
        semantics="Write denied: forbidden root or domain.",
        message_template="Write denied: {root_domain} is forbidden.",
        required_data_fields=("root_domain",),
    ),
    ReplyCode(
        code="EN-WRITE-D-004",
        reply_type="D",
        layer="EN",
        semantics="Write denied: operation type not permitted (edit vs create vs delete).",
        message_template="Write denied: {op} not permitted.",
        required_data_fields=("op",),
    ),
    ReplyCode(
        code="EN-WRITE-D-005",
        reply_type="D",
        layer="EN",
        semantics="Write denied: policy rule matched.",
        message_template="Write denied by policy rule {policy_rule_id}.",
        required_data_fields=("policy_rule_id",),
    ),
    ReplyCode(
        code="EN-READ-D-001",
        reply_type="D",
        layer="EN",
        semantics="Read denied: path requires elevated permission.",
        message_template="Read denied: elevated permission required for {canonical_path}.",
        required_data_fields=("canonical_path",),
    ),
    ReplyCode(
        code="EN-EXEC-D-001",
        reply_type="D",
        layer="EN",
        semantics="Exec denied: terminal/command execution not permitted.",
        message_template="Exec denied: command execution not permitted.",
    ),
    ReplyCode(
        code="EN-POL-E-001",
        reply_type="E",
        layer="EN",
        semantics="Enforcement evaluation failed (bug / missing rule set).",
        message_template="Enforcement error: {error}",
        required_data_fields=("error",),
    ),
    
    # =========================================================================
    # Contract System (Open/Close Lifecycle)
    # =========================================================================
    ReplyCode(
        code="CT-OPEN-S-001",
        reply_type="S",
        layer="CT",
        semantics="Contract opened successfully.",
        message_template="Contract {contract_id} opened.",
        required_data_fields=("contract_id",),
    ),
    ReplyCode(
        code="CT-OPEN-D-001",
        reply_type="D",
        layer="CT",
        semantics="Contract open denied: invalid scope specification.",
        message_template="Contract open denied: invalid scope.",
    ),
    ReplyCode(
        code="CT-OPEN-D-002",
        reply_type="D",
        layer="CT",
        semantics="Contract open denied: requested permissions exceed profile.",
        message_template="Contract open denied: permissions exceed profile.",
    ),
    ReplyCode(
        code="CT-OPEN-E-001",
        reply_type="E",
        layer="CT",
        semantics="Contract open failed due to system error.",
        message_template="Contract open error: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="CT-CLOSE-S-001",
        reply_type="S",
        layer="CT",
        semantics="Contract closed successfully.",
        message_template="Contract {contract_id} closed.",
        required_data_fields=("contract_id",),
    ),
    ReplyCode(
        code="CT-CLOSE-D-001",
        reply_type="D",
        layer="CT",
        semantics="Contract close denied: required evidence missing.",
        message_template="Contract close denied: evidence missing.",
    ),
    ReplyCode(
        code="CT-CLOSE-D-002",
        reply_type="D",
        layer="CT",
        semantics="Contract close denied: gate outcome requires approval.",
        message_template="Contract close denied: requires approval.",
    ),
    ReplyCode(
        code="CT-CLOSE-D-003",
        reply_type="D",
        layer="CT",
        semantics="Contract close denied: gate outcome is deny.",
        message_template="Contract close denied by gate.",
    ),
    ReplyCode(
        code="CT-CLOSE-E-001",
        reply_type="E",
        layer="CT",
        semantics="Contract close failed due to system error.",
        message_template="Contract close error: {error}",
        required_data_fields=("error",),
    ),
    
    # =========================================================================
    # Database Access
    # =========================================================================
    ReplyCode(
        code="DB-READ-S-001",
        reply_type="S",
        layer="DB",
        semantics="DB query succeeded.",
        message_template="Query returned {row_count} rows.",
        required_data_fields=("row_count",),
    ),
    ReplyCode(
        code="DB-READ-I-001",
        reply_type="I",
        layer="DB",
        semantics="DB query returned no rows.",
        message_template="Query returned no rows.",
    ),
    ReplyCode(
        code="DB-READ-D-001",
        reply_type="D",
        layer="DB",
        semantics="DB read denied by policy (if DB access gated).",
        message_template="Database access denied.",
    ),
    ReplyCode(
        code="DB-READ-E-001",
        reply_type="E",
        layer="DB",
        semantics="DB unavailable (cannot open).",
        message_template="Database unavailable: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="DB-READ-E-002",
        reply_type="E",
        layer="DB",
        semantics="DB query failed (SQL error).",
        message_template="Query failed: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="DB-READ-E-003",
        reply_type="E",
        layer="DB",
        semantics="DB schema/version mismatch.",
        message_template="Schema mismatch: {error}",
        required_data_fields=("error",),
    ),
    
    # =========================================================================
    # Parser / AST
    # =========================================================================
    ReplyCode(
        code="PARSE-AST-S-001",
        reply_type="S",
        layer="PARSE",
        semantics="Parsed content into AST successfully.",
        message_template="Parsed {node_count} nodes.",
        required_data_fields=("node_count",),
    ),
    ReplyCode(
        code="PARSE-AST-D-001",
        reply_type="D",
        layer="PARSE",
        semantics="Parse refused: unsupported file type or format.",
        message_template="Unsupported format: {format}",
        required_data_fields=("format",),
    ),
    ReplyCode(
        code="PARSE-AST-E-001",
        reply_type="E",
        layer="PARSE",
        semantics="Parse failed due to syntax error (include location).",
        message_template="Syntax error at line {line}: {error}",
        required_data_fields=("line", "error"),
    ),
    ReplyCode(
        code="PARSE-AST-E-002",
        reply_type="E",
        layer="PARSE",
        semantics="Parse failed due to internal parser error.",
        message_template="Parser error: {error}",
        required_data_fields=("error",),
    ),
    
    # =========================================================================
    # Learner Pipeline
    # =========================================================================
    ReplyCode(
        code="LEARN-DIFF-S-001",
        reply_type="S",
        layer="LEARN",
        semantics="Diff completed and records exported.",
        message_template="Diff completed: {record_count} records.",
        required_data_fields=("record_count",),
    ),
    ReplyCode(
        code="LEARN-DIFF-I-001",
        reply_type="I",
        layer="LEARN",
        semantics="Diff completed; no differences found.",
        message_template="No differences found.",
    ),
    ReplyCode(
        code="LEARN-DIFF-E-001",
        reply_type="E",
        layer="LEARN",
        semantics="Diff failed due to inconsistent inputs or internal error.",
        message_template="Diff error: {error}",
        required_data_fields=("error",),
    ),
    
    # =========================================================================
    # Git Hook
    # =========================================================================
    ReplyCode(
        code="GIT-HOOK-D-001",
        reply_type="D",
        layer="GIT",
        semantics="Commit blocked: active contract missing close receipt.",
        message_template="Commit blocked: contract not closed.",
    ),
    ReplyCode(
        code="GIT-HOOK-D-002",
        reply_type="D",
        layer="GIT",
        semantics="Commit blocked: close receipt outcome not AUTO_APPROVE.",
        message_template="Commit blocked: requires approval.",
    ),
    ReplyCode(
        code="GIT-HOOK-E-001",
        reply_type="E",
        layer="GIT",
        semantics="Hook failed due to internal error.",
        message_template="Git hook error: {error}",
        required_data_fields=("error",),
    ),
]


# =============================================================================
# Registry as Dict (for fast lookup)
# =============================================================================

REGISTRY: Dict[str, ReplyCode] = {}


def _build_registry() -> None:
    """Build the registry dict from the list, validating uniqueness."""
    global REGISTRY
    seen_codes: set[str] = set()
    
    for entry in _REGISTRY_LIST:
        if entry.code in seen_codes:
            raise ValueError(f"Duplicate reply code in registry: {entry.code}")
        
        # Validate code format matches reply_type
        parts = entry.code.split("-")
        if len(parts) != 4:
            raise ValueError(f"Invalid code format: {entry.code} (expected LAYER-SUBSYSTEM-TYPE-NNN)")
        
        code_type = parts[2]
        if code_type != entry.reply_type:
            raise ValueError(
                f"Code type mismatch: {entry.code} has type '{code_type}' "
                f"but reply_type is '{entry.reply_type}'"
            )
        
        seen_codes.add(entry.code)
        REGISTRY[entry.code] = entry


def validate_registry() -> None:
    """Validate registry at startup. Raises if invalid."""
    if not REGISTRY:
        _build_registry()


def get_code(code: str) -> Optional[ReplyCode]:
    """Get a reply code definition, or None if not found."""
    if not REGISTRY:
        _build_registry()
    return REGISTRY.get(code)


def get_message(code: str, **params) -> str:
    """Get formatted message for a code."""
    entry = get_code(code)
    if entry is None:
        return f"Unknown code: {code}"
    return entry.format_message(**params)


# Build registry on import
_build_registry()
