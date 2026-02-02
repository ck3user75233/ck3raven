# Journal Extractor Implementation Plan

> **Status:** READY FOR IMPLEMENTATION  
> **Created:** February 1, 2026  
> **Updated:** February 2, 2026  
> **Spec:** [JOURNAL_EXTRACTOR_SPEC.md](./JOURNAL_EXTRACTOR_SPEC.md)  
> **Dependencies:** CANONICAL_LOGS.md, Canonical Reply System Architecture.md

---

## Executive Summary

The Journal Extractor captures Copilot Chat conversations during defined "windows." It consists of:

1. **Extension-side** (TypeScript): Window lifecycle, discovery, baseline capture, delta extraction
2. **MCP-side** (Python): `ck3_journal` tool for querying/searching archived sessions
3. **Storage**: File-backed journals at `~/.ck3raven/journals/`

---

## Naming Conventions

| Concept | Internal Name | Log Category | Reply Prefix |
|---------|---------------|--------------|--------------|
| Subsystem | Journal Extractor | `ext.journal.*` | `JRN-*` |
| Window | Journal Window | — | — |
| Archive | Journal | — | — |

**Note:** "CCE" may appear in internal code comments but all external-facing names use "Journal".

---

## Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    VS Code Extension                             │
├─────────────────────────────────────────────────────────────────┤
│  src/journal/                                                   │
│  ├── windowManager.ts      # Window lifecycle (start/close)     │
│  ├── discovery.ts          # Locate chatSessions storage        │
│  ├── backends/                                                  │
│  │   └── jsonBackend.ts    # Parse .json files                  │
│  ├── fingerprint.ts        # SHA-256 deduplication              │
│  ├── extractor.ts          # Delta extraction + tag scraping    │
│  └── manifest.ts           # Write manifest.json (v2.0 schema)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ IPC / MCP Call
┌─────────────────────────────────────────────────────────────────┐
│                    MCP Server (Python)                          │
├─────────────────────────────────────────────────────────────────┤
│  tools/ck3lens_mcp/ck3lens/journal/                             │
│  ├── journal_tool.py       # ck3_journal MCP tool               │
│  ├── reader.py             # Read manifests and sessions        │
│  └── search.py             # Query tags.jsonl index             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    File Storage                                  │
├─────────────────────────────────────────────────────────────────┤
│  ~/.ck3raven/journals/{workspace_key}/                          │
│  ├── windows/                                                    │
│  │   └── 2026-02-01T14-30-00Z_window-0001/                      │
│  │       ├── manifest.json      # v2.0 schema, always written   │
│  │       ├── {session_id}.json  # Raw session data              │
│  │       └── {session_id}.md    # Markdown export               │
│  └── index/                                                      │
│      └── tags.jsonl             # Tag index for search          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Decisions Summary (Q1–Q17)

| Question | Decision |
|----------|----------|
| **Q1. RootCategory** | No new ROOT_JOURNALS in v1. Hard-bound to `~/.ck3raven/journals/` |
| **Q2. MCP tool** | Single entry `ck3_journal(action, params)` |
| **Q3. SQLite backend** | JSON only in Phase 1; SQLite is Phase 2+ |
| **Q4. Discovery fallback** | Implement v3.1 exactly: API → standard local → remote/server |
| **Q5. Multi-workspace** | Scope to active workspace at window start |
| **Q6. Remote environments** | Include in candidate roots, best-effort, log if not found |
| **Q7. Implicit close** | Auto-close on extension deactivate with `reason=deactivate` |
| **Q8. Overlapping windows** | Strictly one-at-a-time; new window auto-closes previous |
| **Q9. Baseline size** | Accept any size (metadata only: mtime/size/path) |
| **Q10. Time bucket** | 60 seconds (spec requirement) |
| **Q11. Attachments** | Only explicit attachments in JSON structure, not inferred |
| **Q12. Trace ID** | Per-command `_trace_id`; correlation via `window_id` field |
| **Q13. Reply codes** | `JRN-*` prefix, register in Phase 4 |
| **Q14. Status bar** | Yes: "📓 Journal Window: ON" when active |
| **Q15. PII scrubbing** | None in v1; add warning in UI/README |
| **Q16. Retention** | No auto-pruning; keep forever unless user deletes |
| **Q17. Path override** | No override in v1; always `~/.ck3raven/journals/` |

---

## Mandatory Spec Requirements

### Log Categories (ext.journal.*)

