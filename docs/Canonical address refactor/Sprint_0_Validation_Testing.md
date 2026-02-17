# Sprint 0 — Validation Testing Proposal

> **Date:** February 17, 2026
> **Scope:** WorldAdapterV2, VisibilityRef, ck3_dir, leak detector, purity gate
> **Directive:** Canonical Addressing Refactor Directive (Authoritative)

---

## Overview

This document defines the validation tests for Sprint 0. Tests are organized by component, matching the directive's structure. Each test has an ID, description, and pass/fail criteria.

All tests use `pytest`. The `CK3LENS_SIGIL_SECRET` fixture is NOT required (Sigil encryption was removed per directive §3). Tests create a `WorldAdapterV2` instance with injected root paths and mod paths — no database or live config needed.

---

## Test Fixtures (Shared)

```python
# conftest.py additions or local fixture

@pytest.fixture
def tmp_roots(tmp_path):
    """Create a minimal root structure for WA2 testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "server.py").write_text("# server")
    (repo / "docs").mkdir()
    (repo / "pyproject.toml").write_text("[project]")

    data = tmp_path / "ck3raven_data"
    data.mkdir()
    (data / "wip").mkdir()
    (data / "wip" / "analysis.py").write_text("# wip")

    game = tmp_path / "game"
    game.mkdir()
    (game / "common" / "traits").mkdir(parents=True)
    (game / "common" / "traits" / "00_traits.txt").write_text("# traits")

    return {
        "repo": repo,
        "ck3raven_data": data,
        "game": game,
    }

@pytest.fixture
def tmp_mods(tmp_path):
    """Create mock mod directories."""
    mod_a = tmp_path / "mods" / "TestModA"
    mod_a.mkdir(parents=True)
    (mod_a / "common" / "traits").mkdir(parents=True)
    (mod_a / "common" / "traits" / "zzz_patch.txt").write_text("# patch")

    return {"TestModA": mod_a}

@pytest.fixture
def wa2(tmp_roots, tmp_mods):
    """WorldAdapterV2 instance with test roots and mods."""
    return WorldAdapterV2(
        roots={
            "repo": tmp_roots["repo"],
            "ck3raven_data": tmp_roots["ck3raven_data"],
            "game": tmp_roots["game"],
        },
        mod_paths=tmp_mods,
    )
```

---

## 1. VisibilityRef Tests

### VR-01: Immutability

**Description:** VisibilityRef is a frozen dataclass. Attributes cannot be set or deleted after creation.

**Criteria:**
- `vis_ref.token` returns the UUID string
- `vis_ref.session_abs` returns the canonical address
- Attempting `vis_ref.token = "x"` raises `FrozenInstanceError` (or `AttributeError`)
- `str(vis_ref)` returns `session_abs` value
- `repr(vis_ref)` returns `VisibilityRef(<session_abs>)`

### VR-02: No Host Path on Object

**Description:** The VisibilityRef object contains no host-absolute path in any attribute.

**Criteria:**
- `vis_ref.token` is a UUID4 string (not a path)
- `vis_ref.session_abs` matches `root:<key>/...` or `mod:<name>/...` pattern
- No attribute on the object contains a string starting with a drive letter or `/home/` or `/Users/`

### VR-03: Token is UUID4

**Description:** Each VisibilityRef has a valid UUID4 token.

**Criteria:**
- `uuid.UUID(vis_ref.token, version=4)` does NOT raise

### VR-04: Unique Tokens per Resolve

**Description:** Every call to `resolve()` mints a fresh token, even for the same input.

**Criteria:**
- `wa2.resolve("root:repo/src")` called twice → two different `.ref.token` values
- Both `.ref.session_abs` are identical (`root:repo/src`)

---

## 2. WorldAdapterV2 — Resolution Tests

### WA2-01: Root Address Resolution

**Description:** Canonical `root:<key>/<path>` addresses resolve correctly.

**Criteria:**

| Input | Expected session_abs | Expected exists |
|-------|---------------------|-----------------|
| `root:repo/src/server.py` | `root:repo/src/server.py` | `True` |
| `root:repo/src` | `root:repo/src` | `True` |
| `root:ck3raven_data/wip/analysis.py` | `root:ck3raven_data/wip/analysis.py` | `True` |
| `root:game/common/traits/00_traits.txt` | `root:game/common/traits/00_traits.txt` | `True` |

