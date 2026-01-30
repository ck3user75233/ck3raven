Here is the implementation brief formatted as a single, continuous Markdown document.

# ---

**Agent-Facing Implementation Brief: ck3raven Chat Participant \+ Chat Journal (V1)**

## **0\. Decision Lock**

**These decisions are final for V1. Do not re-litigate.**

* We will **not** attempt global capture of Copilot Chat or other participants.  
* We will implement a ck3raven chat participant (e.g., @ck3raven) so ck3raven owns its chat turns.  
* We will implement an **append-only Chat Journal (JSONL)** plus minimal tagging/actions.  
* We will implement known-conflict warnings (by extension IDs) and self-health indicators (participant registered, journal writable, MCP reachable).

## ---

**1\. Goals (V1)**

* User can chat via @ck3raven inside the VS Code chat UI.  
* Every @ck3raven conversation turn is archived to disk.  
* User can tag the last turn and create follow-up actions referencing that turn.  
* User can search the journal (Simple V1: text scan over JSONL).  
* Extension shows status: Participant OK, Journal OK, MCP OK; plus warns about known incompatible extensions.

## **2\. Non-Goals (V1)**

* Capturing conversations *not* owned by @ck3raven.  
* Full SQLite indexing (Optional V2).  
* Rich UI journaling viewer (Optional V2).  
* Automatic "conflict detection" beyond known extension ID warnings \+ self-health checks.

## ---

**3\. UX Contract**

### **3.1 Chat Entry**

* User types in chat: @ck3raven \<prompt\>  
* ck3raven responds as the orchestrator and may call MCP tools.

### **3.2 Journal Storage**

* **Location:** Workspace-local folder (create if missing).  
* **Directory:** .ck3raven/chats/  
* **File Structure:** One session file per chat session.  
  * .ck3raven/chats/YYYY-MM-DD/session\_\<session\_id\>.jsonl  
* **Constraint:** Append-only. Never rewrite existing lines.

### **3.3 Commands (V1)**

* ck3raven.chatJournal.tagLastTurn  
* ck3raven.chatJournal.createActionFromLastTurn  
* ck3raven.chatJournal.search (Simple input box; returns results list in output channel).  
* ck3raven.diagnose (Prints health snapshot).  
* *(Optional)* ck3raven.chatJournal.openFolder

### **3.4 Status**

In the existing ck3raven status window/panel:

* **Participant:** ✅ / ❌  
* **Journal:** ✅ / ⚠️ / ❌ (Writable? Workspace trust? Path ok?)  
* **MCP Server:** ✅ / ❌ (Ping)  
* **Conflicts:** ⚠️ (If known conflict extension(s) enabled)

## ---

**4\. Data Model (JSONL Event Schema)**

Each line is a JSON object with event\_type and session\_id at minimum.

### **4.1 Common Fields (All Events)**

JSON

{  
  "schema\_version": 1,  
  "event\_id": "uuid",  
  "event\_type": "turn|tool\_call|tag|action|session\_start|session\_end|health",  
  "timestamp": "2026-01-29T19:22:33.123Z",  
  "workspace": {  
    "name": "repo-name",  
    "uri": "file:///.../",  
    "trusted": true  
  },  
  "session\_id": "ck3raven-20260129-\<shortid\>",  
  "mode": {  
    "agent\_mode": "ck3raven-dev",  
    "safety": "safe"  
  }  
}

### **4.2 session\_start**

JSON

{  
  "event\_type": "session\_start",  
  "session\_title": "optional short title",  
  "chat\_surface": "vscode.chat",  
  "participant": "ck3raven"  
}

### **4.3 turn**

Represents one user prompt \+ ck3raven response.

JSON

{  
  "event\_type": "turn",  
  "turn\_id": "t0001",  
  "user": {  
    "text": "Index and cluster docs...",  
    "selection\_context": null  
  },  
  "assistant": {  
    "text": "…",                 // optional plain text  
    "reply": { "...": "..." },    // serialized Reply dict (preferred)  
    "summary": null  
  },  
  "correlation": {  
    "conversation\_key": "optional stable key"  
  }  
}

### **4.4 tool\_call**

Log every MCP tool invocation made during a turn (even if it fails).

JSON

{  
  "event\_type": "tool\_call",  
  "turn\_id": "t0001",  
  "tool": {  
    "name": "ck3\_search",  
    "input": { "...": "..." }  
  },  
  "result": {  
    "ok": true,  
    "reply": { "...": "..." }     // serialized Reply dict  
  },  
  "timing\_ms": 842  
}

### **4.5 tag**

Tags can apply to a turn or an arbitrary span.

JSON

{  
  "event\_type": "tag",  
  "turn\_id": "t0001",  
  "tags": \["qbuilder", "docs", "todo"\],  
  "note": "Optional note"  
}

### **4.6 action**

Follow-up actions for later agent work.

JSON

{  
  "event\_type": "action",  
  "action\_id": "a0001",  
  "turn\_id": "t0001",  
  "title": "Update docs: QBuilder cluster template",  
  "status": "open",  
  "details": "Summarize and update TEMPLATE.md per chat turn t0001",  
  "tags": \["docs", "qbuilder"\]  
}

