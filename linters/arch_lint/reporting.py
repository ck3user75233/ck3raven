from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
import json

@dataclass
class Finding:
    rule_id: str
    severity: str  # ERROR|WARN|INFO|DOC-WARN
    path: str
    line: int
    col: int
    message: str
    evidence: str = ""
    symbol: Optional[str] = None
    suggested_fix: Optional[str] = None
    deprecated: bool = False
    is_doc: bool = False

class Reporter:
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.deprecated_hits: list[Finding] = []
        self.doc_findings: list[Finding] = []
    def add(self, f: Finding) -> None:
        self.findings.append(f)
        if f.deprecated:
            self.deprecated_hits.append(f)
        if f.is_doc or f.severity == "DOC-WARN":
            self.doc_findings.append(f)
    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(asdict(f), ensure_ascii=False) for f in self.findings)
    def render_human(self) -> str:
        c = {"ERROR":0,"WARN":0,"INFO":0,"DOC-WARN":0}
        for f in self.findings:
            c[f.severity] = c.get(f.severity,0)+1

        out: list[str] = []
        out.append(f"Findings: ERROR={c['ERROR']} WARN={c['WARN']} INFO={c['INFO']} DOC-WARN={c['DOC-WARN']}")
        out.append("")
        out.append("== Code Findings ==")
        for f in self.findings:
            if f.is_doc or f.severity == "DOC-WARN":
                continue
            loc = f"{f.path}:{f.line}:{f.col}"
            sym = f" [{f.symbol}]" if f.symbol else ""
            out.append(f"- {f.severity} {f.rule_id} {loc}{sym} -- {f.message}")
            if f.evidence:
                out.append(f"    evidence: {f.evidence[:220]}")
            if f.suggested_fix:
                out.append(f"    fix: {f.suggested_fix}")

        if self.deprecated_hits:
            out.append("")
            out.append("== Deprecated Symbols Still Resident (#deprecated) ==")
            for f in self.deprecated_hits:
                loc = f"{f.path}:{f.line}:{f.col}"
                sym = f" [{f.symbol}]" if f.symbol else ""
                out.append(f"- WARN DEPRECATED {loc}{sym} -- {f.message}")

        if self.doc_findings:
            out.append("")
            out.append("== Docs / Registry Mentions (Segregated) ==")
            for f in self.doc_findings:
                loc = f"{f.path}:{f.line}:{f.col}"
                sym = f" [{f.symbol}]" if f.symbol else ""
                out.append(f"- {f.severity} {f.rule_id} {loc}{sym} -- {f.message}")
                if f.evidence:
                    out.append(f"    evidence: {f.evidence[:220]}")
        return "\n".join(out)