All return `ok=True`, with a valid `VisibilityRef`.

### WA2-02: Mod Address Resolution

**Description:** Canonical `mod:<Name>/<path>` addresses resolve correctly.

**Criteria:**

| Input | Expected session_abs | Expected exists |
|-------|---------------------|-----------------|
| `mod:TestModA/common/traits/zzz_patch.txt` | `mod:TestModA/common/traits/zzz_patch.txt` | `True` |
| `mod:TestModA/common` | `mod:TestModA/common` | `True` |

All return `ok=True`.

### WA2-03: Unknown Root Key → Invalid

**Description:** Using an invalid root key fails.

**Criteria:**
- `wa2.resolve("root:bogus/foo")` → `ok=False`, `error_message` is `"Invalid path / not found"`

### WA2-04: Unknown Mod → Invalid

**Description:** Referencing a mod not in `mod_paths` fails.

**Criteria:**
- `wa2.resolve("mod:NonexistentMod/foo")` → `ok=False`

### WA2-05: Host-Absolute Path → Invalid

**Description:** Raw host paths are rejected (Invariant A).

**Criteria:**
- `wa2.resolve("C:\\Users\\test\\file.txt")` → `ok=False`
- `wa2.resolve("/home/test/file.txt")` → `ok=False`
- `wa2.resolve("/Users/nate/Documents/foo")` → `ok=False`

### WA2-06: Path Traversal Rejected

**Description:** `..` components that escape a root are rejected.

**Criteria:**
- `wa2.resolve("root:repo/../../../etc/passwd")` → `ok=False`
- `wa2.resolve("mod:TestModA/../../secret")` → `ok=False`

### WA2-07: require_exists=True, Path Missing → Invalid

**Description:** When `require_exists=True` (default), non-existent paths fail.

**Criteria:**
- `wa2.resolve("root:repo/nonexistent.py")` → `ok=False`

### WA2-08: require_exists=False, Path Missing → Success with exists=False

**Description:** When `require_exists=False`, structurally valid but non-existent paths succeed.

**Criteria:**
- `res = wa2.resolve("root:repo/nonexistent.py", require_exists=False)` → `ok=True`, `res.exists=False`
- `res.ref` is a valid VisibilityRef
- `wa2.host_path(res.ref)` returns a `Path` under the repo root

### WA2-09: require_exists=False, Root Still Validated

**Description:** Even with `require_exists=False`, invalid root keys or path escapes still fail.

**Criteria:**
- `wa2.resolve("root:bogus/foo", require_exists=False)` → `ok=False`
- `wa2.resolve("root:repo/../../escape", require_exists=False)` → `ok=False`

---

## 3. Input Normalization Tests

### NORM-01: Legacy ROOT_X:/ Accepted

**Description:** Sprint 0 accepts legacy `ROOT_REPO:/...` syntax and normalizes to `root:repo/...`.

**Criteria:**
- `wa2.resolve("ROOT_REPO:/src/server.py")` → `ok=True`
- `res.ref.session_abs == "root:repo/src/server.py"`

### NORM-02: Legacy mod:Name:/ Accepted

**Description:** Sprint 0 accepts `mod:Name:/path` (colon-slash separator) and normalizes.

**Criteria:**
- `wa2.resolve("mod:TestModA:/common/traits")` → `ok=True`
- `res.ref.session_abs == "mod:TestModA/common/traits"`

### NORM-03: Emitter Never Produces Legacy Forms

**Description:** No VisibilityResolution or VisibilityRef contains `ROOT_` prefix or `:/` separator.

**Criteria:**
- For every successful resolution, `res.ref.session_abs` does NOT contain `ROOT_`
- For every successful resolution, `res.ref.session_abs` does NOT match `mod:.*:/`
- `res.root_category` uses lowercase key form (e.g., `"repo"`, not `"ROOT_REPO"`)

---

## 4. Token Registry Tests

### REG-01: host_path Recovery

**Description:** `wa2.host_path(ref)` recovers the correct host-absolute Path.

**Criteria:**
- `res = wa2.resolve("root:repo/src/server.py")`
- `host = wa2.host_path(res.ref)`
- `host` is a `Path` instance
- `host.exists()` is `True`
- `host.name == "server.py"`

### REG-02: Invalid Token → None

