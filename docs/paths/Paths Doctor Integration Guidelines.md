Here is the content converted into a well-formatted Markdown document, organized for clarity and actionability.

# ---

**Agent-Facing Review & Decisions: Paths Doctor**

## **✅ Overall Assessment**

Your Paths Doctor implementation direction is aligned with the v3 architecture constraints (constants-only paths.py, resolution in WorldAdapter, enforcement via capability matrix \+ invariants).

**Proceed ONLY after incorporating the corrections and decisions below.**

## ---

**🔧 Required Corrections Before Coding**

### **1\. Remediation wording must not imply Doctor creates anything**

* **Context:** Paths Doctor is read-only.  
* **Correction:** Update remediation strings to avoid phrases like "will be created on first use."  
* **Use instead:** "Create manually", "Ensure component X initializes it", or "Run daemon".

### **2\. Missing .ck3raven / missing subdirs default to WARN**

* **Context:** ROOT\_CK3RAVEN\_DATA and its subdirs may legitimately be absent on a first run.  
* **Correction:** The Doctor must not create them. Missing items should be **WARN** (unless explicitly decided otherwise for the specific environment), not ERROR.

### **3\. Resolution cross-check mismatch severity**

* **Correction:** Make mismatches **WARN by default**.  
* **Exception:** Upgrade to **ERROR** only when it clearly indicates a core routing regression (e.g., WIP resolving under REPO, or a REPO file resolving as ROOT\_EXTERNAL).

### **4\. Config health must reflect load \+ parse status**

Do not just check if the file exists. The report must include:

* Config path used.  
* Parse errors (**ERROR**).  
* Missing required keys for required roots (**ERROR**), even if the file exists.

### **5\. OK findings are fine, but don’t print them by default**

* **Correction:** Keep OK findings in the report structure for determinism/testing, but **suppress** them in default CLI output.

## ---

**Decisions (Answering Your Questions)**

### **Q1) OK findings — include by default or only with \--verbose?**

* **Decision:** Show OK findings **only with \--verbose**.  
* **Default CLI output:** ERROR \+ WARN only \+ summary counts.

### **Q2) JSON output — worth implementing for CLI?**

* **Decision:** **Yes, implement \--json.**  
* \--json is for automation.  
* \--verbose controls whether OK findings appear.

### **Q3) MCP tool — add ck3\_paths\_doctor tool?**

* **Decision:** **Yes, add it.**  
* It must be read-only and return the full report in Reply.data.

# ---

**🔴 MUST NOW: Reply & Logging System Integration**

**Non-Optional:** You MUST implement Paths Doctor such that it is explicitly compliant with the **Canonical Reply System** AND the **Canonical Logging System**. Do not conflate CLI flags with either.

## **A) Separation of Concerns (Mandatory Model)**

Treat these as distinct layers:

1. **Paths Doctor logic (Diagnostics)**  
   * Returns PathsDoctorReport.  
   * Uses severities: OK | WARN | ERROR.  
   * **Does not log and does not return Replies.**  
2. **Reply System (Tool contract at MCP boundary)**  
   * Wraps doctor output in a **Reply**.  
   * Reply indicates tool execution outcome, **NOT** doctor severity.  
   * Doctor severities belong inside Reply.data.  
3. **Logging System (Observability)**  
   * Emits structured logs about *running the tool*.  
   * Logs summary, not the full report.  
   * Logging levels are orthogonal to doctor severities.

## **B) Reply System Rules (Implement Exactly)**

The MCP tool returns:

* **Reply(S):** When the tool runs successfully (even if doctor finds ERROR diagnostics).  
* **Reply(I):** For invalid tool arguments.  
* **Reply(E):** For infrastructure failure/crash.

**Required Semantics:**

* reply.type \== S means "tool succeeded".  
* reply.data.ok \== False means "doctor found ERROR findings".  
* **Never** treat doctor ERROR findings as Reply(E/D/W). Those are not tool failures.

## **C) Logging Rules (Implement Exactly)**

* Log execution lifecycle with trace\_id:  
  * "started" (INFO).  
  * "completed" (INFO) with summary counts.  
* **Do not** auto-map doctor WARN/ERROR to log WARN/ERROR.  
* Only use log **ERROR** when invocation fails or tool crashes.

## **D) CLI Flags vs. Systems**

* \--verbose controls CLI presentation only (printing OK findings).  
* \--json controls output format only.  
* **Neither changes Reply type nor logging behavior.**

## **E) Validation Requirement (Test Plan)**

Add a test proving:

1. Doctor finds ERROR diagnostics $\\rightarrow$ Tool returns Reply(S) with data.ok \== False.  
2. Logs contain INFO start \+ INFO completion (no ERROR unless infrastructure fails).

## ---

**Artifact 1: MCP Tool Stub (Reply \+ Logging Wired Correctly)**

**Notes:**

* Adjust imports to match your code layout.  
* This stub assumes access to canonical logger and ReplyBuilder utilities.  
* Focus on the **flow** and **semantics**.

Python

\# ck3lens/mcp\_tools/ck3\_paths\_doctor.py  
from \_\_future\_\_ import annotations

from dataclasses import asdict  
from typing import Any, Optional

\# Adjust imports to your actual codebase  
from ck3lens.paths\_doctor import run\_paths\_doctor  
from ck3lens.reply import Reply  \# or ReplyBuilder / ReplyFactory  
from ck3lens.logging import get\_logger  \# canonical logger accessor

LOG \= get\_logger()

