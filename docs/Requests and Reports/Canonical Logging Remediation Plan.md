Here is the refined, final **Agent-Facing Request**. It incorporates the "dual-write" architecture and the specific payload requirements (duration, codes) identified in the feedback.

# ---

**AGENT-FACING REQUEST**

## **Canonical Logs — Remediation Plan: "Dual-Write" Implementation**

### **Context (Read Carefully)**

You previously stated that **Phase 1 (Tool-level logging)** was complete. However, objective validation shows that tool executions are **not** appearing in the canonical log (ck3raven-mcp.log), even though they are appearing in the audit trace (traces/\*.jsonl).

**Root Cause:**

The mcp\_safe\_tool wrapper currently only writes to the **Trace/Audit system** (event-sourcing/compliance). It completely omits the **Canonical Debug Logging system** (operational visibility).

**Instruction:**

You must **not** remove or "fix" the existing trace logging. Instead, you must **add** canonical logging alongside it ("dual-write").

## ---

**Deliverable 1 — Explicit Remediation Plan (Required)**

Apply the following changes to tools/ck3lens\_mcp/safety.py.

### **Step 1: Import Canonical Logger**

Add the import to the top of the file:

Python

from ck3lens import logging as canon\_log

### **Step 2: Instrument the "Dual-Write"**

In the wrapper function, locate the existing call to \_log\_tool\_call. **Immediately after it**, add the canonical logging logic.

**Requirements for the new code:**

1. **Frequency:** Run exactly once per tool execution.  
2. **Level Mapping:**  
   * **Success (S)** $\\to$ INFO (Required for visibility)  
   * **Invalid (I)** $\\to$ WARN  
   * **Denied (D)** $\\to$ WARN  
   * **Exception (E)** $\\to$ ERROR  
3. **Payload:** Must include cat, trace\_id, tool\_name, reply\_type, reply\_code, and elapsed\_ms.

**Code Template (Use this logic):**

Python

\# \[EXISTING\] Audit Trace Call (DO NOT TOUCH)  
\_log\_tool\_call(tool\_name, trace\_id, args, kwargs, result\_dict, None, duration\_ms)

\# \[NEW\] Canonical Debug Call (ADD THIS)  
\# Extract common fields  
r\_type \= result.reply\_type  
r\_code \= getattr(result, 'code', 'UNKNOWN')

log\_data \= {  
    "reply\_type": r\_type,  
    "code": r\_code,  
    "elapsed\_ms": duration\_ms  
}

if r\_type \== 'S':  
    canon\_log.info("mcp.tool", f"Tool {tool\_name} succeeded", trace\_id=trace\_id, data=log\_data)  
elif r\_type in ('I', 'D'):  
    \# Add message for warnings  
    log\_data\["msg"\] \= result.message  
    canon\_log.warn("mcp.tool", f"Tool {tool\_name} {'invalid' if r\_type \== 'I' else 'denied'}", trace\_id=trace\_id, data=log\_data)

### **Step 3: Instrument Exceptions**

In the except block, before returning the error reply:

Python

\# \[EXISTING\] Audit Trace Call  
\_log\_exception(trace\_id, tool\_name, e, stack\_trace)

\# \[NEW\] Canonical Debug Call  
canon\_log.error("mcp.tool", f"Tool {tool\_name} failed", trace\_id=trace\_id, data={  
    "error": str(e),  
    "traceback": stack\_trace \# Optional: limit length if needed  
})

## ---

**Deliverable 2 — Log-Level Guarantees (Non-Negotiable)**

You must adhere to this strict mapping. **DEBUG-only logging is a failure.**

| Event | Log Level | Rationale |
| :---- | :---- | :---- |
| **Tool Success** | **INFO** | Default logs must show that the agent took action. |
| **Invalid/Denied** | **WARN** | Operational issues that require attention but aren't crashes. |
| **Exception** | **ERROR** | Critical system failures. |

## ---

**Deliverable 3 — Quality Gates**

Define these gates to confirm completion.

### **Gate 1 — Tool Coverage**

The following must appear in ck3raven-mcp.log when CK3LENS\_LOG\_LEVEL=INFO:

1. **Success:** ck3\_ping $\\to$ INFO entry.  
2. **Invalid:** ck3\_search(query="") $\\to$ WARN entry.  
3. **Denied:** ck3\_file (forbidden path) $\\to$ WARN entry.  
4. **Exception:** Mocked failure $\\to$ ERROR entry.

### **Gate 2 — Log Content**

Every tool log entry must contain:

* cat: mcp.tool  
* trace\_id: (Non-null)  
* tool\_name: (Correct string)  
* elapsed\_ms: (Number)  
* reply\_type: (S/I/D/E)

### **Gate 3 — Retrieval**

Execute debug\_get\_logs(limit=5, source="mcp") and verify the JSON output contains the entries from Gate 1\.

## ---

**Deliverable 4 — Evidence Format (Mandatory)**

When implementation is complete, provide:

1. **Action:** The tool you ran.  
2. **Raw Log Line:** The line from ck3raven-mcp.log.  
3. **Retrieval Output:** The JSON result from debug\_get\_logs.

*No summaries. No interpretation.*

## ---

**Objective**

**Make it impossible for a tool to execute without leaving an observable trace in ck3raven-mcp.log at the default INFO level.**

Do not proceed to implementation until this plan is understood.