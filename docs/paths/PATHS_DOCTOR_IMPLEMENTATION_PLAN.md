# Paths Doctor Implementation Plan

> **Status:** READY FOR REVIEW  
> **Date:** February 5, 2026  
> **Spec:** See PATHS_DESIGN_BRIEF_v3.md Section 8

---

## Overview

Implement `ck3lens/paths_doctor.py` - a read-only diagnostic utility for validating path configuration.

---

## Implementation Tasks

### Task 1: Create Core Data Structures

**File:** `ck3lens/paths_doctor.py`

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class DoctorFinding:
    id: str                 # e.g. PD-ROOT-GAME-MISSING
    severity: Literal["OK", "WARN", "ERROR"]
    subject: str            # e.g. ROOT_GAME, WIP_DIR
    message: str
    remediation: str | None

@dataclass(frozen=True)
class PathsDoctorReport:
    ok: bool
    findings: tuple[DoctorFinding, ...]
    summary: dict[str, int]
    config_path: str | None
```

---

### Task 2: Implement Root Validation Checks

**Functions to implement:**

```python
def _check_required_roots() -> list[DoctorFinding]:
    """Check ROOT_GAME and ROOT_STEAM are configured and exist."""
    findings = []
    
    # ROOT_GAME
    if ROOT_GAME is None:
        findings.append(DoctorFinding(
            id="PD-ROOT-GAME-MISSING",
            severity="ERROR",
            subject="ROOT_GAME",
            message="ROOT_GAME is not configured",
            remediation="Set game_path in ~/.ck3raven/config/workspace.toml"
        ))
    elif not ROOT_GAME.exists():
        findings.append(DoctorFinding(
            id="PD-ROOT-GAME-NOTFOUND",
            severity="ERROR",
            subject="ROOT_GAME",
            message=f"ROOT_GAME path does not exist: {ROOT_GAME}",
            remediation="Verify game_path points to CK3 install directory"
        ))
    elif not ROOT_GAME.is_dir():
        findings.append(DoctorFinding(
            id="PD-ROOT-GAME-NOTDIR",
            severity="ERROR",
            subject="ROOT_GAME",
            message=f"ROOT_GAME is not a directory: {ROOT_GAME}",
            remediation="game_path must be a directory, not a file"
        ))
    else:
        findings.append(DoctorFinding(
            id="PD-ROOT-GAME-OK",
            severity="OK",
            subject="ROOT_GAME",
            message=f"ROOT_GAME: {ROOT_GAME}",
            remediation=None
        ))
    
    # Similar for ROOT_STEAM...
    return findings

def _check_optional_roots() -> list[DoctorFinding]:
    """Check optional roots (ROOT_USER_DOCS, ROOT_UTILITIES, etc.)."""
    # Warn if None or not exists, but not ERROR
    ...

def _check_computed_roots() -> list[DoctorFinding]:
    """Check ROOT_REPO and ROOT_CK3RAVEN_DATA."""
    # These are always computed, but verify they exist
    ...
