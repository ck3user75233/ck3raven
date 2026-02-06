# Feature Request: Contextual Hints in MCP Tool Responses

**Priority:** High  
**Component:** tools/ck3lens_mcp  
**Date:** 2026-02-06

---

## Problem Statement

AI agents using MCP tools frequently make avoidable mistakes:

1. **Forget tools exist** - Tell user to do work the agent has tools for
2. **Give up on search too early** - Conclude "doesn't exist" without trying variations
3. **Misinterpret policy denials** - Report "bug in contract tool" when fields are missing
4. **Forget write capabilities** - Say "I can't write" when WIP workspace is available
5. **Attempt policy workarounds** - Try to evade restrictions instead of escalating to user

These patterns are **mechanistically detectable** by the MCP server and can be addressed with contextual hints injected into tool responses.

## Solution Overview

The MCP server already controls the full response dict for every tool call. We can enrich responses with guidance when specific conditions are detected:

```python
@mcp.tool()
def ck3_search(query: str, ...):
    results = do_search(query)
    
    response = {"results": results, "count": len(results)}
    
    # Inject contextual hints based on outcome
    if len(results) == 0:
        response["before_concluding_not_found"] = build_search_guidance(query)
    
    return response
```

The agent receives the enriched response and can act on the hints.

---

## Use Cases

### Case 1: Contract Rejection → Field Checklist

**Trigger:** Contract tool returns error containing "required" or field validation failure

**Current behavior:**
```json
{"error": "intent required for open command"}
```

**Agent misinterprets as:** "There's a bug in the contract tool"

**Proposed response:**
```json
{
  "success": false,
  "error": "Missing required field: intent",
  "is_user_error": true,
  "this_is_not_a_bug": "Contract requires all fields. See checklist below.",
  "required_fields": {
    "command": "open ✓",
    "intent": "MISSING - one of: bugfix, refactor, feature, documentation",
    "root_category": "MISSING - one of: ROOT_REPO, ROOT_CK3RAVEN_DATA, ROOT_GAME, ...",
    "operations": "provided ✓",
    "reason": "optional but recommended"
  },
  "example": "ck3_contract(command='open', intent='documentation', root_category='ROOT_REPO', operations=['WRITE'], reason='Creating bug report')"
}
```

**Detection logic:**
```python
def enrich_contract_error(error_msg: str, provided_params: dict) -> dict:
    if "required" in error_msg.lower():
        required = ["command", "intent", "root_category", "operations"]
        checklist = {}
        for field in required:
            if field in provided_params:
                checklist[field] = f"{provided_params[field]} ✓"
            else:
                checklist[field] = f"MISSING - {get_field_options(field)}"
        
        return {
            "is_user_error": True,
            "this_is_not_a_bug": "Contract requires all fields. See checklist below.",
            "required_fields": checklist,
            "example": build_example_call(provided_params)
        }
    return {}
```

---

### Case 2: Search Returns Empty → Exhaustive Search Guidance

**Trigger:** `ck3_search` returns 0 results

**Current behavior:**
```json
{"results": [], "count": 0}
```

**Agent incorrectly concludes:** "Symbol doesn't exist"

**Proposed response:**
```json
{
  "results": [],
  "count": 0,
  "before_concluding_not_found": {
    "1_try_partial": {
      "why": "Exact match failed - symbol may have prefix/suffix",
      "try": "ck3_search(query='%christian%')"
    },
    "2_try_fuzzy": {
      "why": "Spelling variation or underscore vs camelCase",
      "similar_symbols": ["christianity", "christian_faith", "is_christian"]
    },
    "3_search_recursively": {
      "why": "Symbol may be nested inside blocks, not top-level",
      "try": "ck3_search(query='christian', recursive=true)"
    },
    "4_no_exclusions": {
      "why": "Don't skip gitignored folders, generated files, or 'vendor' paths",
      "try": "ck3_search(query='christian', include_all=true)"
    },
    "5_check_raw_grep": {
      "why": "Database may be incomplete - grep raw files as fallback",
      "try": "ck3_grep_raw(pattern='christian', paths=['common/', 'events/'])"
    }
  },
  "warning": "Do NOT conclude 'does not exist' without exhausting these options"
}
```

