"""
Enforcement v2 — THE single gate for all policy decisions.

Canonical Architecture Rule 1: only this module may deny operations.

Walks capability_matrix_v2 data structures:
  1. classify_command(tool, command) → "read" | category | None
  2. "read" → immediate success (visibility already checked by WA)
  3. category → MUTATIONS_MATRIX lookup (subdirectory-specific, then root-level)
  4. No entry → DENY
  5. Conditions check

Returns Reply (the canonical type), never a parallel concept.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from typing import Any

from ck3raven.core.reply import Reply
from ..capability_matrix_v2 import (
    classify_command,
    MUTATIONS_MATRIX,
    MutationRule,
)


def enforce(
    rb: Any,           # ReplyBuilder — passed from tool handler
    mode: str,
    tool: str,
    command: str,
    root_key: str,
    subdirectory: str | None,
    **context: Any,
) -> Reply:
    """
    Single enforcement entry point.

    Args:
        rb: ReplyBuilder from the tool handler (constructs Reply with trace/meta)
        mode: Agent mode ("ck3lens", "ck3raven-dev")
        tool: Tool name (e.g. "ck3_exec", "ck3_file", "ck3_git")
        command: Command/subcommand (e.g. "write", "delete", "commit", or shell string for exec)
        root_key: v2 root key ("repo", "game", "steam", etc.)
        subdirectory: First path component for sub-gating, or None
        **context: Forwarded to condition predicates (e.g. has_contract, exec_signature_valid)

    Returns:
        Reply — success or denied.
    """
    # 1. Classify the tool+command
    category = classify_command(tool, command)

    if category is None:
        return rb.denied("EN-GATE-D-001", {
            "detail": f"Unknown command: ({tool}, {command})",
        })

    # 2. Reads pass immediately — visibility already checked by WA
    if category == "read":
        return rb.success("EN-READ-S-001", {})

    # 3. Mutation — subdirectory-specific lookup first
    rule: MutationRule | None = None
    if subdirectory:
        rule = MUTATIONS_MATRIX.get((mode, category, root_key, subdirectory))

    # 4. Fall back to root-level entry
    if rule is None:
        rule = MUTATIONS_MATRIX.get((mode, category, root_key, None))

    # 5. No entry → DENY
    if rule is None:
        return rb.denied("EN-GATE-D-001", {
            "detail": f"No mutation rule for ({mode}, {category}, {root_key}, {subdirectory})",
        })

    # 6. Conditions check
    denials = [c.denial for c in rule.conditions if not c.check(**context)]
    if denials:
        return rb.denied(denials[0], {"denials": denials})

    return rb.success("EN-WRITE-S-001", {})
