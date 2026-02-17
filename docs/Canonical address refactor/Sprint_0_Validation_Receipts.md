# Sprint 0 Validation Receipts

> **Verified Commit:** `59412e26f5aa232228e6e9875e3bb2ed21a1190f`  
> **Date:** February 17, 2026  
> **Verified By:** Agent (session `cb62798e1eac4178`)  
> **Status:** FROZEN — no changes to Sprint 0 tests or WA2 semantics without explicit re-opening by Nate

---

## Artifact 1: Full Pytest Output (92/92)

```
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0
cachedir: .pytest_cache
rootdir: C:\Users\nateb\Documents\CK3 Mod Project 1.18\ck3raven
configfile: pyproject.toml
plugins: anyio-4.12.1, cov-7.0.0

tests/sprint0/test_dir_ops.py::TestDIR01PwdDefault::test_pwd_default PASSED
tests/sprint0/test_dir_ops.py::TestDIR02CdChangesHome::test_cd_then_pwd PASSED
tests/sprint0/test_dir_ops.py::TestDIR02CdChangesHome::test_cd_bare_key PASSED
tests/sprint0/test_dir_ops.py::TestDIR03CdInvalid::test_cd_bogus_root PASSED
tests/sprint0/test_dir_ops.py::TestDIR03CdInvalid::test_cd_subdirectory_rejected PASSED
tests/sprint0/test_dir_ops.py::TestDIR04ListHome::test_list_default_home PASSED
tests/sprint0/test_dir_ops.py::TestDIR05ListExplicit::test_list_repo_src PASSED
tests/sprint0/test_dir_ops.py::TestDIR06ListNonDir::test_list_file_raises PASSED
tests/sprint0/test_dir_ops.py::TestDIR07ListNonExistent::test_list_nonexistent_raises PASSED
tests/sprint0/test_dir_ops.py::TestDIR08ListHostPath::test_host_path_rejected PASSED
tests/sprint0/test_dir_ops.py::TestDIR09TreeDefault::test_tree_repo PASSED
tests/sprint0/test_dir_ops.py::TestDIR10TreeCustomDepth::test_tree_depth_1 PASSED
tests/sprint0/test_dir_ops.py::TestDIR11NoHostPathsInOutput::test_pwd_no_leak PASSED
tests/sprint0/test_dir_ops.py::TestDIR11NoHostPathsInOutput::test_cd_no_leak PASSED
tests/sprint0/test_dir_ops.py::TestDIR11NoHostPathsInOutput::test_list_no_leak PASSED
tests/sprint0/test_dir_ops.py::TestDIR11NoHostPathsInOutput::test_tree_no_leak PASSED
tests/sprint0/test_e2e_canonical_addressing.py::TestE2E01ResolveListRoundTrip::test_full_round_trip PASSED
tests/sprint0/test_e2e_canonical_addressing.py::TestE2E02CdThenRelativeList::test_cd_then_relative PASSED
tests/sprint0/test_e2e_canonical_addressing.py::TestE2E03LegacyNormalization::test_legacy_root_input PASSED
tests/sprint0/test_leak_detector.py::TestLEAK01WindowsDrive::test_windows_drive PASSED
tests/sprint0/test_leak_detector.py::TestLEAK02UNC::test_unc_path PASSED
tests/sprint0/test_leak_detector.py::TestLEAK03MacOS::test_macos_home PASSED
tests/sprint0/test_leak_detector.py::TestLEAK04Linux::test_linux_home PASSED
tests/sprint0/test_leak_detector.py::TestLEAK05WSL::test_wsl_mount PASSED
tests/sprint0/test_leak_detector.py::TestLEAK06Nested::test_nested_in_list PASSED
tests/sprint0/test_leak_detector.py::TestLEAK06Nested::test_deeply_nested_dict PASSED
tests/sprint0/test_leak_detector.py::TestLEAK06Nested::test_nested_in_tuple PASSED
tests/sprint0/test_leak_detector.py::TestLEAK07SessionAbsPass::test_root_address PASSED
tests/sprint0/test_leak_detector.py::TestLEAK07SessionAbsPass::test_mod_address PASSED
tests/sprint0/test_leak_detector.py::TestLEAK07SessionAbsPass::test_nested_addresses PASSED
tests/sprint0/test_leak_detector.py::TestLEAK08EmptyNone::test_empty_dict PASSED
tests/sprint0/test_leak_detector.py::TestLEAK08EmptyNone::test_none_value PASSED
tests/sprint0/test_leak_detector.py::TestLEAK08EmptyNone::test_empty_string PASSED
tests/sprint0/test_leak_detector.py::TestLEAK08EmptyNone::test_int_value PASSED
tests/sprint0/test_leak_detector.py::TestLEAK08EmptyNone::test_bool_value PASSED
tests/sprint0/test_normalization.py::TestNORM01LegacyRootAccepted::test_legacy_root_repo PASSED
tests/sprint0/test_normalization.py::TestNORM01LegacyRootAccepted::test_legacy_root_game PASSED
tests/sprint0/test_normalization.py::TestNORM01LegacyRootAccepted::test_legacy_root_ck3raven_data PASSED
tests/sprint0/test_normalization.py::TestNORM02LegacyModAccepted::test_legacy_mod_colon_slash PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_root[root:repo/src/server.py] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_root[ROOT_REPO:/src/server.py] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_root[mod:TestModA/common] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_root[mod:TestModA:/common] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_root[root:game/common/traits/00_traits.txt] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_mod[mod:TestModA/common] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_session_abs_no_legacy_mod[mod:TestModA:/common] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_root_category_lowercase[root:repo/src/server.py] PASSED
tests/sprint0/test_normalization.py::TestNORM03NeverEmitsLegacy::test_root_category_lowercase[ROOT_REPO:/src/server.py] PASSED
tests/sprint0/test_registry.py::TestREG01HostPathRecovery::test_basic_recovery PASSED
tests/sprint0/test_registry.py::TestREG01HostPathRecovery::test_directory_recovery PASSED
tests/sprint0/test_registry.py::TestREG02InvalidToken::test_fabricated_token PASSED
tests/sprint0/test_registry.py::TestREG03MaxTokensCap::test_hard_cap PASSED
tests/sprint0/test_registry.py::TestREG04TokenUniquenessVolume::test_1000_unique_tokens PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE01V2ImportsIsolated::test_no_unauthorized_imports PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE02V1Unchanged::test_v1_no_v2_references PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/unified_tools.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/workspace.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/contracts.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/file_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/search_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/conflict_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/playset_ops.py] PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_token_readable PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_session_abs_readable PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_frozen_token PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_frozen_session_abs PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_str_returns_session_abs PASSED
tests/sprint0/test_visibility_ref.py::TestVR01Immutability::test_repr_format PASSED
tests/sprint0/test_visibility_ref.py::TestVR02NoHostPath::test_token_is_not_path PASSED
tests/sprint0/test_visibility_ref.py::TestVR02NoHostPath::test_session_abs_is_canonical PASSED
tests/sprint0/test_visibility_ref.py::TestVR03TokenUUID4::test_valid_uuid4 PASSED
tests/sprint0/test_visibility_ref.py::TestVR04UniqueTokens::test_two_resolves_different_tokens PASSED
tests/sprint0/test_visibility_ref.py::TestVR04UniqueTokens::test_same_session_abs PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA201RootResolution::test_resolves_ok[root:repo/src/server.py-root:repo/src/server.py] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA201RootResolution::test_resolves_ok[root:repo/src-root:repo/src] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA201RootResolution::test_resolves_ok[root:ck3raven_data/wip/analysis.py-root:ck3raven_data/wip/analysis.py] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA201RootResolution::test_resolves_ok[root:game/common/traits/00_traits.txt-root:game/common/traits/00_traits.txt] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA202ModResolution::test_resolves_ok[mod:TestModA/common/traits/zzz_patch.txt-mod:TestModA/common/traits/zzz_patch.txt] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA202ModResolution::test_resolves_ok[mod:TestModA/common-mod:TestModA/common] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA203UnknownRootKey::test_bogus_key PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA204UnknownMod::test_nonexistent_mod PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA205HostAbsoluteRejected::test_host_path_rejected[C:\\Users\\test\\file.txt] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA205HostAbsoluteRejected::test_host_path_rejected[/home/test/file.txt] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA205HostAbsoluteRejected::test_host_path_rejected[/Users/nate/Documents/foo] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA206PathTraversal::test_traversal_rejected[root:repo/../../../etc/passwd] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA206PathTraversal::test_traversal_rejected[mod:TestModA/../../secret] PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA207RequireExistsMissing::test_missing_file PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA208RequireExistsFalse::test_missing_ok PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA208RequireExistsFalse::test_host_path_recovery PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA209RequireExistsFalseStillValidated::test_bogus_key PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA209RequireExistsFalseStillValidated::test_traversal_escape PASSED
tests/sprint0/test_world_adapter_v2.py::TestWA210NonTruncation::test_full_path_preserved PASSED

======================== 92 passed, 1 warning in 3.16s ========================
```