**Detection logic:**
```python
def enrich_empty_search(query: str) -> dict:
    return {
        "before_concluding_not_found": {
            "1_try_partial": {
                "why": "Exact match failed - symbol may have prefix/suffix",
                "try": f"ck3_search(query='%{query}%')"
            },
            "2_try_fuzzy": {
                "why": "Spelling variation",
                "similar_symbols": get_fuzzy_matches(query, limit=5)
            },
            "3_search_recursively": {
                "why": "Symbol may be nested inside blocks",
                "try": f"ck3_search(query='{query}', recursive=true)"
            },
            "4_no_exclusions": {
                "why": "Don't skip gitignored/generated/vendor paths",
                "try": f"ck3_search(query='{query}', include_all=true)"
            },
            "5_check_raw_grep": {
                "why": "Database may be incomplete - grep raw files",
                "try": f"ck3_grep_raw(pattern='{query}')"
            }
        },
        "warning": "Do NOT conclude 'does not exist' without exhausting these options"
    }
```

---

### Case 3: Write Denied → Show Writable Paths + Escalation Path

**Trigger:** `ck3_file(command='write')` returns policy denial

**Current behavior:**
```json
{"error": "Cannot write to workshop mod", "success": false}
```

**Agent concludes:** "I can't write files" (forgets WIP, or tries workarounds)

**Proposed response:**
```json
{
  "success": false,
  "error": "Cannot write to workshop mod",
  "is_policy_denial": true,
  "you_can_write_to": [
    "~/.ck3raven/wip/ (drafts, analysis scripts)",
    "C:/Users/nateb/Documents/Paradox Interactive/Crusader Kings III/mod/* (local mods)"
  ],
  "suggestion": "Write draft to WIP: ck3_file(command='write', path='~/.ck3raven/wip/my_draft.txt', ...)",
  "do_not": [
    "Attempt workarounds to evade this policy",
    "Write to alternate paths hoping to bypass checks",
    "Use shell commands to circumvent file restrictions"
  ],
  "if_policy_seems_wrong": "Escalate to user: explain what you're trying to do and why you believe write access is needed. User can grant elevated permissions or switch modes."
}
```

**Detection logic:**
```python
def enrich_write_denial(denial_reason: str, target_path: str, mode: str) -> dict:
    return {
        "is_policy_denial": True,
        "you_can_write_to": get_writable_paths_for_mode(mode),
        "suggestion": f"Write draft to WIP: ck3_file(command='write', path='~/.ck3raven/wip/{Path(target_path).name}', ...)",
        "do_not": [
            "Attempt workarounds to evade this policy",
            "Write to alternate paths hoping to bypass checks",
            "Use shell commands to circumvent file restrictions"
        ],
        "if_policy_seems_wrong": "Escalate to user: explain what you need and why. User can grant permissions or switch modes."
    }
```

---

### Case 4: Mode Init → Structured Tool Awareness

**Trigger:** `ck3_get_mode_instructions` called (once per session)

**Current behavior:** Returns ~4000 char markdown blob with everything

**Problem:** Agent skims it, forgets tools exist, later tells user to do work manually

**Proposed response structure:**
```json
{
  "mode": "ck3lens",
  "purpose": "CK3 mod compatibility patching and error fixing",
  
  "your_tools": {
    "ck3_search": "Find symbols, files, content in database",
    "ck3_file": "Read/write files (read, write, edit, list commands)",
    "ck3_playset": "Get/switch playset, list mods",
    "ck3_conflicts": "Find symbol and file conflicts across mods",
    "ck3_git": "Version control (status, diff, add, commit)",
    "ck3_parse_content": "Validate CK3 script syntax",
    "ck3_validate": "Check if symbol references exist",
    "ck3_logs": "View error logs and game logs"
  },
  
  "write_access": [
    "~/.ck3raven/wip/ (always)",
    "Local mods under Documents/Paradox Interactive/Crusader Kings III/mod/"
  ],
  
  "cannot_write": [
    "Workshop mods (read-only)",
    "Vanilla game files",
    "ck3raven source code (use ck3raven-dev mode)"
  ],
  
  "detailed_docs": "Use ck3_file(command='read', path='docs/TOOLS.md') for full reference",
  
  "db_status": {
    "ready": false,
    "warning": "No symbols extracted - run: python -m qbuilder daemon --fresh"
  }
}
```

