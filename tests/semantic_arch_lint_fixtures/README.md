# Arch-lint + CK3 semantic/syntax lint fixtures

These fixtures are **deliberately small** and designed to test:

- **ARCH-LINT** (Python architecture constraints)
- **Python semantic undefined refs** (via `pyright`/Pylance JSON)
- **CK3 syntax errors** (parser failures)
- **CK3 semantic undefined refs** (symbols DB-backed validator)
- **NST governance** (new definitions introduced by an edit)

## Layout

- `arch_lint/`
  - `single_file/`: stand-alone files that should trigger arch-lint/NST behaviors.
  - `diff_edits/`: realistic "subset edit" scenarios with `base/`, `after/`, and `changes.diff`.

- `ck3_semantic/`
  - `single_file/`: stand-alone CK3 script snippets (valid / invalid).
  - `diff_edits/`: realistic "subset edit" scenarios with `base/`, `after/`, and `changes.diff`.

## How to use (manual)

### Arch-lint
1. Copy the relevant file(s) into your repo where arch-lint runs (or point your arch-lint runner at these paths).
2. Confirm:
   - Expected **FAIL** cases fail with the intended rule(s).
   - Expected **PASS** cases pass.

### CK3 semantic/syntax lint
1. Ensure you have a symbols DB built for a known playset.
2. Run your CK3 parser/semantic validator against the `after/` files.
3. Confirm:
   - Syntax error cases are reported as parser failures.
   - Undefined symbol cases are reported as undefined references.
   - “definitions added” cases detect only newly introduced defs (post - pre).

## Expected outcomes
Each fixture directory includes an `expected.json` describing the intended result at a high level.