```

**Finding IDs:**

| ID | Severity | Condition |
|----|----------|-----------|
| PD-ROOT-GAME-MISSING | ERROR | ROOT_GAME is None |
| PD-ROOT-GAME-NOTFOUND | ERROR | Path doesn't exist |
| PD-ROOT-GAME-NOTDIR | ERROR | Path is file, not dir |
| PD-ROOT-GAME-OK | OK | Valid |
| PD-ROOT-STEAM-* | (same pattern) | |
| PD-ROOT-USER-DOCS-* | WARN | Optional |
| PD-ROOT-UTILITIES-* | WARN | Optional |
| PD-ROOT-LAUNCHER-* | WARN | Optional |
| PD-ROOT-VSCODE-* | WARN | Optional |
| PD-ROOT-REPO-* | ERROR/OK | Computed, should always exist |
| PD-ROOT-DATA-* | ERROR/OK | Computed |

---

### Task 3: Implement CK3RAVEN_DATA Structure Checks

```python
def _check_data_structure() -> list[DoctorFinding]:
    """Check expected subdirectories under ROOT_CK3RAVEN_DATA."""
    findings = []
    
    # Check expected directories
    expected_dirs = [
        (WIP_DIR, "wip"),
        (PLAYSET_DIR, "playsets"),
        (LOGS_DIR, "logs"),
        (CONFIG_DIR, "config"),
    ]
    
    for path, name in expected_dirs:
        if not path.exists():
            findings.append(DoctorFinding(
                id=f"PD-DATA-{name.upper()}-MISSING",
                severity="WARN",
                subject=name,
                message=f"{name}/ directory missing: {path}",
                remediation=f"Directory will be created on first use"
            ))
    
    # Check DB_PATH (special - file not dir)
    if DB_PATH.exists():
        if DB_PATH.is_dir():
            findings.append(DoctorFinding(
                id="PD-DATA-DB-ISDIR",
                severity="ERROR",
                subject="DB_PATH",
                message=f"DB_PATH is a directory, should be a file: {DB_PATH}",
                remediation="Remove the directory and run the builder daemon"
            ))
    else:
        findings.append(DoctorFinding(
            id="PD-DATA-DB-MISSING",
            severity="WARN",
            subject="DB_PATH",
            message=f"Database not found: {DB_PATH}",
            remediation="Run 'python -m qbuilder.cli daemon' to create"
        ))
    
    return findings
```

**Finding IDs:**

| ID | Severity | Condition |
|----|----------|-----------|
| PD-DATA-WIP-MISSING | WARN | wip/ doesn't exist |
| PD-DATA-PLAYSETS-MISSING | WARN | playsets/ doesn't exist |
| PD-DATA-LOGS-MISSING | WARN | logs/ doesn't exist |
| PD-DATA-CONFIG-MISSING | WARN | config/ doesn't exist |
| PD-DATA-DB-ISDIR | ERROR | ck3raven.db is a directory |
| PD-DATA-DB-MISSING | WARN | Database not created yet |

---

### Task 4: Implement Local Mods Folder Check

```python
def _check_local_mods() -> list[DoctorFinding]:
    """Check LOCAL_MODS_FOLDER validity."""
    if LOCAL_MODS_FOLDER is None:
        return [DoctorFinding(
            id="PD-LOCALMODS-NOTCONFIGURED",
            severity="WARN",
            subject="LOCAL_MODS_FOLDER",
            message="Local mods folder not configured",
            remediation="Set local_mods_folder in workspace.toml or configure ROOT_USER_DOCS"
        )]
    
    if not LOCAL_MODS_FOLDER.exists():
        return [DoctorFinding(
            id="PD-LOCALMODS-NOTFOUND",
            severity="WARN",
            subject="LOCAL_MODS_FOLDER",
            message=f"Local mods folder does not exist: {LOCAL_MODS_FOLDER}",
            remediation="Create the directory or check configuration"
        )]
    
    if not LOCAL_MODS_FOLDER.is_dir():
        return [DoctorFinding(
            id="PD-LOCALMODS-NOTDIR",
            severity="ERROR",
            subject="LOCAL_MODS_FOLDER",
            message=f"Local mods path is not a directory: {LOCAL_MODS_FOLDER}",
            remediation="local_mods_folder must point to a directory"
        )]
    
    return [DoctorFinding(
        id="PD-LOCALMODS-OK",
        severity="OK",
        subject="LOCAL_MODS_FOLDER",
        message=f"LOCAL_MODS_FOLDER: {LOCAL_MODS_FOLDER}",
        remediation=None
    )]