---

## Artifact 2: Durations (`--durations=20`)

```
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0
92 passed in 2.75s

============================= slowest 20 durations ============================
1.99s call   tests/sprint0/test_registry.py::TestREG03MaxTokensCap::test_hard_cap
0.18s call   tests/sprint0/test_registry.py::TestREG04TokenUniquenessVolume::test_1000_unique_tokens
0.08s call   tests/sprint0/test_v2_purity_gate.py::TestGATE01V2ImportsIsolated::test_no_unauthorized_imports

(remaining 89 tests each < 0.01s)
```

Real execution confirmed: REG-03 (10,000 token cap) takes ~2s of actual compute.

---

## Artifact 3: Mutation Sensitivity Proof

### Mutation Applied

**File:** `tools/ck3lens_mcp/ck3lens/world_adapter_v2.py`, line ~234  
**Original:** `token = str(uuid.uuid4())`  
**Mutated to:** `token = "MUTATION-CONSTANT-TOKEN"`

### Tests Executed Under Mutation

```
pytest tests/sprint0/test_registry.py tests/sprint0/test_visibility_ref.py -v --tb=short

FAILED tests/sprint0/test_registry.py::TestREG03MaxTokensCap::test_hard_cap
  → AssertionError: assert not True (constant token overwrites same registry key, cap never reached)

FAILED tests/sprint0/test_registry.py::TestREG04TokenUniquenessVolume::test_1000_unique_tokens
  → assert 1 == 1000 (set({'MUTATION-CONSTANT-TOKEN'}) has cardinality 1)

FAILED tests/sprint0/test_visibility_ref.py::TestVR03TokenUUID4::test_valid_uuid4
  → ValueError: badly formed hexadecimal UUID string

FAILED tests/sprint0/test_visibility_ref.py::TestVR04UniqueTokens::test_two_resolves_different_tokens
  → assert 'MUTATION-CONSTANT-TOKEN' != 'MUTATION-CONSTANT-TOKEN'

4 failed, 12 passed, 1 warning in 2.72s
```

