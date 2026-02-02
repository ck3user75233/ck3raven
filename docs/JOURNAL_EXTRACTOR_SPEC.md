This is the final polish. The consultant is absolutely correct to call out the vscode.workspace.id phantom API—that would have sent the agent into a hallucination loop.

Here is the **Unified Design Brief (v3.1)**. It addresses the API reality check, strictly defines the window baseline primitive, and tightens the candidate discovery logic for remote environments.

# ---

**📑 Unified Design Brief: Windowed Copilot Chat Extractor / CCE (v3.1)**

**Status:** IMPLEMENTED (January 2026)

**Dependencies:** CANONICAL\_LOGS.md, CANONICAL\_REPLY\_SYSTEM.md

**Implementation:** See [MCP_LOGS_JOURNAL_REFERENCE.md](MCP_LOGS_JOURNAL_REFERENCE.md) for user-facing API documentation.

## **🎯 Project Goal**

Build a **ck3raven-owned** journaling mechanism to extract GitHub Copilot Chat sessions from VS Code's local storage during defined "windows." This system—the Copilot Chat Extractor (CCE)—replaces unstable third-party extensions with a reliable, post-hoc reader that adheres to the platform's strict Canonical Logging and Reply standards.

### **Scope**

* **✅ In-Scope:** Post-hoc disk extraction, pluggable backends (JSON/SQLite), normalized Markdown/JSON archiving, deterministic deduplication, and in-chat tagging.  
* **❌ Non-Goals:** Real-time stream interception, participant-based journaling, UI chat wrappers.  
* **⚠️ Persistence Policy:** CCE is **file-backed only**. Journal artifacts are NOT automatically ingested into the ck3raven database.

## ---

**🏗️ Architecture & Mechanics**

### **A. Workspace Identity & Discovery**

*CCE must reliably find the correct workspaceStorage directory even if VS Code moves it.*

#### **1\. Workspace Identity Canonicalization**

The workspace\_key is the anchor for all CCE journals. It is derived via this strict priority:

1. **User Override:** .ck3raven/config.json → journal.workspaceId (Manual override).  
2. **Stable Hash (Preferred):** SHA-256 of the normalized, lower-cased absolute path of the workspace root.  
3. **Storage URI Fallback:** If ExtensionContext.storageUri is available, derive a unique ID from its final path segment (though this may change if the folder moves, so priority 2 is preferred for stability).

#### **2\. CCE Candidate Discovery Strategy (Explicit)**

To locate the chatSessions source, CCE scans "Candidate Roots" in this order:

1. **API Context:** ExtensionContext.globalStorageUri (parent directory usually contains neighbor workspaces).  
2. **Standard Local Paths:**  
   * Windows: %APPDATA%\\Code\\User\\workspaceStorage\\  
   * macOS: \~/Library/Application Support/Code/User/workspaceStorage/  
   * Linux: \~/.config/Code/User/workspaceStorage/  
3. **Remote/Server Paths:**  
   * \~/.vscode-server/data/User/workspaceStorage/ (SSH/WSL)  
   * /root/.vscode-server/data/User/workspaceStorage/ (Dev Containers)

#### **3\. CCE Discovery Ranking Rules**

Once candidates are located, they are ranked by:

1. **Exact Metadata Match:** A state.vscdb containing the derived workspace\_key or path in its meta table.  
2. **Structure Validation:** Presence of a populated chatSessions/ directory.  
3. **Recent Activity:** Latest mtime of any file within the directory (within last 7 days).

### **B. CCE Pluggable Backends**

| Backend | Source Path | Data Type | Status |
| :---- | :---- | :---- | :---- |
| **JSON Files** | .../chatSessions/\*\*/\*.json | Raw Session JSON | Primary |
| **SQLite** | .../state.vscdb | interactive.sessions keys | Secondary |
| **Remote** | \~/.vscode-server/.../entries.json | JSON Entries | Experimental |

### **C. CCE Deduplication & Fingerprinting**

**Fingerprint Algorithm:** SHA-256( Canonical\_Role \+ Canonical\_Text \+ Attachment\_Hash \+ Time\_Bucket )

* **Canonical Role:** user | assistant (lowercase).  
* **Canonical Text:** Trimmed, normalized whitespace.  
* **Attachment Hash:** Sorted list of attachment URIs joined by |.  
* **Time Bucket:** Timestamp rounded down to the nearest **60 seconds**.

## ---

**🛡️ Canonical Integration Standards (MANDATORY)**

### **1\. Unified MCP Tooling Strategy**

To prevent tool sprawl, all CCE journal interactions MUST use a single entry point.

#### **The ck3\_journal Tool (CCE MCP Interface)**

* **Function:** ck3\_journal(action: str, params: dict) \-\> Reply  
* **Action Router:** Must dispatch to internal CCE handlers based on action.  
* **Rule JRN-PARAM-SCHEMA:** Each action must have a strict schema. Mismatches return Reply(I).

