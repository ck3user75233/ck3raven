from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

class PatchFile(BaseModel):
    path: str
    format: Literal["ck3_script", "localization_yml"] = "ck3_script"
    content: str

class DeclaredSymbol(BaseModel):
    type: str
    name: str

class PatchDraft(BaseModel):
    target_build_id: Optional[str] = None
    patches: list[PatchFile] = Field(default_factory=list)
    declared_new_symbols: list[DeclaredSymbol] = Field(default_factory=list)
    touched_units: list[str] = Field(default_factory=list)
    notes: Optional[str] = None

class ValidationMessage(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)

class ValidationReport(BaseModel):
    ok: bool
    errors: list[ValidationMessage] = Field(default_factory=list)
    warnings: list[ValidationMessage] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
