# QBuilder Canonical Architecture & Non-Negotiable Data Identity Laws

Status: CANONICAL  
Applies to: ck3raven-dev, ck3lens  
Authority: Hard law  
Compatibility: NONE (flag-day only)

**Migration Status:** Laws 4, 4b, 5 implemented as of January 16, 2026.
See [CONTENT_KEYED_SCHEMA.md](CONTENT_KEYED_SCHEMA.md) for current schema.

---

## 0. Prime Directive

QBuilder is a content-centric, queue-driven build system.

Its sole responsibilities are:
• Discover files
• Parse content
• Derive ASTs, symbols, and references
• Populate derived database state deterministically and safely

QBuilder is NOT:
• A session manager
• A UI abstraction
• A file editor
• A fallback execution path

All derived data MUST be produced by QBuilder.
All inline parsing or extraction is non-canonical.

---

## 1. Canonical Role Separation

Component responsibilities are strictly segregated:

QBuilder  
• Discovery  
• Parsing  
• Symbol extraction  
• Reference extraction  
• Database writes  

MCP Tools  
• Read-only queries  
• Enqueue requests only  

Database  
• Stores canonical derived state  

Queues  
• The ONLY schedulers of work  

No component may perform another component’s role.

---

## 2. Queue Singularity Law

All parsing and extraction work MUST originate from `build_queue`.

Forbidden:
• Inline parsing
• “Fast path” parsing
• Validation that parses
• AST generation outside the queue

If parsing occurs, it MUST be because a queue item was claimed.

---

## 3. Content-Centric Model

QBuilder is content-centric, not file-centric.

Definitions:
• File: A location pointing to content
• Content: The byte sequence of a file
• AST: Parsed representation of content
• Symbol / Reference: Facts derived from an AST

---

## 4. Non-Negotiable Data Identity Laws

Violations are architectural defects.

### Law 1 — File Identity Is Fingerprint-Based

A file is identified by:
(file_path, file_mtime, file_size, file_hash)

If any fingerprint changes, file identity changes.

---

### Law 2 — Content Identity Is Hash-Based

Content identity is:
(content_hash)

Paths, mods, CVIDs, playsets are NOT identity.

---

### Law 3 — AST Identity Is Content + Parser Version

AST identity is:
(content_hash, parser_version_id)

There is at most ONE AST per such pair.

Multiple files MAY legally share a single AST.

---

### Law 4 — Symbols and References Bind to Content, Not Files

Symbols and references derive from ASTs.

They MUST bind to content identity, not file identity.

Forbidden in symbols/refs tables:
• file_id
• relpath
• content_version_id
• mod identifiers

File associations are derived via joins only.

---

### Law 4b — No Stored File Associations

Symbols and references MUST NOT store file-level data.

All file associations are resolved at query time using joins.

---

### Law 5 — AST Deduplication Is Mandatory

If two files have identical content:
• Parse once
• Reuse AST
• Do NOT duplicate symbols or refs

---

### Law 6 — Envelopes Are Immutable

Where envelopes apply:
• Assigned once
• Never mutated
• Changes require rediscovery

---

### Law 7 — MCP Is Enqueue-Only

MCP tools:
• MAY enqueue work
• MAY read derived data
• MUST NOT parse or extract inline

---

### Law 8 — Timeouts Are Mandatory

All parsing and traversal MUST:
• Run in subprocesses
• Enforce hard timeouts
• Be killable without blocking MCP

---

### Law 9 — Legacy Code Is Guilty Until Proven Innocent

Any code that:
• Bypasses queues
• Parses inline
• Reintroduces file-centric binding
• Implements compatibility layers

is non-canonical and must be deleted or quarantined.

---

## 5. The Golden Join (Required)

To associate symbols or references back to files:

symbols / refs  
→ asts (via ast_id)  
→ files (via content_hash)  
→ content_versions (optional filtering)

This is the ONLY allowed resolution path.

---

## 6. Hard Bans

Explicitly forbidden:
• Compatibility reads from old tables
• Dual-write or dual-read strategies
• symbols.file_id or refs.file_id
• Snapshot / Merkle CVID semantics
• Inline parsing “for convenience”

---

## 7. Flag-Day Rule

When identity laws change:
• Old tables are dropped
• Derived data is rebuilt
• No migration bridges remain

Correctness > continuity.

---

## 8. Success Criteria

This architecture is correct if:
• Identical content produces exactly one AST
• Symbols and refs do not multiply per file
• All parsing occurs via queues
• MCP tools remain responsive during builds
• No fallback or legacy paths exist
