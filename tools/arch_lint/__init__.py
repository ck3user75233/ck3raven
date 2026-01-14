"""
arch_lint v2.35 — Modular architecture linter for ck3raven.

Detects architectural violations:
- Permission oracles (can_write, is_allowed, etc.)
- Parallel truth structures (editable_mods, live_mods, etc.)
- Concept explosion (Lens*, PlaysetLens, etc.)
- Raw I/O outside handles
- Path arithmetic outside WorldAdapter
- Mutators outside builder
- Enforcement calls outside boundary modules
- Suspicious comments (hack, workaround, fixme)
- Forbidden filename patterns

Usage:
    python -m tools.arch_lint [root]
    python -m tools.arch_lint --json
    python -m tools.arch_lint --errors-only
    python -m tools.arch_lint --daemon
"""

__version__ = "2.35"
