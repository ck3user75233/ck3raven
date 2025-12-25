"""
Guards package for pre-commit and CI validation.

Includes:
- code_diff_guard: Prevents duplicate implementations and shadow pipelines
"""
from .code_diff_guard import run_guard, run_guard_on_diff, GuardResult, Violation

__all__ = ["run_guard", "run_guard_on_diff", "GuardResult", "Violation"]
