"""
Contextual Hints for MCP Tool Responses

Provides hint generation for common agent mistakes:
- Contract field validation errors → field checklist
- Empty search results → search guidance
- Write denials → writable paths + escalation

The hints are injected into MCP responses when specific conditions are detected.
"""
from __future__ import annotations
from typing import Optional
from pathlib import Path


class HintEngine:
    """Generate contextual hints based on tool outcomes."""
    
    def for_contract_error(self, error_msg: str, provided_params: dict) -> dict:
        """
        Generate hints for contract validation errors.
        
        Returns checklist showing which required fields are missing.
        """
        # Only hint on "required" or field validation errors
        lower_error = error_msg.lower()
        if "required" not in lower_error and "validation" not in lower_error:
            return {}
        
        # Required fields for contract open
        required_fields = {
            "command": "open, close, cancel, status, list",
            "intent": "bugfix, refactor, feature, documentation, or descriptive string",
            "root_category": "ROOT_REPO, ROOT_CK3RAVEN_DATA, ROOT_GAME, ROOT_STEAM, ROOT_USER_DOCS, etc.",
            "work_declaration": "Required for WRITE operations - must include work_summary and edits[]",
        }
        
        # Build checklist
        checklist = {}
        for field, options in required_fields.items():
            value = provided_params.get(field)
            if value is not None:
                if field == "work_declaration" and isinstance(value, dict):
                    # Check work_declaration sub-fields
                    missing_sub = []
                    if not value.get("work_summary"):
                        missing_sub.append("work_summary")
                    if not value.get("edits") and provided_params.get("operations", []):
                        ops = provided_params.get("operations", [])
                        if any(op in ("WRITE", "DELETE") for op in ops):
                            missing_sub.append("edits[]")
                    if missing_sub:
                        checklist[field] = f"PROVIDED but missing: {', '.join(missing_sub)}"
                    else:
                        checklist[field] = "✓ provided"
                else:
                    checklist[field] = f"✓ {value}"
            else:
                checklist[field] = f"MISSING - one of: {options}"
        
        return {
            "is_user_error": True,
            "this_is_not_a_bug": "Contract requires specific fields. See checklist below.",
            "required_fields": checklist,
            "example": self._build_contract_example(provided_params),
            "work_declaration_schema": {
                "work_summary": "Brief description of the work (required)",
                "work_plan": ["Step 1", "Step 2", "..."],
                "out_of_scope": ["What this does NOT include"],
                "edits": [
                    {
                        "file": "relative/path/to/file.py",
                        "edit_kind": "add | modify | delete | rename",
                        "location": "Description of where in file",
                        "change_description": "What changes are being made"
                    }
                ]
            }
        }
    
    def _build_contract_example(self, provided_params: dict) -> str:
        """Build an example contract open call with all required fields."""
        intent = provided_params.get("intent", "bugfix")
        root_cat = provided_params.get("root_category", "ROOT_REPO")
        
        return (
            f"ck3_contract(command='open', intent='{intent}', root_category='{root_cat}', "
            f"work_declaration={{'work_summary': '...', 'work_plan': ['...'], 'edits': "
            f"[{{'file': '...', 'edit_kind': 'modify', 'location': '...', 'change_description': '...'}}]}})"
        )
    
    def for_empty_search(self, query: str, search_type: str = "unified") -> dict:
        """
        Generate hints when search returns 0 results.
        
        Provides guidance on alternative search strategies before concluding
        that something doesn't exist.
        """
        # Clean query for suggestions
        clean_query = query.strip().strip("%").strip("*")
        
        return {
            "before_concluding_not_found": {
                "1_try_partial": {
                    "why": "Exact match failed - symbol may have prefix/suffix",
                    "try": f"ck3_search(query='%{clean_query}%')"
                },
                "2_check_spelling": {
                    "why": "Spelling variation, underscore vs camelCase, or typo",
                    "tip": "Try common variations: underscores, plurals, past tense"
                },
                "3_search_content": {
                    "why": "String may appear in file content, not symbol names",
                    "try": f"ck3_search(query='{clean_query}', search_type='content')"
                },
                "4_use_confirm_tool": {
                    "why": "Verify exhaustively before claiming not found",
                    "try": f"ck3_confirm_not_exists(symbol='{clean_query}')"
                },
                "5_raw_grep_fallback": {
                    "why": "Database may be incomplete - grep raw files",
                    "try": f"ck3_grep_raw(query='{clean_query}')"
                }
            },
            "warning": "Do NOT conclude 'does not exist' without exhausting these options"
        }
    
    def for_write_denial(
        self, 
        denial_reason: str, 
        target_path: str, 
        mode: str,
        writable_paths: list[str] | None = None
    ) -> dict:
        """
        Generate hints when a write is denied by policy.
        
        Shows where the agent CAN write and how to escalate if needed.
        """
        # Default writable paths if not provided
        if writable_paths is None:
            writable_paths = [
                "~/.ck3raven/wip/ (always writable - drafts, analysis scripts)",
                "Local mods under Documents/Paradox Interactive/Crusader Kings III/mod/",
            ]
        
        # Extract filename for suggestion
        filename = Path(target_path).name if target_path else "draft.txt"
        
        return {
            "is_policy_denial": True,
            "you_can_write_to": writable_paths,
            "suggestion": f"Write to WIP: ck3_file(command='write', mod_name='wip', rel_path='{filename}', content='...')",
            "do_not": [
                "Attempt workarounds to evade this policy",
                "Write to alternate paths hoping to bypass checks",
                "Use shell commands to circumvent file restrictions"
            ],
            "if_policy_seems_wrong": (
                "Escalate to user: explain what you're trying to write and why. "
                "User can grant elevated permissions or switch modes."
            )
        }


# Module-level singleton for convenience
_hint_engine: Optional[HintEngine] = None

def get_hint_engine() -> HintEngine:
    """Get the global HintEngine instance."""
    global _hint_engine
    if _hint_engine is None:
        _hint_engine = HintEngine()
    return _hint_engine
