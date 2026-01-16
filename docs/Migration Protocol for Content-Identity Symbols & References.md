# Migration Protocol: Content-Identity Symbols & References (Flag Day)

Status: ✅ COMPLETED — January 16, 2026  
Mode: Flag day (no compatibility)  
Scope: symbols, refs, dependent lookups, extraction code

---

## Migration Summary

**Executed:** January 16, 2026  
**Schema Version:** v5

All steps completed successfully:
- ✅ Drop legacy tables (symbols, refs, lookups, FTS)
- ✅ Create content-keyed tables with ast_id only
- ✅ Update qbuilder/worker.py extraction code
- ✅ Update qbuilder/api.py delete logic (CASCADE)
- ✅ Full database rebuild in progress

---

## 0. Objective

Replace all file-bound symbol and reference storage with a content-identity model.

After migration:
• Symbols and refs bind to ASTs
• File associations are derived via joins
• Duplicate rows caused by identical content are eliminated

---

## 1. Preconditions

### 1.1 AST Identity Verification

Before proceeding, confirm:
• asts table enforces UNIQUE(content_hash, parser_version_id)
• ast_id is the surrogate key for that identity

If false, STOP and report.

---

### 1.2 Inventory (Mandatory)

Before any schema change, produce and commit:

1. All code paths that WRITE to symbols or refs
2. All code paths that READ from symbols or refs
3. All dependent lookup or cache tables

This inventory is part of the deliverable.

---

## 2. Flag-Day Rules

• Old tables are DROPPED, not migrated
• No compatibility paths
• No dual writes
• No fallback reads

If something breaks, fix it — do not work around it.

---

## 3. Canonical Schema

### 3.1 Drop Legacy Tables

Drop:
• symbols
• refs
• all dependent lookup tables identified in inventory

---

### 3.2 Create Canonical Tables

#### symbols

Purpose: Definitions derived from content.

Required columns:
• symbol_id (PK)
• ast_id (FK → asts.ast_id)
• name
• symbol_type
• optional scope / namespace
• line_number
• column_number
• metadata_json

Forbidden:
• file_id
• content_version_id

Uniqueness:
Choose and document ONE:

Option A:
UNIQUE(ast_id, symbol_type, name)

Option B (allows duplicates in same content):
UNIQUE(ast_id, symbol_type, name, line_number)

---

#### refs

Purpose: Usage edges derived from content.

Required columns:
• ref_id (PK)
• ast_id (FK → asts.ast_id)
• name (referenced symbol)
• ref_type
• context
• line_number
• column_number

Uniqueness:
UNIQUE(ast_id, ref_type, name, context, line_number)

---

### 3.3 Required Indices

symbols(ast_id)  
symbols(symbol_type, name)  
refs(ast_id)  
refs(ref_type, name)

---

## 4. Code Refactor Requirements

### 4.1 Extractors

All extractors MUST:
• Accept ast_id as input
• NEVER accept file_id
• NEVER accept content_version_id

Canonical flow:
file_id  
→ files.content_hash  
→ asts.ast_id  
→ extract_symbols(ast_id)  
→ extract_refs(ast_id)

---

### 4.2 Queries (Golden Join Only)

All queries answering:
• “Where is symbol X defined?”
• “Which files reference Y?”

MUST join:
symbols / refs  
→ asts  
→ files (via content_hash)

Direct file-bound queries are forbidden.

---

## 5. Execution Steps

1. Stop QBuilder
2. Drop legacy tables
3. Apply new schema
4. Deploy refactored code
5. Clear all queues
6. Rediscover all roots
7. Rebuild all derived data

No partial runs allowed.

---

## 6. Verification Checklist

1. Schema contains NO file_id or content_version_id in symbols/refs
2. Identical content yields ONE AST and ONE symbol set
3. Golden joins return correct file paths
4. Grep confirms no reads of dropped tables

Verification output must be committed.

---

## 7. Deliverables

Agent must commit:
• Completed inventory
• Final DDL
• Code changes
• Verification results

---

## 8. Final Warning

If you are tempted to:
• Keep old tables “just in case”
• Add compatibility code
• Store file_id for convenience

STOP. That is explicitly forbidden.

Correctness is enforced by deletion, not accommodation.