**Key changes:**
- Tools listed by name with one-line description
- Write access explicitly listed
- Cannot-write explicitly listed
- Much shorter than current blob
- Detailed docs available on-demand

---

### Case 5: Repeated Similar Calls → Suggest Better Approach

**Trigger:** Agent calls same tool 3+ times with similar parameters in short window

**Example pattern detected:**
```
ck3_file(read, "mod1/common/traits/00_traits.txt")
ck3_file(read, "mod2/common/traits/00_traits.txt") 
ck3_file(read, "mod3/common/traits/00_traits.txt")
```

**Current behavior:** Returns each file, no guidance

**Proposed - on 3rd similar call:**
```json
{
  "content": "...",
  "efficiency_hint": {
    "pattern_detected": "Reading same relative path across multiple mods",
    "better_approach": "ck3_conflicts(command='files', path='common/traits/00_traits.txt')",
    "why": "Shows all mod versions side-by-side with load order context"
  }
}
```

**Detection logic:**
```python
class SessionTracker:
    def __init__(self):
        self.recent_calls = []  # [(tool, params, timestamp), ...]
    
    def record_and_check(self, tool: str, params: dict) -> Optional[dict]:
        self.recent_calls.append((tool, params, time.time()))
        self.recent_calls = self.recent_calls[-20:]  # Keep last 20
        
        # Check for repetitive patterns
        if tool == "ck3_file" and params.get("command") == "read":
            similar = self._find_similar_reads(params)
            if len(similar) >= 2:
                return self._suggest_conflicts_tool(similar)
        
        return None
    
    def _find_similar_reads(self, current_params: dict) -> list:
        """Find recent reads of same relative path in different mods."""
        current_rel = extract_relative_path(current_params.get("path", ""))
        similar = []
        for tool, params, ts in self.recent_calls[-10:]:
            if tool == "ck3_file" and params.get("command") == "read":
                rel = extract_relative_path(params.get("path", ""))
                if rel == current_rel:
                    similar.append(params)
        return similar
```

---

## Implementation Notes

### Where to Add Hint Logic

```
tools/ck3lens_mcp/
├── server.py              # Tool definitions
├── ck3lens/
│   ├── hints.py           # NEW: Hint generation logic
│   ├── session_tracker.py # NEW: Track call patterns
│   └── ...
```

### Hint Injection Pattern

```python
# In server.py or wrapper layer

from ck3lens.hints import HintEngine

hint_engine = HintEngine()

@mcp.tool()
def ck3_search(query: str, ...):
    results = do_search(query)
    response = {"results": results, "count": len(results)}
    
    # Inject hints based on outcome
    hints = hint_engine.for_search(query, results)
    if hints:
        response.update(hints)
    
    return response
```

### Keeping Hints Lightweight

- Hints only added when conditions met (empty results, errors, patterns)
- Normal successful responses unchanged
- Agent can ignore hints if not relevant

---

## Summary Table

| Case | Trigger | Detection | Hint Content |
|------|---------|-----------|--------------|
| Contract fields | Error contains "required" | String match | Field checklist + example |
| Empty search | Results count = 0 | Trivial | Partial/fuzzy/recursive suggestions |
| Write denied | Policy = DENY + write | Policy layer | Writable paths + escalation guidance |
| Mode init | `ck3_get_mode_instructions` | Always (once) | Structured tool list |
| Repeated calls | Same tool 3x similar params | Session tracker | Suggest better tool |

---

## Success Criteria

- Agent stops saying "contract tool has a bug" when fields missing
- Agent exhausts search options before concluding "not found"
- Agent uses WIP workspace when write denied, or escalates to user
- Agent remembers its tool capabilities throughout session
- Agent uses efficient tools (conflicts) instead of manual multi-reads
