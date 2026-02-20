"""
Enforcement v2 — THE single gate for all operation decisions.

Canonical Architecture Rule 1: only this module may deny operations.

Single path for ALL operations (reads AND mutations):
  1. find_operation_rule(mode, root_key, subdirectory, tool, command) -> rule or None
  2. None -> DENY (no rule governs this operation at this location)
  3. Rule found -> check conditions with **context -> all pass? ALLOW : DENY

Returns Reply (the canonical type), never a parallel concept.
Denial codes are produced HERE, not by conditions. Conditions just return True/False.

Logging: canonical JSONL to ~/.ck3raven/logs/ck3raven-mcp.log
  Category: policy.enforce
  Every enforcement decision is logged at INFO level with full context.

Design brief: docs/Canonical address refactor/v2_enforcement_design_brief.md
"""
from __future__ import annotations

from typing import Any

from ck3raven.core.reply import Reply
from ..capability_matrix_v2 import find_operation_rule


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

    Walks the operations matrix — one path, no bypass branches.
    Finds the matching rule for (tool, command) at (mode, root_key, subdirectory),
    evaluates its conditions, and returns allow or deny.

    Args:
        rb: ReplyBuilder from the tool handler (constructs Reply with trace/meta)
        mode: Agent mode ("ck3lens", "ck3raven-dev")
        tool: Tool name (e.g. "ck3_exec", "ck3_file", "ck3_git")
        command: Command/subcommand (e.g. "write", "delete", "commit", or shell string for exec)
        root_key: v2 root key ("repo", "game", "steam", etc.)
        subdirectory: First path component for sub-gating, or None
        **context: Forwarded to condition predicates (e.g. has_contract, script_host_path)

    Returns:
        Reply -- success or denied.
    """
    from ck3lens.logging import info

    # --- Log entry ---
    # Redact large/sensitive context values for logging
    log_context = {}
    for k, v in context.items():
        if isinstance(v, str) and len(v) > 200:
            log_context[k] = v[:200] + "..."
        else:
            log_context[k] = repr(v)

    info("policy.enforce", "Enforcement entered",
         tool=tool, command=command, mode=mode,
         root_key=root_key, subdirectory=subdirectory,
         context_keys=list(context.keys()), context_summary=log_context)

    # --- 1. Find the operation rule governing this (tool, command) at this location ---
    rule = find_operation_rule(mode, root_key, subdirectory, tool, command)

    if rule is None:
        info("policy.enforce", "DENY: no rule found",
             tool=tool, command=command, mode=mode,
             root_key=root_key, subdirectory=subdirectory,
             code="EN-GATE-D-001")
        return rb.denied("EN-GATE-D-001", {
            "detail": f"No operation rule for ({tool}, {command}) at ({mode}, {root_key}, {subdirectory})",
        })

    # --- Log the matched rule ---
    condition_names = [c.name for c in rule.conditions]
    info("policy.enforce", "Rule matched",
         tool=tool, command=command, mode=mode,
         root_key=root_key, subdirectory=subdirectory,
         condition_count=len(rule.conditions),
         condition_names=condition_names)

    # --- 2. Check conditions — all must pass ---
    if not rule.conditions:
        # No conditions = operation allowed (e.g. reads, unconditioned writes)
        info("policy.enforce", "ALLOW: no conditions on rule",
             tool=tool, command=command, mode=mode,
             root_key=root_key, subdirectory=subdirectory,
             code="EN-WRITE-S-001")
        return rb.success("EN-WRITE-S-001", {})

    # Evaluate each condition, log individual results
    results = {}
    failed = []
    for c in rule.conditions:
        passed = c.check(**context)
        results[c.name] = passed
        if not passed:
            failed.append(c.name)

    info("policy.enforce", "Conditions evaluated",
         tool=tool, command=command, mode=mode,
         root_key=root_key, subdirectory=subdirectory,
         condition_results=results)

    if failed:
        info("policy.enforce", "DENY: conditions failed",
             tool=tool, command=command, mode=mode,
             root_key=root_key, subdirectory=subdirectory,
             failed_conditions=failed, code="EN-GATE-D-001")
        return rb.denied("EN-GATE-D-001", {
            "detail": f"Conditions not met: {failed}",
            "failed_conditions": failed,
            "tool": tool,
            "command": command,
        })

    info("policy.enforce", "ALLOW: all conditions passed",
         tool=tool, command=command, mode=mode,
         root_key=root_key, subdirectory=subdirectory,
         code="EN-WRITE-S-001")
    return rb.success("EN-WRITE-S-001", {})