### Revert & Re-green

Mutation reverted → `token = str(uuid.uuid4())` restored → **92 passed, 2.94s**.  
File size matches original: 13,474 bytes.

---

## Artifact 4: Git Revision Proof

```
$ git rev-parse HEAD
59412e26f5aa232228e6e9875e3bb2ed21a1190f

$ git status --porcelain
(empty — clean working tree)

$ git diff --stat
(empty — no uncommitted changes)
```

Working tree is clean at the verified commit.

---

## Artifact 5: Purity Gate Standalone

```
============================= test session starts =============================
platform win32 -- Python 3.13.12, pytest-9.0.2, pluggy-1.6.0

tests/sprint0/test_v2_purity_gate.py::TestGATE01V2ImportsIsolated::test_no_unauthorized_imports PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE02V1Unchanged::test_v1_no_v2_references PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/unified_tools.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/workspace.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/contracts.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/file_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/search_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/conflict_ops.py] PASSED
tests/sprint0/test_v2_purity_gate.py::TestGATE03NoV2InV1Tools::test_no_v2_import[ck3lens/impl/playset_ops.py] PASSED

======================== 9 passed, 1 warning in 0.16s =========================
```

All 3 gate categories pass:
- **GATE-01:** V2 modules import only from allowed set (stdlib, typing, pathlib, uuid, dataclasses, re)
- **GATE-02:** V1 world_adapter.py contains no references to v2 modules
- **GATE-03:** 7 V1 tool modules scanned via AST — none import WA2

---

## Sprint 0 Scope (Frozen)

| Component | File | Status |
|-----------|------|--------|
| WorldAdapterV2 | `tools/ck3lens_mcp/ck3lens/world_adapter_v2.py` | Verified |
| VisibilityRef | (within world_adapter_v2.py) | Verified |
| VisibilityResolution | (within world_adapter_v2.py) | Verified |
| LeakDetector | `tools/ck3lens_mcp/ck3lens/leak_detector.py` | Verified |
| dir_ops | `tools/ck3lens_mcp/ck3lens/impl/dir_ops.py` | Verified |
| v2_isolation purity gate | `linters/arch_lint/v2_isolation.py` | Verified |
| Reply codes (DIR) | `tools/ck3lens_mcp/ck3lens/reply_codes.py` | Verified |
| Test suite (92 tests) | `tests/sprint0/` | Verified |
