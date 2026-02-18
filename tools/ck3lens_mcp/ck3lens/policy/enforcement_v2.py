"""
Enforcement v2 — THE single gate for all mutation decisions.

Canonical Architecture Rule 1: only this module may deny operations.

Walks capability_matrix_v2 data structures:
  1. is_read_command(tool, command) -> True? immediate success (visibility already checked by WA)
  2. find_mutation_rule(mode, root_key, subdirectory, tool, command) -> rule or None
  3. None -> DENY (no rule governs this command at this location)
  4. Rule found -> check conditions with **context -> all pass? ALLOW : DENY

Returns Reply (the canonical type), never a parallel concept.
Denial codes are produced HERE, not by conditions. Conditions just return True/False.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from typing import Any

from ck3raven.core.reply import Reply
from ..capability_matrix_v2 import (
    is_read_command,
    find_mutation_rule,
)


def enforce(
    rb: Any,           # ReplyBuilder -- passed from tool handler
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
        Reply -- success or denied.
    """
    # 1. Reads pass immediately -- visibility already checked by WA
    if is_read_command(tool, command):
        return rb.success("EN-READ-S-001", {})

    # 2. Find the mutation rule governing this (tool, command) at this location
    rule = find_mutation_rule(mode, root_key, subdirectory, tool, command)

    # 3. No rule -> DENY
    if rule is None:
        return rb.denied("EN-GATE-D-001", {
            "detail": f"No mutation rule for ({tool}, {command}) at ({mode}, {root_key}, {subdirectory})",
        })

    # 4. Check conditions -- all must pass
    failed = [c.name for c in rule.conditions if not c.check(**context)]
    if failed:
        return rb.denied("EN-COND-D-001", {
            "failed_conditions": failed,
            "tool": tool,
            "command": command,
        })

    return rb.success("EN-WRITE-S-001", {})