```

---

### Task 5: Implement Config Health Check

```python
def _check_config_health() -> list[DoctorFinding]:
    """Report config source and any errors."""
    findings = []
    
    # Report config path
    config_path = CONFIG_DIR / "workspace.toml"
    if config_path.exists():
        findings.append(DoctorFinding(
            id="PD-CONFIG-LOADED",
            severity="OK",
            subject="config",
            message=f"Config loaded from: {config_path}",
            remediation=None
        ))
    else:
        findings.append(DoctorFinding(
            id="PD-CONFIG-NOTFOUND",
            severity="WARN",
            subject="config",
            message=f"Config file not found: {config_path}",
            remediation="Run 'python -m ck3lens.config_loader' to create default"
        ))
    
    # Report any config errors from _config.errors
    for error in _config.errors:
        findings.append(DoctorFinding(
            id="PD-CONFIG-ERROR",
            severity="ERROR",
            subject="config",
            message=f"Config error: {error}",
            remediation="Fix the error in workspace.toml"
        ))
    
    # Report defaults in use
    for path_name in _config.paths.using_defaults:
        findings.append(DoctorFinding(
            id=f"PD-CONFIG-DEFAULT-{path_name.upper()}",
            severity="WARN",
            subject="config",
            message=f"Using OS-default for {path_name}",
            remediation=f"Configure {path_name} in workspace.toml"
        ))
    
    return findings
```

---

### Task 6: Implement Optional Resolution Cross-Checks

```python
def _check_resolution(world: WorldAdapter) -> list[DoctorFinding]:
    """Cross-check resolution against expected classifications."""
    findings = []
    
    test_cases = [
        # (path, expected_root_category, description)
        (str(WIP_DIR / "doctor_probe.txt"), RootCategory.ROOT_CK3RAVEN_DATA, "WIP path"),
        (str(ROOT_REPO / "pyproject.toml"), RootCategory.ROOT_REPO, "Repo path"),
    ]
    
    if LOCAL_MODS_FOLDER:
        test_cases.append(
            (str(LOCAL_MODS_FOLDER / "TestMod"), RootCategory.ROOT_USER_DOCS, "Local mod path")
        )
    
    for path, expected_root, desc in test_cases:
        try:
            result = world.resolve(path)
            if result.root_category != expected_root:
                findings.append(DoctorFinding(
                    id="PD-RESOLUTION-MISMATCH",
                    severity="ERROR",
                    subject="resolution",
                    message=f"{desc} resolved to {result.root_category}, expected {expected_root}",
                    remediation="Check resolution order in WorldAdapter"
                ))
        except Exception as e:
            findings.append(DoctorFinding(
                id="PD-RESOLUTION-ERROR",
                severity="ERROR",
                subject="resolution",
                message=f"Resolution failed for {desc}: {e}",
                remediation="Check WorldAdapter.resolve() implementation"
            ))
    
    if not findings:
        findings.append(DoctorFinding(
            id="PD-RESOLUTION-OK",
            severity="OK",
            subject="resolution",
            message="All resolution cross-checks passed",
            remediation=None
        ))
    
    return findings
```

---

### Task 7: Implement Main Entry Point

```python
def run_paths_doctor(*, include_resolution_checks: bool = True) -> PathsDoctorReport:
    """Run all diagnostic checks and return report."""
    all_findings: list[DoctorFinding] = []
    
    # 1. Root presence checks
    all_findings.extend(_check_required_roots())
    all_findings.extend(_check_optional_roots())
    all_findings.extend(_check_computed_roots())
    
    # 2. Data structure checks
    all_findings.extend(_check_data_structure())
    
    # 3. Local mods folder
    all_findings.extend(_check_local_mods())
    
    # 4. Config health
    all_findings.extend(_check_config_health())
    
    # 5. Optional resolution cross-checks
    if include_resolution_checks:
        try:
            from ck3lens.world_adapter import WorldAdapter
            world = WorldAdapter.create()
            all_findings.extend(_check_resolution(world))
        except Exception as e:
            all_findings.append(DoctorFinding(
                id="PD-RESOLUTION-INIT-ERROR",
                severity="WARN",
                subject="resolution",
                message=f"Could not initialize WorldAdapter: {e}",
                remediation="Resolution checks skipped"
            ))
    
    # Build summary
    summary = {"OK": 0, "WARN": 0, "ERROR": 0}
    for f in all_findings:
        summary[f.severity] += 1
    
    # Sort findings: ERROR first, then WARN, then OK
    severity_order = {"ERROR": 0, "WARN": 1, "OK": 2}
    sorted_findings = sorted(all_findings, key=lambda f: (severity_order[f.severity], f.id))
    
    return PathsDoctorReport(
        ok=(summary["ERROR"] == 0),
        findings=tuple(sorted_findings),
        summary=summary,
        config_path=str(CONFIG_DIR / "workspace.toml") if (CONFIG_DIR / "workspace.toml").exists() else None
    )
