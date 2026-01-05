# arch_lint v2.3 (token-based)

Why v2.3 exists:
- v2.2 was vulnerable to:
  - case changes
  - separator changes
  - camelCase
  - mixed word order / spacing
- v2.3 matches *tokens*, not literal substrings.

Run:
```bash
python tools/arch_lint/arch_lint_v2_3.py <repo_root>
```

## Pattern types

1) **Direct term scan** (case-insensitive substring) for known hard bans.
2) **Composite token scan:**
   - `'active%local%mods'` matches tokens `'active ... local ... mods'` with gaps.
3) **Near-window scan:**
   - flags required token sets appearing within N tokens.

## Allowlist

- raw substring allowlist (e.g., `'local_mods_folder'`)
- token sequence allowlist (e.g., `('local','mods','folder')`)

## Waiver

OS-only path ops allowed only in allowlisted modules or with:
```python
# CK3RAVEN_OS_PATH_OK: <reason>
```

## Tuning

- Add/remove composite rules in `COMPOSITE_RULES` and `NEAR_WINDOW_RULES`.
- Keep bans minimal and conceptual. Let token rules catch variants.