### **4.7 health**

Optional, written on diagnose.

JSON

{  
  "event\_type": "health",  
  "checks": {  
    "participant\_registered": true,  
    "journal\_writable": true,  
    "mcp\_reachable": true,  
    "known\_conflicts": \["specstory.extensionId"\]  
  }  
}

## ---

**5\. Implementation Plan**

### **5.1 Extension Contributions**

* Register a chat participant:  
  * **Name:** ck3raven  
  * **Display:** “ck3raven”  
  * *(Note: supports slash commands if desired like /init, /mode, but not required for V1).*  
* Register commands listed in **3.3**.  
* Add/extend status UI to show health signals.

### **5.2 Session Lifecycle**

* **When first message arrives for @ck3raven:**  
  * Create session\_id.  
  * Write session\_start.  
* **For each prompt:**  
  * Create turn\_id.  
  * Write turn after generating response (or write a preliminary “turn\_start” if desired; not required).  
  * Log each tool call as tool\_call.  
* *(Optional: Write session\_end when VS Code deactivates or after inactivity threshold. Skip for V1).*

### **5.3 Journal Writer (Core)**

Implement a single module responsible for:

1. Resolving workspace folder.  
2. Ensuring .ck3raven/chats/YYYY-MM-DD/ exists.  
3. Opening file in **append mode**.  
4. Writing one JSON object per line (newline-delimited JSON).

**Hard Rules:**

* Append-only.  
* Never rewrite previous lines.  
* If write fails, report in status and fall back to in-memory buffer (small ring buffer) so user doesn’t lose the session; flush later if possible.

### **5.4 Tag/Action Commands**

* **Tag Last Turn:**  
  * Finds current session \+ last turn\_id (keep in memory for V1).  
  * Prompts user for tags (quick-pick multi-select \+ freeform add).  
  * Writes tag event.  
* **Create Action from Last Turn:**  
  * Prompts for title \+ details (pre-fill details with snippet from the last turn).  
  * Writes action event.

### **5.5 Search (V1)**

* **Input box:** Query string.  
* **Scanning:** Scan JSONL files under .ck3raven/chats/ using simple substring match on:  
  * user.text  
  * assistant.text  
  * tags / actions  
* **Results:** Return results in an output channel (Show date/session/turn\_id \+ 1-line snippet \+ file path).  
  * *(V2: Upgrade to SQLite index and clickable results).*

### **5.6 Known Conflict Warnings**

* Maintain a small deny/warn list:  
  * knownChatRecorderExtensions: string\[\] \= \[ "specstory.\<id\>", ... \]  
* On activation and on diagnose:  
  * Enumerate enabled extensions.  
  * If any match, set status warning “Potential conflict: …”  
* **Do not block.** Only warn.

### **5.7 MCP Orchestration Hook**

In the participant handler:

1. Use existing ck3raven agent-mode initiation path.  
2. Calls to MCP tools are already structured (Reply dict). Log tool\_calls.  
3. Ensure the final chat response is either:  
   * Plain text with structured data embedded.  
   * Plain text \+ a summarized view of the Reply.  
   * *(The journal stores the full Reply dict).*

## ---

**6\. File/Module Layout (Suggested)**

* src/chat/participant.ts  
  * Registers @ck3raven, routes messages to orchestrator, calls journal.  
* src/chat/journal.ts  
  * Session management, JSONL writing, last-turn tracking.  
* src/chat/search.ts  
  * V1 scanning search.  
* src/chat/actions.ts  
  * Tag/action command handlers.  
* src/health/diagnose.ts  
  * Health checks \+ conflict warning.  
* src/ui/status.ts  
  * Status panel integration.

## ---

**7\. Acceptance Tests (Must Pass)**

### **7.1 Participant**

* Typing @ck3raven hello returns a response.  
* Status shows Participant ✅.

### **7.2 Journal**

* After one message, a session JSONL exists under .ck3raven/chats/YYYY-MM-DD/.  
* File contains session\_start and one turn event.  
* Append-only: Sending another message adds new lines, does not rewrite.

### **7.3 Tool Logging**

* If a prompt causes an MCP tool call, a tool\_call event is written with tool name, input, and Reply output.

### **7.4 Tagging**

* Running ck3raven.chatJournal.tagLastTurn writes a tag event referencing the last turn.

### **7.5 Actions**

* Running ck3raven.chatJournal.createActionFromLastTurn writes an action event referencing the last turn.

### **7.6 Search**

* Running ck3raven.chatJournal.search for a known word finds at least one result and prints session/turn info.

### **7.7 Conflicts Warning**

* If an extension from the known list is enabled, status shows ⚠️ Conflicts and diagnose prints the IDs.

## ---

**8\. Guardrails (Important)**

* **Do not** hook into Copilot Chat internals.  
* **Do not** attempt to read other participants’ messages.  
* **Do not** introduce “clever” background indexing (V1 is on-demand scan).  
* Prefer correctness and durability over UI polish.  
* *(Note: V2 brief for SQLite index \+ sidebar journal viewer \+ clickable “open turn” deep-links can follow, but this V1 is the minimum for reliable archiving/tagging).*