# Routing Table Exclusion Updates + Parser Bug Report

**Date:** 2026-01-25
**Source:** ck3lens analysis of build_queue failures
**Target File:** `qbuilder/routing_table.json`

---

## CRITICAL: Parser Timeout Bug

**275 files from Historic Invasions are timing out at 30s**, including:

| File | Size | Content |
|------|------|---------|
| `07_balgarsko_templates.txt` | 9 bytes | `# none` |
| `33_mamluk_story_cycle.txt` | 14 bytes | `# nothing #` |
| `00_historicinvasions_decision_group_types.txt` | 61 bytes | ? |
| `82_komnenos_templates.txt` | 71 bytes | ? |

**A 9-byte file with just a BOM + comment should parse in &lt;1ms, not timeout at 30 seconds.**

This is not a file size issue - it's a parser bug. Meanwhile, `combat_events.txt` (61KB) parses successfully.

### Affected Mods
| Mod | Timeout Count | Avg Size |
|-----|---------------|----------|
| Historic Invasions | 275 | 5.8 KB |
| Historical Invasion Fix | 43 | 12.0 KB |
| Historicity | 14 | 13.0 KB |
| Prisoners of War | 7 | 1.2 KB |
| SRE | 1 | 57.9 KB |

**Total: 340 files timing out**

### Recommendation for ck3raven-dev

1. **Debug the parser timeout** - why do small comment-only files take 30s?
2. Check if there's a queue issue or worker stall affecting these specific files
3. Consider if it's related to BOM handling or comment-only content

---

## Routing Table Exclusions (Still Valid)

These documentation files should still be excluded from E_SCRIPT envelope:

```json
{
  "match": "changelog",
  "envelope": "E_SKIP",
  "comment": "Changelog files in any location are not CK3 scripts"
},
{
  "match": "description.txt",
  "envelope": "E_SKIP", 
  "comment": "Mod description files are not CK3 scripts"
},
{
  "match": "credit.txt",
  "envelope": "E_SKIP",
  "comment": "Credits file (alternate naming from credits.txt)"
},
{
  "match": "compatibility.txt",
  "envelope": "E_SKIP",
  "comment": "Mod compatibility notes are not CK3 scripts"
},
{
  "match": "STEAM_DESCRIPTION.txt",
  "envelope": "E_SKIP",
  "comment": "Steam Workshop description files"
},
{
  "match": "modding_info.txt",
  "envelope": "E_SKIP",
  "comment": "Documentation for modders"
}
```

---

## Files Fixed by Exclusions

| File | Mod | Error |
|------|-----|-------|
| `common/character_interactions/PoW_changelog.txt` | Prisoners of War | ParseTimeout |
| `description.txt` (2) | Multiple | LexerError '•' '(' |
| `credit.txt` | Unknown | LexerError '☞' |
| `compatibility.txt` | Unknown | LexerError '\\' |
| `STEAM_DESCRIPTION.txt` | Unknown | LexerError '(' |
| `modding_info.txt` | Unknown | LexerError '(' |

---

## Parser Issues (Not Exclusions)

These are CK3 script files with characters the parser should handle:

1. **EPE ethnicity files** - backtick characters
2. **acs_se_claims.txt** - semicolon in comment
3. **ttk_travel_event_kill.txt** - guillemet (») character

---

## Priority

1. **HIGH** - Debug parser timeout bug (340 files blocked)
2. **MEDIUM** - Add routing exclusions (6 files)
3. **LOW** - Fix parser for special characters (8 files)