**Description:** A fabricated or expired VisibilityRef returns None from `host_path`.

**Criteria:**
- `fake_ref = VisibilityRef(token="not-a-real-token", session_abs="root:repo/x")`
- `wa2.host_path(fake_ref)` returns `None`

### REG-03: MAX_TOKENS Hard Cap

**Description:** Registry raises deterministic error at 10,000 tokens.

**Criteria:**
- Resolve 10,000 distinct paths successfully
- The 10,001st resolve returns `ok=False` with message containing `"capacity exceeded"`

### REG-04: Token Uniqueness Under Volume

**Description:** 1,000 resolves of the same input produce 1,000 unique tokens.

**Criteria:**
- `tokens = [wa2.resolve("root:repo/src", require_exists=False).ref.token for _ in range(1000)]`
- `len(set(tokens)) == 1000`

---

## 5. Leak Detector Tests

### LEAK-01: Detects Windows Drive Path

**Criteria:** `check_no_host_paths({"path": "C:\\Users\\nate\\file.txt"})` raises `ValueError`

### LEAK-02: Detects UNC Path

**Criteria:** `check_no_host_paths({"path": "\\\\server\\share"})` raises `ValueError`

### LEAK-03: Detects macOS Home Path

**Criteria:** `check_no_host_paths({"path": "/Users/nate/Documents"})` raises `ValueError`

### LEAK-04: Detects Linux Home Path

**Criteria:** `check_no_host_paths({"path": "/home/nate/code"})` raises `ValueError`

### LEAK-05: Detects WSL/Mount Path

**Criteria:** `check_no_host_paths({"path": "/mnt/c/Users/nate"})` raises `ValueError`

### LEAK-06: Nested Detection

**Description:** Host paths buried in nested structures are found.

**Criteria:**
- `check_no_host_paths({"entries": [{"name": "x", "path": "C:\\bad"}]})` raises
- `check_no_host_paths({"a": {"b": {"c": "/home/nate/x"}}})` raises

### LEAK-07: Session-Absolute Addresses Pass

**Description:** Canonical addresses do NOT trigger false positives.

**Criteria:**
- `check_no_host_paths({"path": "root:repo/src/server.py"})` does NOT raise
- `check_no_host_paths({"path": "mod:TestMod/common/traits"})` does NOT raise
- `check_no_host_paths({"entries": [{"path": "root:game/common/"}]})` does NOT raise

### LEAK-08: Empty and None Values Pass

**Criteria:**
- `check_no_host_paths({})` does NOT raise
- `check_no_host_paths({"x": None})` does NOT raise
- `check_no_host_paths({"x": ""})` does NOT raise

---

## 6. ck3_dir Command Tests

### DIR-01: pwd Returns Default Home

**Description:** Initial `pwd` returns `ROOT_CK3RAVEN_DATA`.

**Criteria:**
- Reply is Success
- `data["home"] == "root:ck3raven_data/"`
- `data["root_category"] == "ck3raven_data"`

### DIR-02: cd Changes Home

**Description:** `cd root:repo` changes the home root.

**Criteria:**
- `cd root:repo` → Success
- Subsequent `pwd` → `data["home"] == "root:repo/"`

### DIR-03: cd Invalid Root → Invalid

**Criteria:**
- `cd root:bogus` → Invalid reply
- `cd root:repo/some/subdir` → Invalid reply (subdirectory homing not allowed in Sprint 0)

### DIR-04: list Home Directory

**Description:** `list` with no path lists the current home directory.

**Criteria:**
- Reply is Success
- `data["entries"]` is a list of dicts with `name`, `path`, `type` keys
- All `path` values are session-absolute (`root:...` or `mod:...`)
- No `path` value contains a host-absolute path

### DIR-05: list Explicit Path

**Description:** `list root:repo/src` lists contents of the src directory.

**Criteria:**
- Reply is Success
- `data["entries"]` contains an entry with `name == "server.py"` and `type == "file"`

### DIR-06: list Non-Directory → Invalid