| Event | Category | When Logged |
|-------|----------|-------------|
| Window started | `ext.journal.window_start` | On `startWindow` command |
| Window ended | `ext.journal.window_end` | On close (any reason) |
| Discovery completed | `ext.journal.discovery` | After candidate root scan |
| Access denied | `ext.journal.access_denied` | Write attempted outside journals/ |
| Storage locked | `ext.journal.storage_locked` | Cannot acquire file lock |

### Reply Codes (JRN-*)

Must follow Canonical Reply System format: `JRN-AREA-TYPE-NNN`

| Code | Type | Meaning |
|------|------|---------|
| `JRN-WIN-S-001` | Success | Window started successfully |
| `JRN-WIN-S-002` | Success | Window closed successfully |
| `JRN-WIN-I-001` | Info | No changes detected in window |
| `JRN-WIN-E-001` | Error | Window start failed |
| `JRN-DIS-S-001` | Success | Discovery found chatSessions |
| `JRN-DIS-I-001` | Info | No candidates found |
| `JRN-DIS-E-001` | Error | Discovery failed |
| `JRN-EXT-S-001` | Success | Extraction completed |
| `JRN-EXT-E-001` | Error | Extraction failed |
| `JRN-QRY-S-001` | Success | Query returned results |
| `JRN-QRY-I-001` | Info | No results found |
| `JRN-VIS-001` | Info | Visibility invariant (manifest written) |

### Discovery Order (v3.1 Exact)

**Candidate Root Scan Order:**
1. API context (`globalStorageUri` neighbor scan)
2. Standard local paths (platform-specific)
3. Remote/server paths (SSH, WSL, Dev Container)

**Ranking Rules (in order):**
1. DB meta match (workspaceId matches)
2. Structure validation (chatSessions/ directory exists)
3. Recent activity (most recently modified)

### Manifest Schema (v2.0)

```json
{
  "manifest_version": "2.0",
  "extractor_version": "1.0.0",
  "window_id": "2026-02-01T14-30-00Z_window-0001",
  "workspace_key": "a1b2c3d4...",
  "started_at": "2026-02-01T14:30:00.000Z",
  "closed_at": "2026-02-01T16:45:00.000Z",
  "close_reason": "user_command",
  "exports": [
    {
      "session_id": "abc123",
      "fingerprint": "sha256:...",
      "json_path": "abc123.json",
      "md_path": "abc123.md",
      "tags": ["*tag:architecture*", "*tag:bug-fix*"]
    }
  ],
  "telemetry": {
    "sessions_scanned": 42,
    "sessions_changed": 3,
    "sessions_exported": 3,
    "duplicates_skipped": 0,
    "extraction_duration_ms": 1234
  },
  "errors": []
}
```

**Invariant JRN-VIS-001:** Manifest MUST be written even on total failure. If extraction fails, `exports` will be empty and `errors` will contain failure details.

### Fingerprint Algorithm

Inputs (in order):
1. Role (user/assistant)
2. Text content (normalized)
3. Attachment URIs (sorted list, explicit attachments only)
4. Time bucket (floor to 60 seconds)

Output: SHA-256 hash

---

## Implementation Phases

### Phase 1: Core Infrastructure (Extension)

**Goal:** Establish foundation for Journal Extractor in the extension.

| ID | Task | File | Description |
|----|------|------|-------------|
| 1.1 | Types | `src/journal/types.ts` | Define interfaces (WindowState, SessionMetadata, Manifest v2.0) |
| 1.2 | Workspace key | `src/journal/workspaceKey.ts` | SHA-256 of normalized path (or override) |
| 1.3 | Discovery | `src/journal/discovery.ts` | v3.1 candidate root scan + ranking rules |
| 1.4 | Storage | `src/journal/storage.ts` | Journal directory management |
| 1.5 | Logging | Update `structuredLogger.ts` | Add `ext.journal.*` categories |

**Deliverables:**
- Consistent workspace_key derivation
- Discovery with exact v3.1 scan order and ranking
- `ext.journal.discovery` event logged

### Phase 2: Window Lifecycle

**Goal:** Implement the "window" abstraction for capturing sessions.

| ID | Task | File | Description |
|----|------|------|-------------|
| 2.1 | Window manager | `src/journal/windowManager.ts` | Start/close with one-at-a-time enforcement |
| 2.2 | Baseline | `src/journal/baseline.ts` | Snapshot mtime/size map on start |
| 2.3 | Delta | `src/journal/delta.ts` | Detect changed files since baseline |
| 2.4 | Commands | `src/journal/commands.ts` | Register VS Code commands |
| 2.5 | Status bar | `src/journal/statusBar.ts` | "📓 Journal Window: ON" indicator |
| 2.6 | Extension init | Update `extension.ts` | Initialize journal subsystem |
| 2.7 | Deactivate hook | Update `extension.ts` | Auto-close window on deactivate |

