from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


class ArtifactFile(BaseModel):
    """
    A single file in an ArtifactBundle.
    
    This is a mode-agnostic representation of a file the agent wants to submit.
    Can be CK3 scripts (ck3lens) or Python files (ck3raven-dev).
    
    Attributes:
        path: Relative path (e.g., "common/traits/my_trait.txt" or "src/module.py")
        format: Content format - ck3_script, localization_yml, or python
        content: The file content
        ck3_file_model: CK3-only file model classification for policy validation:
            - A: New file, no conflicts possible
            - B: Override file (zzz_ prefix), intentional last-wins
            - C: Partial override targeting specific units
            - D: Full replacement of existing file
    """
    path: str
    format: Literal["ck3_script", "localization_yml", "python"] = "ck3_script"
    content: str
    ck3_file_model: Optional[Literal["A", "B", "C", "D"]] = None


# Backwards compatibility alias
PatchFile = ArtifactFile


class DeclaredSymbol(BaseModel):
    """
    A newly introduced symbol declared in an ArtifactBundle.
    
    Attributes:
        type: Symbol type (trait, decision, event, etc.)
        name: Symbol name/identifier
        reason: Why this new symbol is being introduced
        defined_in_path: Path to the artifact file where this symbol is defined
    """
    type: str
    name: str
    reason: Optional[str] = None
    defined_in_path: Optional[str] = None


class Claim(BaseModel):
    """
    An evidence-backed claim made by the agent.
    
    Part of the claims evidence contract - every claim must reference
    tool calls that provide supporting evidence.
    
    Attributes:
        claim_type: Type of claim being made
            - existence: Something exists (symbol, file, behavior)
            - non_existence: Something does NOT exist
            - behavior: How something behaves
            - value: A specific value or state
        subject: What is being claimed (e.g., "trait:brave exists in vanilla")
        evidence_tool_calls: List of trace entry IDs providing evidence
    """
    claim_type: Literal["existence", "non_existence", "behavior", "value"]
    subject: str
    evidence_tool_calls: list[str] = Field(default_factory=list)


class ClaimsManifest(BaseModel):
    """
    Collection of claims attached to a delivery attempt.
    
    The policy validator checks:
    1. Every claim has >= 1 evidence_tool_call
    2. Evidence matches scope rules (playset, vanilla version)
    3. Non-existence claims have ck3_confirm_not_exists evidence
    """
    claims: list[Claim] = Field(default_factory=list)
    
    @property
    def negative_claims(self) -> list[Claim]:
        """Claims asserting non-existence."""
        return [c for c in self.claims if c.claim_type == "non_existence"]


class ArtifactBundle(BaseModel):
    """
    A collection of files the agent wants to deliver.
    
    Mode-agnostic container:
    - ck3lens: produces ArtifactBundle with CK3 script files
    - ck3raven-dev: produces ArtifactBundle with Python files
    
    The policy validator inspects the bundle differently depending on mode.
    """
    target_build_id: Optional[str] = None
    artifacts: list[ArtifactFile] = Field(default_factory=list)
    declared_new_symbols: list[DeclaredSymbol] = Field(default_factory=list)
    touched_units: list[str] = Field(default_factory=list)
    claims_manifest: Optional[ClaimsManifest] = None
    notes: Optional[str] = None
    
    # Backwards compatibility: 'patches' is an alias for 'artifacts'
    @property
    def patches(self) -> list[ArtifactFile]:
        return self.artifacts


# Backwards compatibility alias
PatchDraft = ArtifactBundle

class ValidationMessage(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

class ValidationReport(BaseModel):
    ok: bool
    errors: list[ValidationMessage] = Field(default_factory=list)
    warnings: list[ValidationMessage] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
