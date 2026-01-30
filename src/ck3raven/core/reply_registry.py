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
        code="DB-CONN-S-001",
        reply_type="S",
        layer="DB",
        semantics="Database connection closed successfully.",
        message_template="Database connection closed.",
    ),
    ReplyCode(
        code="DB-CONN-E-001",
        reply_type="E",
        layer="DB",
        semantics="Database connection close failed.",
        message_template="Database close failed: {error}",
        required_data_fields=("error",),
    ),
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
    
    # =========================================================================
    # MCP Tool-Specific Codes (FILE-OP, FOLDER-OP, etc.)
    # 
    # These are for tool-level outcomes within the MCP layer.
    # Layer = MCP (tools call these, not lower layers)
    # =========================================================================
    
    # File Operations (ck3_file tool)
    # =========================================================================
    ReplyCode(
        code="FILE-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="File operation completed successfully.",
        message_template="File {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="FILE-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="File write/edit denied by policy.",
        message_template="File write denied: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="FILE-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="File not found in database or filesystem.",
        message_template="File not found: {path}",
        required_data_fields=("path",),
    ),
    ReplyCode(
        code="FILE-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="File operation failed due to internal error.",
        message_template="File operation error: {error}",
        required_data_fields=("error",),
    ),
    
    # Folder Operations (ck3_folder tool)
    # =========================================================================
    ReplyCode(
        code="FOLDER-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Folder operation completed successfully.",
        message_template="Folder {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="FOLDER-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Folder access denied by policy.",
        message_template="Folder access denied: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="FOLDER-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="Folder not found.",
        message_template="Folder not found: {path}",
        required_data_fields=("path",),
    ),
    ReplyCode(
        code="FOLDER-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Folder operation failed due to internal error.",
        message_template="Folder operation error: {error}",
        required_data_fields=("error",),
    ),
    
    # Playset Operations (ck3_playset tool)
    # =========================================================================
    ReplyCode(
        code="PLAYSET-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Playset query completed successfully.",
        message_template="Active playset: {playset_name}",
        required_data_fields=("playset_name",),
    ),
    ReplyCode(
        code="PLAYSET-OP-S-002",
        reply_type="S",
        layer="MCP",
        semantics="Playset switched successfully.",
        message_template="Switched to playset: {playset_name}",
        required_data_fields=("playset_name",),
    ),
    ReplyCode(
        code="PLAYSET-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Invalid command or missing required parameter.",
        message_template="Invalid playset command: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="PLAYSET-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="Playset not found.",
        message_template="Playset not found: {playset_name}",
        required_data_fields=("playset_name",),
    ),
    ReplyCode(
        code="PLAYSET-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Playset operation failed due to internal error.",
        message_template="Playset operation error: {error}",
        required_data_fields=("error",),
    ),
    
    # Git Command Operations (ck3_git tool)
    # =========================================================================
    ReplyCode(
        code="GIT-CMD-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Git command completed successfully.",
        message_template="Git {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="GIT-CMD-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Git command denied by policy.",
        message_template="Git command denied: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="GIT-CMD-D-002",
        reply_type="D",
        layer="MCP",
        semantics="Invalid git command or missing required parameter.",
        message_template="Invalid git command: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="GIT-CMD-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Git command failed due to internal error.",
        message_template="Git command error: {error}",
        required_data_fields=("error",),
    ),
    
    # Repair Operations (ck3_repair tool)
    # =========================================================================
    ReplyCode(
        code="REPAIR-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Repair operation completed successfully.",
        message_template="Repair {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="REPAIR-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Repair denied (wrong mode or requires confirmation).",
        message_template="Repair denied: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="REPAIR-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Repair operation failed due to internal error.",
        message_template="Repair operation error: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="REPAIR-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="Repair dry run - changes would be made.",
        message_template="Dry run - {command} would make changes.",
        required_data_fields=("command",),
    ),
    
    # Exec Operations (ck3_exec tool)
    # =========================================================================
    ReplyCode(
        code="EXEC-CMD-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Command executed successfully.",
        message_template="Command executed: exit_code={exit_code}",
        required_data_fields=("exit_code",),
    ),
    ReplyCode(
        code="EXEC-CMD-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Command denied by policy.",
        message_template="Command denied: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="EXEC-CMD-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Command execution failed.",
        message_template="Command failed: {error}",
        required_data_fields=("error",),
    ),
    
    # Search Operations (ck3_search tool)
    # =========================================================================
    ReplyCode(
        code="SEARCH-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Search completed successfully.",
        message_template="Search complete: {result_count} results.",
        required_data_fields=("result_count",),
    ),
    ReplyCode(
        code="SEARCH-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Search query invalid or missing.",
        message_template="Invalid search: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="SEARCH-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Search failed due to internal error.",
        message_template="Search error: {error}",
        required_data_fields=("error",),
    ),
    
    # Validate Operations (ck3_validate tool)
    # =========================================================================
    ReplyCode(
        code="VALIDATE-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Validation passed.",
        message_template="Validation passed for {target}.",
        required_data_fields=("target",),
    ),
    ReplyCode(
        code="VALIDATE-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Validation target invalid or missing.",
        message_template="Invalid validation request: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="VALIDATE-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="Validation found issues (not a crash, just invalid input).",
        message_template="Validation failed: {error_count} errors found.",
        required_data_fields=("error_count",),
    ),
    ReplyCode(
        code="VALIDATE-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Validation failed due to internal error.",
        message_template="Validation error: {error}",
        required_data_fields=("error",),
    ),
    
    # QBuilder Operations (ck3_qbuilder tool)
    # =========================================================================
    ReplyCode(
        code="QBUILD-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="QBuilder operation completed successfully.",
        message_template="QBuilder {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="QBUILD-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="QBuilder command invalid.",
        message_template="Invalid qbuilder command: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="QBUILD-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="QBuilder operation failed due to internal error.",
        message_template="QBuilder error: {error}",
        required_data_fields=("error",),
    ),
    
    # VS Code IPC Operations (ck3_vscode tool)
    # =========================================================================
    ReplyCode(
        code="VSCODE-IPC-S-001",
        reply_type="S",
        layer="MCP",
        semantics="VS Code IPC operation completed successfully.",
        message_template="VS Code {command} complete.",
        required_data_fields=("command",),
    ),
    ReplyCode(
        code="VSCODE-IPC-D-001",
        reply_type="D",
        layer="MCP",
        semantics="VS Code IPC not available or command invalid.",
        message_template="VS Code IPC unavailable: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="VSCODE-IPC-E-001",
        reply_type="E",
        layer="MCP",
        semantics="VS Code IPC operation failed due to internal error.",
        message_template="VS Code IPC error: {error}",
        required_data_fields=("error",),
    ),
    
    # Contract Operations (ck3_contract tool)
    # =========================================================================
    ReplyCode(
        code="CONTRACT-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Contract opened successfully.",
        message_template="Contract opened: {contract_id}",
        required_data_fields=("contract_id",),
    ),
    ReplyCode(
        code="CONTRACT-OP-S-002",
        reply_type="S",
        layer="MCP",
        semantics="Contract closed successfully.",
        message_template="Contract closed: {contract_id}",
        required_data_fields=("contract_id",),
    ),
    ReplyCode(
        code="CONTRACT-OP-S-003",
        reply_type="S",
        layer="MCP",
        semantics="Contract status retrieved successfully.",
        message_template="Contract status: {status}",
        required_data_fields=("status",),
    ),
    ReplyCode(
        code="CONTRACT-OP-S-004",
        reply_type="S",
        layer="MCP",
        semantics="Contract cancelled successfully.",
        message_template="Contract cancelled: {contract_id}",
        required_data_fields=("contract_id",),
    ),
    ReplyCode(
        code="CONTRACT-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Contract command invalid or missing required parameter.",
        message_template="Invalid contract command: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="CONTRACT-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Contract operation failed due to internal error.",
        message_template="Contract error: {error}",
        required_data_fields=("error",),
    ),
    ReplyCode(
        code="CONTRACT-OP-I-001",
        reply_type="I",
        layer="MCP",
        semantics="No active contract.",
        message_template="No active contract.",
        required_data_fields=(),
    ),
    
    # DB Query Operations (ck3_db_query tool)
    # =========================================================================
    ReplyCode(
        code="DB-QUERY-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Database query completed successfully.",
        message_template="Query returned {row_count} rows.",
        required_data_fields=("row_count",),
    ),
    ReplyCode(
        code="DB-QUERY-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Invalid query or table name.",
        message_template="Invalid query: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="DB-QUERY-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Database query failed due to internal error.",
        message_template="Query error: {error}",
        required_data_fields=("error",),
    ),
    
    # Conflict Detection Operations (ck3_conflicts tool)
    # =========================================================================
    ReplyCode(
        code="CONFLICT-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Conflict detection completed successfully.",
        message_template="Found {conflict_count} conflicts.",
        required_data_fields=("conflict_count",),
    ),
    ReplyCode(
        code="CONFLICT-OP-D-001",
        reply_type="D",
        layer="MCP",
        semantics="Invalid conflict command.",
        message_template="Invalid conflict command: {reason}",
        required_data_fields=("reason",),
    ),
    ReplyCode(
        code="CONFLICT-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Conflict detection failed due to internal error.",
        message_template="Conflict detection error: {error}",
        required_data_fields=("error",),
    ),
    
    # Logs Operations (ck3_logs tool)
    # =========================================================================
    ReplyCode(
        code="LOGS-OP-S-001",
        reply_type="S",
        layer="MCP",
        semantics="Log query completed successfully.",
        message_template="Logs query completed: source={source}, command={command}",
        required_data_fields=("source", "command"),
    ),
    ReplyCode(
        code="LOGS-OP-E-001",
        reply_type="E",
        layer="MCP",
        semantics="Log query failed due to internal error.",
        message_template="Logs error: {error}",
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
