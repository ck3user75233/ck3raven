# LEGACY — DO NOT REUSE ARCHITECTURE

This directory contains the old builder daemon code that has been **quarantined**.

## Why Quarantined

The old builder uses architecture patterns that are now prohibited:

- **Phase batching** - Processing files in phases (parse phase, symbols phase, etc.)
- **needs_* inference** - Using database state to determine what work is needed
- **"Missing artifact" scheduling** - Checking if artifacts exist to decide work

These patterns lead to:
- Race conditions and non-deterministic behavior
- Difficulty reasoning about crash safety
- Hidden dependencies between phases

## What Replaces It

**QBuilder-Daemon** (`qbuilder/`) replaces this with:

- **Routing table authority** - File type determines envelope, no inference
- **FIFO queues** - Monotonic build_id ordering, deterministic processing
- **Fingerprint binding** - Artifacts tied to exact file bytes (mtime+size+hash)
- **No phase thinking** - Each file gets its complete envelope executed atomically

## What Can Be Reused

The following low-level utilities MAY be imported by QBuilder if needed:

- `phases/parsing.py` - Core PDX parsing functions (if extracted cleanly)
- `phases/symbols.py` - Symbol extraction logic (if extracted cleanly)
- `phases/refs.py` - Reference extraction logic (if extracted cleanly)

**Import rule:** Only import specific functions, never entire modules or orchestration code.

## Deletion Schedule

This directory will be deleted after QBuilder is proven stable (convergence test passes).

---

**Last updated:** January 11, 2026