def ck3\_paths\_doctor(  
    \*,  
    include\_resolution\_checks: bool \= True,  
    verbose: bool \= False,  
    json\_output: bool \= False,  
    trace\_id: str \= "no-trace",  
) \-\> Reply:  
    """  
    MCP Tool wrapper for Paths Doctor.

    Reply semantics:  
      \- Reply(S): tool executed successfully, regardless of doctor findings.  
      \- Reply(I): invalid args.  
      \- Reply(E): crash / infrastructure failure.

    Logging semantics:  
      \- INFO start  
      \- INFO completion with summary counts  
      \- ERROR only on crash  
    """

    \# \--- Argument validation \-\> Reply(I) \---  
    if not isinstance(include\_resolution\_checks, bool):  
        return Reply.invalid(  
            code="MCP-VAL-I-001",  
            message="include\_resolution\_checks must be boolean",  
            data={"include\_resolution\_checks": include\_resolution\_checks},  
        )  
    if not isinstance(verbose, bool):  
        return Reply.invalid(  
            code="MCP-VAL-I-001",  
            message="verbose must be boolean",  
            data={"verbose": verbose},  
        )  
    if not isinstance(json\_output, bool):  
        return Reply.invalid(  
            code="MCP-VAL-I-001",  
            message="json\_output must be boolean",  
            data={"json\_output": json\_output},  
        )

    \# \--- Logging: started \---  
    LOG.info(  
        cat="mcp.tool",  
        trace\_id=trace\_id,  
        msg="ck3\_paths\_doctor started",  
        data={  
            "include\_resolution\_checks": include\_resolution\_checks,  
            "verbose": verbose,  
            "json\_output": json\_output,  
        },  
    )

    try:  
        report \= run\_paths\_doctor(include\_resolution\_checks=include\_resolution\_checks)

        \# Prepare payload  
        payload: dict\[str, Any\] \= asdict(report)

        \# Optional CLI formatting is NOT done here; tool returns structured data always.  
        if json\_output:  
            import json  
            payload\["json"\] \= json.dumps(payload, ensure\_ascii=False, indent=2)

        \# Default: include all findings in Reply.data  
        if not verbose:  
            \# Keep full findings in payload\_full for machine usage, but provide filtered findings for human callers  
            payload\["findings\_full"\] \= payload.get("findings", \[\])  
            payload\["findings"\] \= \[f for f in payload.get("findings", \[\]) if f.get("severity") \!= "OK"\]

        \# \--- Logging: completed (INFO regardless of diagnostics) \---  
        summary \= payload.get("summary") or {}  
        LOG.info(  
            cat="mcp.tool",  
            trace\_id=trace\_id,  
            msg="ck3\_paths\_doctor completed",  
            data={  
                "ok": payload.get("ok"),  
                "errors": summary.get("ERROR", 0),  
                "warnings": summary.get("WARN", 0),  
                "oks": summary.get("OK", 0),  
            },  
        )

        return Reply.success(  
            code="MCP-VAL-S-001",  
            message="Paths Doctor completed",  
            data=payload,  
        )

    except Exception as e:  
        LOG.error(  
            cat="mcp.tool",  
            trace\_id=trace\_id,  
            msg="ck3\_paths\_doctor crashed",  
            data={"error": repr(e)},  
        )  
        return Reply.error(  
            code="MCP-SYS-E-001",  
            message="Paths Doctor crashed",  
            data={"error": repr(e)},  
        )

**Key properties this stub enforces:**

* Doctor "ERROR findings" do **not** become Reply(E).  
* Logging remains **INFO** for completion unless the tool crashes.  
* \--verbose / \--json are presentation/format controls only.

## ---

**Artifact 2: System Diagram (Doctor → Reply → Logs)**

Code snippet

flowchart TD  
  A\[User / Agent / CLI\] \--\>|invokes| B\[MCP Tool: ck3\_paths\_doctor\]  
  B \--\>|calls| C\[Paths Doctor: run\_paths\_doctor\]  
  C \--\>|returns| D\[PathsDoctorReport\<br/\>severities: OK/WARN/ERROR\]  
  D \--\>|wrapped into| E\[Reply S/I/E\<br/\>tool outcome only\]  
  B \--\>|emits| F\[Canonical Logs\<br/\>INFO start \+ INFO completed \+ summary\<br/\>ERROR only on crash\]

  subgraph Rules  
    R1\[Doctor severities\<br/\>are diagnostic content\<br/\>never Reply type\]   
    R2\[Reply type reflects tool execution:\<br/\>S=ran, I=bad args, E=crash\]  
    R3\[Logging level is observability:\<br/\>INFO lifecycle; ERROR only on crash\]  
  end

  D \--\> R1  
  E \--\> R2  
  F \--\> R3

**Legend:**

* **Doctor severity:** Content quality/state of configuration.  
* **Reply type:** Tool execution contract.  
* **Log level:** Operational telemetry.  
* *These must never be conflated.*

## ---

**Final "Do This Now" Checklist**

1. \[ \] **Apply Corrections:** Remediation wording, WARN vs ERROR defaults, config health semantics, OK output suppression.  
2. \[ \] **Pure Logic:** Implement Paths Doctor as a pure report generator (no Reply, no logging inside).  
3. \[ \] **MCP Tool:** Add ck3\_paths\_doctor using the stub pattern above.  
4. \[ \] **Logging:** Add structured logs (start \+ completion summary; error only on crash).  
5. \[ \] **Testing:** Add tests proving:  
   * Doctor ERROR findings $\\rightarrow$ Reply(S) with data.ok \== False.  
   * Logs show INFO start \+ INFO completed (no ERROR unless crash).