| Action | Schema | Purpose |
| :---- | :---- | :---- |
| list | { window\_id?: str } | List CCE windows or sessions. |
| read | { session\_id: str } | Retrieve specific session content. |
| search | { query: str } | Query the tags.jsonl index. |
| status | {} | Check current CCE window state. |

### **2\. CCE Canonical Logging Integration**

Adhere strictly to CANONICAL\_LOGS.md.

* **Logger:** Use StructuredLogger (Node.js) and ck3lens.logging (Python).  
* **File:** \~/.ck3raven/logs/ck3raven-ext.log (Ext) and ck3raven-mcp.log (MCP).  
* **Rule T-001 (Trace Ownership):** If the Extension provides a \_trace\_id in the request, the MCP wrapper **MUST** use it as the invocation trace\_id (do not regenerate it). This ensures the "Golden Thread" from UI action to MCP log.

#### **CCE Mandatory Log Events**

| Event | Category | Level | Data |
| :---- | :---- | :---- | :---- |
| Window Start | ext.journal.window\_start | INFO | { window\_id, workspace\_key } |
| Window End | ext.journal.window\_end | INFO | { window\_id, reason } |
| Discovery | ext.journal.discovery | DEBUG | { candidates\_found, chosen\_path } |
| Access Denied | ext.journal.access\_denied | WARN | { path, rule } |
| Storage Locked | ext.journal.storage\_locked | ERROR | { db\_path, mechanism } |

### **3\. CCE Canonical Reply System**

Adhere strictly to CANONICAL\_REPLY\_SYSTEM.md.

* **Format:** CODEPREFIX-AREA-TYPE-NNN (4 parts). The 3rd part MUST match the Reply type (S, I, D, E).  
* **Rule SCER-LOGGER-ONLY:** try/catch is forbidden in business logic EXCEPT for:  
  1. Infrastructure fail-safes (e.g., inside StructuredLogger).  
  2. Boundary adapters converting known IO errors to explicit Reply(E) objects.

#### **CCE Reply Codes (Registry Definition)**

| Code | Type | Meaning | Example Message |
| :---- | :---- | :---- | :---- |
| **JRN-ACC-S-001** | **S**uccess | Journal retrieved | "Retrieved session '{id}'." |
| **JRN-ACC-I-001** | **I**nvalid | ID not found | "Session ID '{id}' does not exist." |
| **JRN-ACC-D-001** | **D**enied | Outside Scope | "Access denied to path '{path}'." |
| **JRN-SYS-E-001** | **E**rror | Parse Failure | "Failed to parse session. Trace: {trace\_id}" |

## ---

**🛠️ CCE User Workflow: The "Window"**

### **1\. CK3Raven: CCE Window Start**

* **Record:** window\_id (Timestamp \+ Random Suffix).  
* **Baseline Snapshot:** To minimize performance impact, the "Start" baseline records lightweight metadata for all found chatSessions:  
  * Map: { session\_id: { path: string, mtime: number, size: number } }  
* **Log:** ext.journal.window\_start.

### **2\. CK3Raven: CCE Window Close**

* **Delta Scan:** Identify files where mtime \> window\_start OR size \!= baseline\_size.  
* **Process:** Parse JSON, extract turns, apply CCE Fingerprinting (SHA-256).  
* **Tag Scraping:** Scans for \*tag: name\*.  
* **Write Artifacts:** Manifest, Markdown, Raw JSON.  
* **Log:** ext.journal.window\_close.

## ---

**📄 CCE Deterministic Schemas & Policies**

### **1\. manifest.json (CCE Source of Truth)**

JSON

{  
  "manifest\_version": "2.0",  
  "cce\_version": "0.1.0",  
  "window": {  
    "id": "2026-01-31T22-10-00Z\_window-0007",  
    "workspace\_key": "sha256-hash-of-root-path"  
  },  
  "telemetry": {  
    "duration\_ms": 450,  
    "backend\_probe\_results": { "json\_backend": "found" },  
    "sessions\_exported": 3  
  },  
  "exports": \[  
    {  
      "session\_id": "uuid-123",  
      "file\_name": "uuid-123.json",  
      "md\_name": "uuid-123.md",  
      "fingerprint": "sha256-hash",  
      "tags": \["discovery-logic"\]  
    }  
  \],  
  "errors": \[\\]  
}

### **2\. CCE Security & Failure Policy**

* **Invariant JRN-VIS-001:** Every "Window Close" operation **MUST** write a manifest.json. If the export fails entirely, the manifest must still be written with an errors array detailing the crash. "If it happened, it must be visible."  
* **Boundary Control:** No CCE writes outside the configured journals/ directory.

### **3\. CCE Explorer Integration**

* **Tag Scraper:** Regex /\\\*tag:\\s\*(.\*?)\\\*/g populates index/tags.jsonl.  
* **Tree View:** Displays chronological CCE windows and "Tagged Moments" using the index/ data.

**Status:** READY FOR IMPLEMENTATION PLAN.