```

---

### Task 8: Implement CLI Entry Point

```python
# At bottom of paths_doctor.py

def _print_report(report: PathsDoctorReport) -> None:
    """Print human-readable report."""
    print("\n" + "=" * 60)
    print("PATHS DOCTOR REPORT")
    print("=" * 60)
    
    if report.config_path:
        print(f"\nConfig: {report.config_path}")
    
    print(f"\nSummary: {report.summary['ERROR']} errors, {report.summary['WARN']} warnings, {report.summary['OK']} ok")
    print(f"Status: {'HEALTHY' if report.ok else 'UNHEALTHY'}")
    
    print("\n" + "-" * 60)
    print("FINDINGS")
    print("-" * 60)
    
    for f in report.findings:
        icon = {"ERROR": "❌", "WARN": "⚠️", "OK": "✅"}[f.severity]
        print(f"\n{icon} [{f.id}] {f.subject}")
        print(f"   {f.message}")
        if f.remediation:
            print(f"   → {f.remediation}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    report = run_paths_doctor()
    _print_report(report)
    sys.exit(0 if report.ok else 1)
```

---

## File Structure

```
tools/ck3lens_mcp/ck3lens/
├── paths.py           # Constants (existing)
├── paths_doctor.py    # NEW - this implementation
├── world_adapter.py   # Resolution (existing)
└── ...
```

---

## Testing Strategy

### Unit Tests (after implementation)

```python
# tests/test_paths_doctor.py

def test_report_has_no_errors_when_configured():
    """With valid config, report.ok should be True."""
    report = run_paths_doctor()
    assert report.ok == True

def test_missing_game_path_is_error():
    """ROOT_GAME=None should produce ERROR finding."""
    # Would need to mock paths.ROOT_GAME = None
    ...

def test_severity_ordering():
    """Findings should be sorted ERROR, WARN, OK."""
    report = run_paths_doctor()
    severities = [f.severity for f in report.findings]
    # Check ordering...
```

### Manual Tests

1. Run `python -m ck3lens.paths_doctor` - verify output
2. Temporarily break config - verify ERROR findings
3. Remove optional path - verify WARN findings

---

## Review Checklist

Before implementing, confirm:

- [ ] All finding IDs are unique and stable
- [ ] Severity assignments match spec (ERROR vs WARN)
- [ ] No writes/mutations in any function
- [ ] No capability matrix consultation
- [ ] All path checks use existing constants (no re-derivation)
- [ ] Resolution checks delegate to WorldAdapter.resolve()
- [ ] CLI exit code reflects report.ok

---

## Estimated Effort

| Task | Est. Time |
|------|-----------|
| Task 1: Data structures | 10 min |
| Task 2: Root validation | 30 min |
| Task 3: Data structure checks | 15 min |
| Task 4: Local mods check | 10 min |
| Task 5: Config health | 15 min |
| Task 6: Resolution cross-checks | 20 min |
| Task 7: Main entry point | 10 min |
| Task 8: CLI | 10 min |
| **Total** | ~2 hours |

---

## Questions for Review

1. **Should OK findings be included by default?** (Or only on verbose flag?)
2. **Should the CLI have JSON output option?** (Spec says "optional")
3. **Should we add an MCP tool `ck3_paths_doctor`?** (Spec allows it)
