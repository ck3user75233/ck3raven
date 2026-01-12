# QBuilder-Daemon Canonical Architecture, Ontology, and Non-Negotiable Rules

Status: CANONICAL  
Audience: Agentic AI implementing CK3 build systems  
Supersedes: All prior builder, daemon, policy, and phase-based documentation  
Goal: A crash-safe, resumable, uniform, queue-driven build system with no parallel authorities, no global stages, and no special-case content types.

## Prime Directive

There is exactly one build system.

There is:
- one scheduler (the queue)
- one routing mechanism (file routing table → envelope)
- one correctness model (signature-based validity)
- one authority for what work happens (the envelope assigned at discovery)

Anything that introduces a second pathway, a second authority, or a second interpretation of “what needs work” is a defect.

## Ontology

### Content Version

There is exactly one concept of content version: content_version.

Vanilla, mods, DLC, generated content, and future sources are not different kinds of content. They differ only by metadata (path, load order, writability), never by identity or processing logic.

The following ideas are permanently banned:
- vanilla CVID
- mod CVID
- _ensure_vanilla_cvid
- _ensure_mod_cvid
- any architectural branching on “vanilla vs mod”

If “is vanilla” is ever required, it must be derived inline from metadata and must never introduce a separate architectural pathway.

### Files

A file is uniquely identified by:
(file_id) := (content_version_id, relpath)

The files table is the sole authority for file identity and file content state.

There is no separate file_state table and no file_content_version intersection table. Any such constructs are redundant and prohibited.

### Envelopes (Work Orders)

Every file receives exactly one envelope at discovery.

An envelope is a declarative description of the complete intended lifecycle for that file type.

Examples (illustrative only):
- Script file → ingest → parse AST → extract definitions and references
- Localization file → ingest → parse localization entries
- Name list → ingest → lookup generation

Envelopes are assigned once at discovery and are never inferred later by scanning database state.

## File Routing Table

There exists a human-readable and machine-readable routing table mapping file characteristics (extensions, patterns) to envelopes.

This routing table is the single authority for deciding what work a file will undergo.

The following logic is prohibited:
- “if needs_ast then…”
- “if symbols missing then…”
- “if table empty then…”

All such inference is replaced by envelope assignment at discovery.

## Queues and Scheduling

### Single Scheduler

All work flows through one scheduler: build_queue.

There is no bypass mode.

Flash updates, batch rebuilds, CI runs, and interactive edits all enqueue build_queue items.

### FIFO and Priority

Queue ordering is:
ORDER BY priority DESC, build_id ASC

build_id is a monotonic queue item identifier and defines FIFO ordering.

Audit or run identifiers must use a different name (e.g. run_id). build_id must never be reused to mean anything else.

### Leases

Queue items are claimed with leases.

A lease is a time-limited “I am working on this” claim for crash recovery only.

Leases are not permissions, not authority, and not correctness indicators.

## Discovery

Discovery performs the following actions:
- create content_versions
- enumerate files from the filesystem
- insert rows into the files table
- assign envelopes using the routing table
- enqueue build_queue items

Discovery must not introduce parallel authorities.

The following discovery fields are prohibited as authoritative concepts:
- root_type
- root_name
- root_path

Discovery operates only on canonical identifiers (content_version_id). Filesystem paths are resolved via canonical metadata.

### Reset Semantics

reset --fresh means:
- database is empty
- content_versions table is empty
- files table is empty
- derived tables are empty
- queues are empty

Discovery after reset must repopulate everything from scratch.

AUTOINCREMENT gaps are irrelevant and must be ignored.

## Execution Model

Each build_queue item executes:
- one file
- one envelope
- one ordered sequence of steps

Execution is per file, not per stage.

Global stage scheduling is prohibited. The following are banned:
- “run ASTs for all files first”
- “scan DB for files missing symbols”
- “needs_ast / needs_symbols / mask logic”

All such behavior must be replaced by envelope execution and signature validation.

## Correctness Model

Existence of rows in derived tables does not imply correctness.

This rule is absolute.

### Validity Signatures

Every derived artifact is valid only if its input signature matches.

Typical signature components include:
- file content hash
- parser version ID
- extractor version ID
- upstream artifact identity (AST hash, symbol set version)

If any part of the signature changes, the artifact is invalid and must be regenerated.

Resume is allowed only if the recorded signature still matches. Resume must never rely on row existence or counts.

## Cross-File Dependencies (Symbols)

Files extract unresolved symbol definitions and references independently.

A separate SymbolRegistry snapshot may aggregate definitions.

Reference resolution operates against a registry snapshot and is not a global “symbol stage.”

Resolution may be triggered by watermarks, version changes, or explicit commands, never by scanning for “missing refs.”

## Flash Updates

All file writes enqueue build_queue items using the same routing and envelope system.

Inline parsing or extraction in the write path is prohibited.

Flash updates may enqueue with higher priority.

Callers may optionally wait by polling queue completion, but execution semantics remain identical.

## Background Builds

Full rebuilds run as managed subprocesses:
python -m qbuilder.cli build

Subprocesses must:
- survive MCP restarts
- rely on leases for resumability
- record run_id and logs explicitly

In-process threads and permanent daemons are not permitted at this stage.

## Queue Counts and Observability

Queue counts exist solely for observability and operator insight.

Queue counts must never:
- decide what work to run
- decide what work to skip
- imply correctness

Preferred implementation is computing counts via SQL COUNT(*) GROUP BY status.

Stored counters, if any, are informational only and may be wrong without consequence.

## Banned Ideas (Enforced)

The following concepts are permanently banned:
- vanilla vs mod CVIDs
- phase-based builders
- stage scans (“missing ASTs”, “needs symbols”)
- parallel execution paths
- DB-existence-based correctness
- discovery branching on content type
- root metadata as authority
- inline parse or extract on write

## Required Public API

qbuilder/api.py must expose only:
- enqueue(paths or content_versions, priority) → build_ids
- wait(build_ids, timeout) → status

No other scheduling APIs are permitted.

## Final Authority Statement

This document defines the canonical ontology and behavior of QBuilder-Daemon.

If any existing code, prior documentation, or agent intuition conflicts with this document, this document prevails with no exceptions.
