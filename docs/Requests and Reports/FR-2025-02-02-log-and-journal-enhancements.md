# Feature Requests: Log Analysis & Journal Enhancements

**Date:** 2025-02-02  
**Requester:** ck3lens agent (on behalf of user)  
**Priority:** High  
**Status:** Proposed

---

## Context

During a debugging session analyzing error logs with 100,000+ errors, several limitations were encountered that hindered the workflow:

1. Logs get wiped when CK3 restarts - no way to analyze from backup
2. Analysis results exist only in chat - no persistent export
3. Journal doesn't capture tool I/O - session reconstruction incomplete

---

## FR-1: Log Source Path Override

### Problem
`ck3_logs` is hardcoded to read from `~/.../Crusader Kings III/logs/`. When the game restarts, logs are wiped. There's no way to:
- Analyze logs saved to backup locations
- Compare historical logs across sessions
- Preserve logs before game restart overwrites them

### Proposed Solution
Add optional `source_path` parameter to `ck3_logs`:

```python
# Current (limited)
ck3_logs(source="error", command="cascades")

# Proposed (flexible)
ck3_logs(source="error", command="cascades", 
         source_path="~/.ck3raven/wip/backups/error_2025-02-02.log")

# Or using canonical addressing
ck3_logs(source="error", command="cascades",
         source_path="wip://log-backups/error_2025-02-02.log")
```

### Acceptance Criteria
- [ ] `source_path` parameter accepts absolute paths or WIP-relative paths
- [ ] All commands (summary, list, cascades, search, read, raw) work with custom paths
- [ ] Validation ensures file exists and is readable
- [ ] Default behavior unchanged when `source_path` not provided

---

## FR-2: Analysis Export to WIP

### Problem
Analysis results from `ck3_logs` commands like `summary`, `cascades`, `list` exist only as tool return values in the chat. There's no way to:
- Persist analysis for later reference
- Share analysis across sessions
- Build historical records of error patterns

### Proposed Solution
Add `export_to` parameter for analysis commands:

```python
# Export cascade analysis to markdown
ck3_logs(source="error", command="cascades",
         export_to="wip://logs/cascade_analysis_2025-02-02.md")

# Export summary with timestamp
ck3_logs(source="error", command="summary",
         export_to="wip://logs/error_summary_{timestamp}.md")

# Export filtered error list
ck3_logs(source="error", command="list", mod_filter="MiniSuperCompatch",
         export_to="wip://logs/msc_errors.md")
```

### Output Format
Markdown with:
- Timestamp and session info header
- Structured tables for data
- Code blocks for raw content
- Cross-references to related files

### Acceptance Criteria
- [ ] `export_to` parameter accepts WIP paths
- [ ] Markdown formatting appropriate for each command type
- [ ] Automatic timestamp substitution with `{timestamp}` placeholder
- [ ] Returns both normal tool result AND confirmation of file written
- [ ] Creates parent directories if needed

---

## FR-3: Journal Complete MCP Trace Capture

### Problem
The journal (`ck3_journal`) archives Copilot Chat sessions but only captures chat messages, not tool call details. This means:
- Cannot reconstruct what tools were called
- Cannot see parameters passed to tools
- Cannot review tool outputs/errors
- Session replay/debugging severely limited

### Current State
Journal captures:
- ✅ User messages
- ✅ Assistant responses (text)
- ❌ Tool invocations
- ❌ Tool parameters
- ❌ Tool results
- ❌ Error states

### Proposed Solution
Enhance journal to optionally capture complete MCP traces:

```python
# Journal entry structure enhancement
{
    "turn_id": "...",
    "user_message": "...",
    "assistant_response": "...",
    "tool_calls": [
        {
            "tool": "ck3_logs",
            "parameters": {"source": "error", "command": "cascades"},
            "result_summary": "98 cascades detected, 100k errors",
            "result_code": "MCP-SYS-S-900",
            "trace_id": "58df9b6e0ebf4f49",
            "duration_ms": 1234
        }
    ]
}
```

### Configuration Options
```python
# In workspace config or journal settings
journal_settings = {
    "capture_tool_calls": True,  # Enable/disable
    "capture_full_results": False,  # Summary vs full (size tradeoff)
    "max_result_size": 10000,  # Truncate large results
    "exclude_tools": ["ck3_ping"]  # Skip noisy tools
}
```

### Acceptance Criteria
- [ ] Tool invocations captured with name and parameters
- [ ] Result summaries or full results (configurable)
- [ ] Trace IDs preserved for cross-referencing with MCP logs
- [ ] Duration/timing captured
- [ ] Error states and codes captured
- [ ] Configurable to manage storage size
- [ ] Backward compatible with existing journal format

---

## Implementation Notes

### Priority Order
1. **FR-1** (Log Source Path) - Highest impact, enables log preservation workflow
2. **FR-2** (Export to WIP) - Medium complexity, high value for documentation
3. **FR-3** (Journal Traces) - Larger change, may require VS Code extension work

### Dependencies
- FR-1 and FR-2 are MCP server changes only
- FR-3 may require coordination between MCP server and VS Code extension

### Related Work
- Consider adding `ck3_logs(command="backup")` helper to copy current logs to WIP
- Consider `ck3_logs(command="compare", path1=..., path2=...)` for diff analysis

---

## User Story

> As a mod compatibility developer, I need to preserve error logs before restarting the game so that I can analyze historical error patterns and track which fixes worked across sessions. I also need my analysis results persisted so I can reference them later without re-running the analysis.

---

*Submitted by ck3lens agent during error log debugging session.*