**Criteria:**
- `list root:repo/pyproject.toml` → Invalid reply (it's a file, not a directory)

### DIR-07: list Non-Existent → Invalid

**Criteria:**
- `list root:repo/nonexistent_dir` → Invalid reply

### DIR-08: list Host Path Input → Invalid

**Criteria:**
- `list C:\Users\nate\Documents` → Invalid reply (Invariant A — host paths rejected)

### DIR-09: tree Default Depth

**Description:** `tree` returns directory structure with default depth=3.

**Criteria:**
- Reply is Success
- `data["directories"]` is a list/tree structure
- `data["depth"] == 3`
- All path values are session-absolute

### DIR-10: tree Custom Depth

**Criteria:**
- `tree root:repo depth=1` → directories only 1 level deep

### DIR-11: No Host Paths in Any Output

**Description:** Run leak detector on Reply.data for every successful dir command.

**Criteria:**
- `check_no_host_paths(reply.data)` does NOT raise for any of DIR-01 through DIR-10

---

## 7. Purity Gate Tests

### GATE-01: v2 Module Imports Are Isolated

**Description:** The arch_lint v2_isolation rule passes on the Sprint 0 codebase.

**Criteria:**
- No file in `tools/ck3lens_mcp/` outside the allowed set imports from `world_adapter_v2`
- Allowed importers: `world_adapter_v2.py`, `impl/dir_ops.py`, `leak_detector.py`, `server.py`, any `*_v2.py`

### GATE-02: v1 WorldAdapter Unchanged

**Description:** `world_adapter.py` has zero diff from before Sprint 0.

**Criteria:**
- `git diff HEAD -- tools/ck3lens_mcp/ck3lens/world_adapter.py` produces no output

### GATE-03: No v2 Imports in v1 Tools

**Description:** The following files must NOT import anything from `world_adapter_v2`:
- `unified_tools.py`
- `workspace.py`
- `enforcement.py`
- `db_queries.py`
- `impl/file_ops.py`
- `impl/search_ops.py`
- `impl/conflict_ops.py`
- `impl/playset_ops.py`

**Criteria:**
- `grep -r "world_adapter_v2" <file>` returns nothing for each listed file

---

## 8. Integration / End-to-End Tests

### E2E-01: Full Resolve → list Round-Trip

**Description:** Resolve a path via WA2, get a VisibilityRef, recover host path, list directory contents — verifying no host paths leak into the Reply.

**Criteria:**
1. `wa2.resolve("root:repo/src")` → Success
2. `wa2.host_path(res.ref)` → valid `Path`
3. `ck3_dir_impl(command="list", path="root:repo/src", wa_v2=wa2, rb=rb)` → Success reply
4. Leak detector passes on the reply data
5. Entries contain `server.py`

### E2E-02: cd Then Relative list

**Description:** Change home to `root:repo`, then list with a relative path.

**Criteria:**
1. `ck3_dir_impl(command="cd", path="root:repo", ...)` → Success
2. `ck3_dir_impl(command="list", path="src", ...)` → Success (resolves as `root:repo/src`)
3. Entries contain `server.py`

### E2E-03: Legacy Input Normalization Through ck3_dir

**Description:** Use legacy syntax through ck3_dir and verify normalized output.

**Criteria:**
1. `ck3_dir_impl(command="list", path="ROOT_REPO:/src", ...)` → Success
2. All paths in `reply.data["entries"]` use `root:repo/...` form (not `ROOT_REPO:/...`)

---

## Test File Locations

| File | Contents |
|------|----------|
| `tests/test_world_adapter_v2.py` | Sections 1-4 (VR-*, WA2-*, NORM-*, REG-*) |
| `tests/test_leak_detector.py` | Section 5 (LEAK-*) |
| `tests/test_dir_ops.py` | Section 6 (DIR-*) |
| `tests/test_v2_purity_gate.py` | Section 7 (GATE-*) |
| `tests/test_e2e_canonical_addressing.py` | Section 8 (E2E-*) |

---

## Pass Criteria for Sprint 0 Completion

**All of the following must be true:**

1. All 40+ tests pass (`pytest tests/test_world_adapter_v2.py tests/test_leak_detector.py tests/test_dir_ops.py tests/test_v2_purity_gate.py tests/test_e2e_canonical_addressing.py`)
2. Purity gate passes — no v1 module imports from v2
3. Leak detector catches all 5 host-path patterns and produces zero false positives on canonical addresses
4. `world_adapter.py` (v1) is byte-for-byte unchanged
5. `ck3_dir` commands produce only canonical `root:key/path` and `mod:name/path` forms in output
6. Token registry hard cap at 10,000 produces deterministic error
