"""
arch_lint v2.35 — Reporting and output formatting.

Handles:
- Finding dataclass
- Human-readable output
- JSON output
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class Finding:
    """A single lint finding."""
    rule_id: str
    severity: str  # "ERROR", "WARN", "INFO", "DOC-WARN"
    path: str
    line: int
    col: int
    message: str
    evidence: str = ""
    symbol: Optional[str] = None
    suggested_fix: Optional[str] = None
    deprecated: bool = False
    is_doc: bool = False
    
    def __str__(self) -> str:
        loc = f"{self.path}:{self.line}:{self.col}"
        sym = f" [{self.symbol}]" if self.symbol else ""
        return f"{self.severity} {self.rule_id} {loc}{sym} — {self.message}"


class Reporter:
    """Collects and formats findings."""
    
    def __init__(self) -> None:
        self.findings: list[Finding] = []
    
    def add(self, finding: Finding) -> None:
        """Add a finding."""
        self.findings.append(finding)
    
    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "ERROR"]
    
    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("WARN", "DOC-WARN")]
    
    def render_human(self) -> str:
        """Render findings as human-readable text."""
        if not self.findings:
            return "arch_lint v2.35: OK — no findings"
        
        # Sort: errors first, then by path/line
        sorted_findings = sorted(
            self.findings,
            key=lambda f: (f.severity != "ERROR", f.path, f.line, f.col, f.rule_id)
        )
        
        lines = [
            f"arch_lint v2.35",
            f"Errors: {len(self.errors)}  Warnings: {len(self.warnings)}",
            "",
        ]
        
        for f in sorted_findings:
            lines.append(str(f))
            if f.evidence:
                lines.append(f"    {f.evidence}")
            if f.suggested_fix:
                lines.append(f"    -> {f.suggested_fix}")
        
        return "\n".join(lines)
    
    def render_json(self) -> str:
        """Render findings as JSON."""
        return json.dumps(
            [asdict(f) for f in self.findings],
            indent=2,
            default=str,
        )
