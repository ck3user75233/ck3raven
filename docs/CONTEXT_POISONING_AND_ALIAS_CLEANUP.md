# Context Poisoning and Alias Cleanup

> **Date:** February 16, 2026  
> **Status:** Active cleanup in progress

---

## The Problem

As a codebase evolves and too many aliases and deprecated concepts accumulate, an
agent's context ends up with too many parallel ways to describe something that at
its base is either **already available directly**, or is **resolvable without any
complex mechanics**.

This document records a specific case study: the identification of CK3 base game
files in the ck3raven database.

---

## How It Happened

The base game files (CK3's vanilla game data) are always:

1. **`mods[0]`** in the session load order — the software puts it there, always first
2. **Named `'CK3 Game Files'`** in `content_versions.name` — set by discovery.py
3. **Located at `ROOT_GAME`** — a global constant pointing to the Steam game folder
4. **Resolvable to a `cvid`** via `mods[0].cvid` at any point after playset activation

Despite all four of these being trivially available, the agent (over multiple
sessions) introduced **20 separate special-case signifiers** across 4+ files to
"identify" the base game files in SQL queries. Each successive session saw existing
patterns in the code, assumed they were intentional, and reinforced them — a textbook
case of context poisoning.

---

## The Signifiers That Were Invented (All Unnecessary)

### Pattern A: `workshop_id IS NULL` = game files

**Why it's wrong:** Local mods (mods in `ROOT_USER_DOCS/mod/`) also have
`workshop_id IS NULL`. This pattern falsely labels every local mod as "game files."

**Where it appeared:**
- report.py `_build_context`: Split content_versions into NULL/NOT NULL buckets
- report.py `_find_file_conflicts`: `CASE WHEN cv.workshop_id IS NULL THEN 'vanilla'`
- report.py count CTE: UNION ALL with NULL/NOT NULL branches
- report.py playset_cte: Same UNION ALL pattern
- db_queries.py: `WHERE cv.workshop_id IS NOT NULL` for "mod" lookups
- server.py: `WHERE workshop_id IS NOT NULL` for mods_only scope

### Pattern B: `content_version_id = 1` or `> 1` by convention

**Why it's wrong:** There is no such convention. cvid assignment is
insertion-order-dependent. If the database were rebuilt, game files could receive
any cvid.

**Where it appeared:**
- server.py `ck3_db_delete` mods_only scope: `WHERE content_version_id > 1`
- Cascading into files, asts, symbols, refs filtering

### Pattern C: `LIKE '%vanilla%'` name matching

**Why it's wrong:** The name is `'CK3 Game Files'`, not `'vanilla'`. And even if
it were, fuzzy matching a name we control is absurd.

**Where it appeared:**
- db_queries.py `get_cvids`: `WHERE workshop_id IS NULL AND LOWER(name) LIKE '%vanilla%'`

### Pattern D: Manufactured `kind`/`source_kind` fields

**Why it's wrong:** Every content_version already has a `name`. The game files are
named `'CK3 Game Files'`. There is no need for a parallel classification system.

**Where it appeared:**
- SourceInfo dataclass: `kind: Literal["vanilla", "mod"]`
- LoadOrderEntry dataclass: `kind: Literal["vanilla", "mod"]`
- contributions.py: `source_kind: str  # 'vanilla' or 'mod'`
- contributions.py: `is_vanilla_involved` property
- SQL CTEs manufacturing `'game_files' as source_kind`

### Pattern E: `COALESCE(cv.name, 'vanilla')` fallback

**Why it's wrong:** If `cv.name` is NULL, something is broken in ingestion. The
fallback hides the bug and injects the string `'vanilla'` as a display name.

**Where it appeared:**
- 13 locations across db_queries.py, server.py, report.py, conflict_ops.py

---

## The Correct Approach

The base game files need **zero special handling**:

| Need | Solution |
|------|----------|
| "Which cvid is the base game?" | `mods[0].cvid` — resolved at playset activation |
| "What's the base game called?" | `mods[0].name` or `content_versions.name` via normal JOIN |
| "Is this contribution from the base game?" | Check if `content_version_id == mods[0].cvid` |
| "Give me all contributions" | Single JOIN to content_versions, use `cv.name` — same query for game files and mods |
| "Exclude game files from delete" | Use the known cvid: `WHERE content_version_id != :game_cvid` |

The base game is a mod. It's mod 0. Its name is `'CK3 Game Files'`. It has a cvid
like every other mod. Everything that works for mods works for it.

---

## Cleanup Summary

Each cluster of changes removes one or more signifier patterns and replaces them
with the trivial correct approach described above.

| Cluster | File(s) | What Changed |
|---------|---------|--------------|
| A | report.py | Removed `kind` field from SourceInfo and LoadOrderEntry |
| B | report.py | `_build_context` queries all content_versions, no NULL split |
| C | report.py | `_find_file_conflicts` uses `cv.name` directly, no CASE WHEN |
| D | report.py | Count CTE and playset_cte: single JOIN, no UNION ALL |
| E | db_queries.py | `get_cvids` resolves mods[0] by path, no LIKE pattern |
| F | server.py | `mods_only` scope uses name match, not cvid > 1 |
| G | db_queries.py + others | `COALESCE(cv.name, 'vanilla')` → `cv.name` |
| H | contributions.py | `source_kind` stays (used in contribution_units table) but `is_vanilla_involved` documented |
