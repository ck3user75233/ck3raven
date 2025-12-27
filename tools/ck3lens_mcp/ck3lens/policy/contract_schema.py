"""
CK3Lens Contract Schema Validation

Validates contract structure based on intent_type requirements.
Each intent type has specific required and optional fields.

Contract Requirements by Intent Type:
-------------------------------------

COMPATCH / BUGPATCH (Write/Edit/Delete):
- targets: List of {mod_id, rel_path} - must resolve to concrete files
- operation: edit | write | delete
- before_after_snippets: Up to 3 blocks (required if files > 0)
- change_summary: Required if more than 3 files
- rollback_plan: How to undo
- acceptance_tests: DIFF_SANITY + VALIDATION

RESEARCH_MOD_ISSUES (Read-Only):
- findings_evidence: DB excerpts and/or log excerpts
- No write operations permitted

RESEARCH_BUGREPORT (Read-Only):
- findings_evidence: Description of issue being reported
- ck3raven_source_access: Optional, limited read-only access

SCRIPT_WIP:
- script_content: The Python script
- script_hash: SHA256 of script content
- syntax_validation: Proof script passed syntax check
- declared_reads: Files script will read
- declared_writes: Files script will write (WIP or active local mods only)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .types import IntentType, AcceptanceTest


# =============================================================================
# CONTRACT SCHEMA DEFINITIONS
# =============================================================================

@dataclass
class ContractTarget:
    """A target file in a write contract."""
    mod_id: str
    rel_path: str
    operation: str = "write"  # write | edit | delete
    
    def to_dict(self) -> dict[str, str]:
        return {
            "mod_id": self.mod_id,
            "rel_path": self.rel_path,
            "operation": self.operation,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContractTarget":
        return cls(
            mod_id=data.get("mod_id", ""),
            rel_path=data.get("rel_path", ""),
            operation=data.get("operation", "write"),
        )


@dataclass
class BeforeAfterSnippet:
    """A before/after code snippet for a file change."""
    file: str
    before: Optional[str] = None  # None for new files
    after: Optional[str] = None   # None for deletions
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "before": self.before,
            "after": self.after,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BeforeAfterSnippet":
        return cls(
            file=data.get("file", ""),
            before=data.get("before"),
            after=data.get("after"),
        )


@dataclass
class WriteContract:
    """
    Contract schema for COMPATCH / BUGPATCH intents.
    """
    intent_type: IntentType
    targets: list[ContractTarget]
    before_after_snippets: list[BeforeAfterSnippet] = field(default_factory=list)
    change_summary: Optional[str] = None
    rollback_plan: Optional[str] = None
    acceptance_tests: list[AcceptanceTest] = field(default_factory=list)
    
    def validate(self) -> tuple[bool, list[str]]:
        """Validate contract structure. Returns (valid, errors)."""
        errors = []
        
        # Intent must be write type
        if self.intent_type not in {IntentType.COMPATCH, IntentType.BUGPATCH}:
            errors.append(f"Invalid intent_type for write contract: {self.intent_type}")
        
        # Must have targets
        if not self.targets:
            errors.append("Write contract must have at least one target")
        
        # Validate targets have required fields
        for i, t in enumerate(self.targets):
            if not t.mod_id:
                errors.append(f"Target {i}: missing mod_id")
            if not t.rel_path:
                errors.append(f"Target {i}: missing rel_path")
            if t.operation not in {"write", "edit", "delete"}:
                errors.append(f"Target {i}: invalid operation '{t.operation}'")
        
        # Must have snippets if targets exist
        if self.targets and not self.before_after_snippets:
            errors.append("Write contract must include before/after snippets")
        
        # Must have change_summary if more than 3 files
        if len(self.targets) > 3 and not self.change_summary:
            errors.append("Write contract with >3 files must include change_summary")
        
        # Must have rollback_plan
        if not self.rollback_plan:
            errors.append("Write contract must include rollback_plan")
        
        # Must include DIFF_SANITY acceptance test
        if AcceptanceTest.DIFF_SANITY not in self.acceptance_tests:
            errors.append("Write contract must include DIFF_SANITY acceptance test")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "targets": [t.to_dict() for t in self.targets],
            "before_after_snippets": [s.to_dict() for s in self.before_after_snippets],
            "change_summary": self.change_summary,
            "rollback_plan": self.rollback_plan,
            "acceptance_tests": [t.value for t in self.acceptance_tests],
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WriteContract":
        intent_type_str = data.get("intent_type", "")
        try:
            intent_type = IntentType(intent_type_str)
        except ValueError:
            intent_type = IntentType.COMPATCH  # Default
        
        targets = [ContractTarget.from_dict(t) for t in data.get("targets", [])]
        snippets = [BeforeAfterSnippet.from_dict(s) for s in data.get("before_after_snippets", [])]
        
        test_strs = data.get("acceptance_tests", [])
        tests = []
        for t in test_strs:
            try:
                tests.append(AcceptanceTest(t))
            except ValueError:
                pass  # Skip invalid tests
        
        return cls(
            intent_type=intent_type,
            targets=targets,
            before_after_snippets=snippets,
            change_summary=data.get("change_summary"),
            rollback_plan=data.get("rollback_plan"),
            acceptance_tests=tests,
        )


@dataclass
class ResearchContract:
    """
    Contract schema for RESEARCH_MOD_ISSUES / RESEARCH_BUGREPORT intents.
    """
    intent_type: IntentType
    findings_evidence: str
    ck3raven_source_access: bool = False  # Only for RESEARCH_BUGREPORT
    
    def validate(self) -> tuple[bool, list[str]]:
        """Validate contract structure. Returns (valid, errors)."""
        errors = []
        
        # Intent must be research type
        if self.intent_type not in {IntentType.RESEARCH_MOD_ISSUES, IntentType.RESEARCH_BUGREPORT}:
            errors.append(f"Invalid intent_type for research contract: {self.intent_type}")
        
        # Must have findings evidence
        if not self.findings_evidence:
            errors.append("Research contract must include findings_evidence")
        
        # ck3raven_source_access only allowed for RESEARCH_BUGREPORT
        if self.ck3raven_source_access and self.intent_type != IntentType.RESEARCH_BUGREPORT:
            errors.append("ck3raven_source_access only allowed for RESEARCH_BUGREPORT intent")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "findings_evidence": self.findings_evidence,
            "ck3raven_source_access": self.ck3raven_source_access,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchContract":
        intent_type_str = data.get("intent_type", "")
        try:
            intent_type = IntentType(intent_type_str)
        except ValueError:
            intent_type = IntentType.RESEARCH_MOD_ISSUES
        
        return cls(
            intent_type=intent_type,
            findings_evidence=data.get("findings_evidence", ""),
            ck3raven_source_access=data.get("ck3raven_source_access", False),
        )


@dataclass
class ScriptContract:
    """
    Contract schema for SCRIPT_WIP intent.
    """
    intent_type: IntentType = IntentType.SCRIPT_WIP
    script_content: str = ""
    script_hash: str = ""
    syntax_validation_passed: bool = False
    declared_reads: list[str] = field(default_factory=list)
    declared_writes: list[str] = field(default_factory=list)
    
    def validate(self) -> tuple[bool, list[str]]:
        """Validate contract structure. Returns (valid, errors)."""
        errors = []
        
        # Intent must be SCRIPT_WIP
        if self.intent_type != IntentType.SCRIPT_WIP:
            errors.append(f"Invalid intent_type for script contract: {self.intent_type}")
        
        # Must have script content
        if not self.script_content:
            errors.append("Script contract must include script_content")
        
        # Must have script hash
        if not self.script_hash:
            errors.append("Script contract must include script_hash")
        
        # Must pass syntax validation
        if not self.syntax_validation_passed:
            errors.append("Script must pass syntax validation before execution")
        
        return len(errors) == 0, errors
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type.value,
            "script_content": self.script_content,
            "script_hash": self.script_hash,
            "syntax_validation_passed": self.syntax_validation_passed,
            "declared_reads": self.declared_reads,
            "declared_writes": self.declared_writes,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScriptContract":
        return cls(
            intent_type=IntentType.SCRIPT_WIP,
            script_content=data.get("script_content", ""),
            script_hash=data.get("script_hash", ""),
            syntax_validation_passed=data.get("syntax_validation_passed", False),
            declared_reads=data.get("declared_reads", []),
            declared_writes=data.get("declared_writes", []),
        )


# =============================================================================
# CONTRACT FACTORY
# =============================================================================

def create_contract(data: dict[str, Any]) -> WriteContract | ResearchContract | ScriptContract:
    """
    Create the appropriate contract type based on intent_type.
    
    Args:
        data: Contract data dictionary
    
    Returns:
        Typed contract object
    
    Raises:
        ValueError: If intent_type is missing or invalid
    """
    intent_type_str = data.get("intent_type")
    if not intent_type_str:
        raise ValueError("Contract must specify intent_type")
    
    try:
        intent_type = IntentType(intent_type_str)
    except ValueError:
        raise ValueError(f"Invalid intent_type: {intent_type_str}")
    
    if intent_type in {IntentType.COMPATCH, IntentType.BUGPATCH}:
        return WriteContract.from_dict(data)
    elif intent_type in {IntentType.RESEARCH_MOD_ISSUES, IntentType.RESEARCH_BUGREPORT}:
        return ResearchContract.from_dict(data)
    elif intent_type == IntentType.SCRIPT_WIP:
        return ScriptContract.from_dict(data)
    else:
        raise ValueError(f"Unhandled intent_type: {intent_type}")


def validate_contract(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate a contract dictionary against schema.
    
    Args:
        data: Contract data dictionary
    
    Returns:
        (valid: bool, errors: list[str])
    """
    try:
        contract = create_contract(data)
        return contract.validate()
    except ValueError as e:
        return False, [str(e)]