**Commands:**
- `ck3raven.journal.startWindow` - "Journal: Start Window"
- `ck3raven.journal.closeWindow` - "Journal: Close Window"
- `ck3raven.journal.status` - "Journal: Show Status"

**Events:**
- `ext.journal.window_start` on start
- `ext.journal.window_end` on close (any reason)

**Close Reasons:**
- `user_command` - User explicitly closed
- `overlap_new_window` - New window started
- `deactivate` - Extension deactivating

### Phase 3: Extraction & Storage

**Goal:** Parse sessions, deduplicate, and write archives.

| ID | Task | File | Description |
|----|------|------|-------------|
| 3.1 | JSON backend | `src/journal/backends/jsonBackend.ts` | Parse chatSessions/*.json |
| 3.2 | Fingerprint | `src/journal/fingerprint.ts` | SHA-256 with v3.1 inputs (60s bucket) |
| 3.3 | Tag scraper | `src/journal/tagScraper.ts` | Extract `/\*tag:\s*(.*?)\*/g` |
| 3.4 | Markdown export | `src/journal/markdownExport.ts` | Convert session to Markdown |
| 3.5 | Manifest writer | `src/journal/manifest.ts` | v2.0 schema, always written (JRN-VIS-001) |
| 3.6 | Indexer | `src/journal/indexer.ts` | Append to index/tags.jsonl |
| 3.7 | Error handling | `src/journal/extractor.ts` | Ensure manifest written on any failure |

**Invariants:**
- Manifest always written, even on total failure
- `errors[]` always present (empty array if no errors)
- Telemetry fields always populated

### Phase 4: MCP Tool

**Goal:** Expose journal data to agents via `ck3_journal` tool.

| ID | Task | File | Description |
|----|------|------|-------------|
| 4.1 | Module init | `ck3lens/journal/__init__.py` | Journal module |
| 4.2 | Reader | `ck3lens/journal/reader.py` | Read manifests and session files |
| 4.3 | Search | `ck3lens/journal/search.py` | Query tags.jsonl index |
| 4.4 | Tool impl | `ck3lens/journal/journal_tool.py` | `ck3_journal_impl` function |
| 4.5 | Server registration | Update `server.py` | Register `ck3_journal` MCP tool |
| 4.6 | Reply codes | Update `reply_registry.py` | Add JRN-* codes |

**Tool Actions:**

| Action | Schema | Reply Code |
|--------|--------|------------|
| `list` | `{ window_id?: str }` | JRN-QRY-S-001 / JRN-QRY-I-001 |
| `read` | `{ session_id: str }` | JRN-QRY-S-001 |
| `search` | `{ query: str }` | JRN-QRY-S-001 / JRN-QRY-I-001 |
| `status` | `{}` | JRN-WIN-S-001 |

### Phase 5: Explorer Integration

**Goal:** Visual interface for browsing journal archives.

| ID | Task | File | Description |
|----|------|------|-------------|
| 5.1 | Window tree | `src/journal/views/windowTreeProvider.ts` | Tree view of windows |
| 5.2 | Tagged moments | `src/journal/views/taggedMomentsProvider.ts` | Tree of tagged items |
| 5.3 | Package.json | Update `package.json` | Register views |
| 5.4 | Session viewer | `src/journal/views/sessionViewer.ts` | Webview for session content |

---

## Pre-Implementation Checklist

Before starting Phase 1:

- [x] Decisions finalized for all Q1–Q17
- [ ] Rename spec file from "Canonical Copilot Chat Extractor.md" to canonical name
- [ ] Verify structuredLogger.ts supports new categories
- [ ] Create `src/journal/` directory structure
- [ ] Pre-register JRN-* reply codes in registry

---

## Estimated Effort

| Phase | Effort | Deliverable |
|-------|--------|-------------|
| Phase 1 | 1-2 days | Discovery + workspace key |
| Phase 2 | 2-3 days | Window lifecycle + status bar |
| Phase 3 | 2-3 days | Extraction + manifest v2.0 |
| Phase 4 | 1-2 days | MCP tool |
| Phase 5 | 2-3 days | Explorer views |

**Total: 8-13 days**

---

## Changelog

| Date | Changes |
|------|---------|
| 2026-02-01 | Initial implementation plan created |
| 2026-02-02 | Renamed from CCE to Journal; integrated Q1-Q17 decisions; fixed spec mismatches (log categories, reply codes, discovery order, manifest schema) |
