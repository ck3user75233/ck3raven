"""
Paths Doctor - Read-only diagnostic utility for path configuration.

Purpose: Validate configured and derived paths, detect misconfiguration early,
and provide actionable remediation guidance.

CONSTRAINTS (Non-Negotiable):
- Read-only: MUST NOT create directories, write files, modify config
- No enforcement: MUST NOT consult capability matrix for authorization
- Canonical sources only: paths.py constants, loaded config, WorldAdapter resolution
- No re-implementation: Classification checks delegate to WorldAdapter.resolve()
- Deterministic output: Same config + filesystem state → same report
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Literal
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass(frozen=True)
class DoctorFinding:
    """Single diagnostic finding."""
    id: str                 # stable identifier, e.g. PD-ROOT-GAME-MISSING
    severity: Literal["OK", "WARN", "ERROR"]
    subject: str            # e.g. ROOT_GAME, WIP_DIR, config
    message: str            # human-readable description
    remediation: str | None # concrete next step for the user


@dataclass(frozen=True)
class PathsDoctorReport:
    """Complete diagnostic report."""
    ok: bool                      # true iff no ERROR findings
    findings: tuple[DoctorFinding, ...]
    summary: dict[str, int]       # counts by severity
    config_path: str | None       # path to loaded config, if known


# =============================================================================
# CHECK FUNCTIONS
# =============================================================================

def _check_required_roots() -> list[DoctorFinding]:
    """Check ROOT_GAME and ROOT_STEAM are configured and exist."""
    from .paths import ROOT_GAME, ROOT_STEAM
    
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
    
    # ROOT_STEAM
    if ROOT_STEAM is None:
        findings.append(DoctorFinding(
            id="PD-ROOT-STEAM-MISSING",
            severity="ERROR",
            subject="ROOT_STEAM",
            message="ROOT_STEAM is not configured",
            remediation="Set workshop_path in ~/.ck3raven/config/workspace.toml"
        ))
    elif not ROOT_STEAM.exists():
        findings.append(DoctorFinding(
            id="PD-ROOT-STEAM-NOTFOUND",
            severity="ERROR",
            subject="ROOT_STEAM",
            message=f"ROOT_STEAM path does not exist: {ROOT_STEAM}",
            remediation="Verify workshop_path points to Steam Workshop mods folder"
        ))
    elif not ROOT_STEAM.is_dir():
        findings.append(DoctorFinding(
            id="PD-ROOT-STEAM-NOTDIR",
            severity="ERROR",
            subject="ROOT_STEAM",
            message=f"ROOT_STEAM is not a directory: {ROOT_STEAM}",
            remediation="workshop_path must be a directory, not a file"
        ))
    else:
        findings.append(DoctorFinding(
            id="PD-ROOT-STEAM-OK",
            severity="OK",
            subject="ROOT_STEAM",
            message=f"ROOT_STEAM: {ROOT_STEAM}",
            remediation=None
        ))
    
    return findings


def _check_optional_roots() -> list[DoctorFinding]:
    """Check optional roots (ROOT_USER_DOCS, ROOT_UTILITIES, etc.)."""
    from .paths import ROOT_USER_DOCS, ROOT_UTILITIES, ROOT_LAUNCHER, ROOT_VSCODE
    
    findings = []
    
    optional_roots = [
        ("ROOT_USER_DOCS", ROOT_USER_DOCS, "user_docs_path"),
        ("ROOT_UTILITIES", ROOT_UTILITIES, "utilities_path"),
        ("ROOT_LAUNCHER", ROOT_LAUNCHER, "launcher_path"),
        ("ROOT_VSCODE", ROOT_VSCODE, "vscode_path"),
    ]
    
    for name, path, config_key in optional_roots:
        if path is None:
            findings.append(DoctorFinding(
                id=f"PD-{name.replace('ROOT_', '')}-NOTCONFIGURED",
                severity="WARN",
                subject=name,
                message=f"{name} is not configured",
                remediation=f"Configure {config_key} in workspace.toml for full functionality"
            ))
        elif not path.exists():
            findings.append(DoctorFinding(
                id=f"PD-{name.replace('ROOT_', '')}-NOTFOUND",
                severity="WARN",
                subject=name,
                message=f"{name} path does not exist: {path}",
                remediation=f"Create directory or fix {config_key} in workspace.toml"
            ))
        elif not path.is_dir():
            findings.append(DoctorFinding(
                id=f"PD-{name.replace('ROOT_', '')}-NOTDIR",
                severity="ERROR",
                subject=name,
                message=f"{name} is not a directory: {path}",
                remediation=f"{config_key} must be a directory, not a file"
            ))
        else:
            findings.append(DoctorFinding(
                id=f"PD-{name.replace('ROOT_', '')}-OK",
                severity="OK",
                subject=name,
                message=f"{name}: {path}",
                remediation=None
            ))
    
    return findings


def _check_computed_roots() -> list[DoctorFinding]:
    """Check ROOT_REPO and ROOT_CK3RAVEN_DATA."""
    from .paths import ROOT_REPO, ROOT_CK3RAVEN_DATA
    
    findings = []
    
    # ROOT_REPO (from config - NOT computed from __file__)
    # For ck3lens mode: WARN if not configured
    # For ck3raven-dev mode: ERROR if not configured
    if ROOT_REPO is None:
        findings.append(DoctorFinding(
            id="PD-REPO-NOTCONFIGURED",
            severity="WARN",  # WARN for ck3lens (optional), ERROR would be for ck3raven-dev
            subject="ROOT_REPO",
            message="ROOT_REPO is not configured in workspace.toml",
            remediation="Set repo_path in ~/.ck3raven/config/workspace.toml to the ck3raven source directory"
        ))
    elif not ROOT_REPO.exists():
        findings.append(DoctorFinding(
            id="PD-REPO-NOTFOUND",
            severity="ERROR",
            subject="ROOT_REPO",
            message=f"ROOT_REPO does not exist: {ROOT_REPO}",
            remediation="Verify repo_path in workspace.toml points to ck3raven source directory"
        ))
    elif not ROOT_REPO.is_dir():
        findings.append(DoctorFinding(
            id="PD-REPO-NOTDIR",
            severity="ERROR",
            subject="ROOT_REPO",
            message=f"ROOT_REPO is not a directory: {ROOT_REPO}",
            remediation="repo_path must be a directory, not a file"
        ))
    else:
        # Verify it looks like a repo (has pyproject.toml)
        if (ROOT_REPO / "pyproject.toml").exists():
            findings.append(DoctorFinding(
                id="PD-REPO-OK",
                severity="OK",
                subject="ROOT_REPO",
                message=f"ROOT_REPO: {ROOT_REPO}",
                remediation=None
            ))
        else:
            findings.append(DoctorFinding(
                id="PD-REPO-NOPYPROJECT",
                severity="WARN",
                subject="ROOT_REPO",
                message=f"ROOT_REPO exists but has no pyproject.toml: {ROOT_REPO}",
                remediation="repo_path may be pointing to wrong directory"
            ))
    
    # ROOT_CK3RAVEN_DATA (always ~/.ck3raven)
    if not ROOT_CK3RAVEN_DATA.exists():
        findings.append(DoctorFinding(
            id="PD-DATA-ROOT-NOTFOUND",
            severity="WARN",
            subject="ROOT_CK3RAVEN_DATA",
            message=f"ROOT_CK3RAVEN_DATA does not exist: {ROOT_CK3RAVEN_DATA}",
            remediation="Run MCP server or daemon to create ~/.ck3raven structure"
        ))
    elif not ROOT_CK3RAVEN_DATA.is_dir():
        findings.append(DoctorFinding(
            id="PD-DATA-ROOT-NOTDIR",
            severity="ERROR",
            subject="ROOT_CK3RAVEN_DATA",
            message=f"ROOT_CK3RAVEN_DATA is not a directory: {ROOT_CK3RAVEN_DATA}",
            remediation="Remove the file at ~/.ck3raven - it should be a directory"
        ))
    else:
        findings.append(DoctorFinding(
            id="PD-DATA-ROOT-OK",
            severity="OK",
            subject="ROOT_CK3RAVEN_DATA",
            message=f"ROOT_CK3RAVEN_DATA: {ROOT_CK3RAVEN_DATA}",
            remediation=None
        ))
    
    return findings


def _check_data_structure() -> list[DoctorFinding]:
    """Check expected subdirectories under ROOT_CK3RAVEN_DATA."""
    from .paths import WIP_DIR, PLAYSET_DIR, LOGS_DIR, CONFIG_DIR, DB_PATH
    
    findings = []
    
    # Check expected directories
    expected_dirs = [
        (WIP_DIR, "WIP_DIR", "wip"),
        (PLAYSET_DIR, "PLAYSET_DIR", "playsets"),
        (LOGS_DIR, "LOGS_DIR", "logs"),
        (CONFIG_DIR, "CONFIG_DIR", "config"),
    ]
    
    for path, name, dirname in expected_dirs:
        if not path.exists():
            findings.append(DoctorFinding(
                id=f"PD-DATA-{dirname.upper()}-MISSING",
                severity="WARN",
                subject=name,
                message=f"{dirname}/ directory does not exist: {path}",
                remediation=f"Run MCP server or daemon to initialize, or create manually"
            ))
        elif not path.is_dir():
            findings.append(DoctorFinding(
                id=f"PD-DATA-{dirname.upper()}-NOTDIR",
                severity="ERROR",
                subject=name,
                message=f"{dirname} is a file, should be a directory: {path}",
                remediation=f"Remove the file and create a directory"
            ))
        else:
            findings.append(DoctorFinding(
                id=f"PD-DATA-{dirname.upper()}-OK",
                severity="OK",
                subject=name,
                message=f"{name}: {path}",
                remediation=None
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
                id="PD-DATA-DB-OK",
                severity="OK",
                subject="DB_PATH",
                message=f"DB_PATH: {DB_PATH}",
                remediation=None
            ))
    else:
        findings.append(DoctorFinding(
            id="PD-DATA-DB-MISSING",
            severity="WARN",
            subject="DB_PATH",
            message=f"Database file does not exist: {DB_PATH}",
            remediation="Run 'python -m qbuilder.cli daemon' to create database"
        ))
    
    return findings


def _check_local_mods() -> list[DoctorFinding]:
    """Check LOCAL_MODS_FOLDER validity."""
    from .paths import LOCAL_MODS_FOLDER
    
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


def _check_config_health() -> list[DoctorFinding]:
    """Report config source and any errors."""
    from .paths import CONFIG_DIR, _config
    
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
            remediation="Run MCP server to auto-create default config, or create manually"
        ))
    
    # Report any config errors from _config.errors
    if hasattr(_config, 'errors') and _config.errors:
        for error in _config.errors:
            findings.append(DoctorFinding(
                id="PD-CONFIG-ERROR",
                severity="ERROR",
                subject="config",
                message=f"Config error: {error}",
                remediation="Fix the error in workspace.toml"
            ))
    
    # Report defaults in use
    if hasattr(_config, 'paths') and hasattr(_config.paths, 'using_defaults'):
        for path_name in _config.paths.using_defaults:
            findings.append(DoctorFinding(
                id=f"PD-CONFIG-DEFAULT-{path_name.upper().replace('_PATH', '')}",
                severity="WARN",
                subject="config",
                message=f"Using OS-default for {path_name}",
                remediation=f"Configure {path_name} in workspace.toml"
            ))
    
    return findings


def _check_resolution() -> list[DoctorFinding]:
    """Cross-check resolution against expected classifications."""
    from .paths import RootCategory, WIP_DIR, ROOT_REPO, LOCAL_MODS_FOLDER
    
    findings = []
    
    try:
        from .world_adapter import WorldAdapter
        world = WorldAdapter.create()
    except Exception as e:
        return [DoctorFinding(
            id="PD-RESOLUTION-INIT-ERROR",
            severity="WARN",
            subject="resolution",
            message=f"Could not initialize WorldAdapter: {e}",
            remediation="Resolution checks skipped - fix WorldAdapter first"
        )]
    
    test_cases: list[tuple[str, RootCategory, str]] = [
        # (path, expected_root_category, description)
        (str(WIP_DIR / "doctor_probe.txt"), RootCategory.ROOT_CK3RAVEN_DATA, "WIP path"),
    ]
    
    # Only test repo if it's configured and exists
    if ROOT_REPO is not None:
        repo_test_file = ROOT_REPO / "pyproject.toml"
        if repo_test_file.exists():
            test_cases.append(
                (str(repo_test_file), RootCategory.ROOT_REPO, "Repo path")
            )
    
    # Only test local mods if configured and exists
    if LOCAL_MODS_FOLDER and LOCAL_MODS_FOLDER.exists():
        test_cases.append(
            (str(LOCAL_MODS_FOLDER / "TestMod" / "descriptor.mod"), RootCategory.ROOT_USER_DOCS, "Local mod path")
        )
    
    errors_found = False
    for path, expected_root, desc in test_cases:
        try:
            result = world.resolve(path)
            if result.root_category != expected_root:
                findings.append(DoctorFinding(
                    id="PD-RESOLUTION-MISMATCH",
                    severity="WARN",  # WARN by default per spec
                    subject="resolution",
                    message=f"{desc} resolved to {result.root_category.name}, expected {expected_root.name}",
                    remediation="Check resolution order in WorldAdapter - possible root overlap"
                ))
                errors_found = True
        except Exception as e:
            findings.append(DoctorFinding(
                id="PD-RESOLUTION-ERROR",
                severity="WARN",
                subject="resolution",
                message=f"Resolution failed for {desc}: {e}",
                remediation="Check WorldAdapter.resolve() implementation"
            ))
            errors_found = True
    
    if not errors_found and test_cases:
        findings.append(DoctorFinding(
            id="PD-RESOLUTION-OK",
            severity="OK",
            subject="resolution",
            message=f"All {len(test_cases)} resolution cross-checks passed",
            remediation=None
        ))
    
    return findings


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def run_paths_doctor(*, include_resolution_checks: bool = True) -> PathsDoctorReport:
    """
    Run all diagnostic checks and return report.
    
    Args:
        include_resolution_checks: If True, run WorldAdapter resolution cross-checks
        
    Returns:
        PathsDoctorReport with all findings
    """
    from .paths import CONFIG_DIR
    
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
        all_findings.extend(_check_resolution())
    
    # Build summary
    summary = {"OK": 0, "WARN": 0, "ERROR": 0}
    for f in all_findings:
        summary[f.severity] += 1
    
    # Sort findings: ERROR first, then WARN, then OK
    severity_order = {"ERROR": 0, "WARN": 1, "OK": 2}
    sorted_findings = sorted(all_findings, key=lambda f: (severity_order[f.severity], f.id))
    
    # Determine config path
    config_path = CONFIG_DIR / "workspace.toml"
    config_path_str = str(config_path) if config_path.exists() else None
    
    return PathsDoctorReport(
        ok=(summary["ERROR"] == 0),
        findings=tuple(sorted_findings),
        summary=summary,
        config_path=config_path_str
    )


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def _print_report(report: PathsDoctorReport, verbose: bool = False) -> None:
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
        # Skip OK findings unless verbose
        if f.severity == "OK" and not verbose:
            continue
            
        icon = {"ERROR": "❌", "WARN": "⚠️", "OK": "✅"}[f.severity]
        print(f"\n{icon} [{f.id}] {f.subject}")
        print(f"   {f.message}")
        if f.remediation:
            print(f"   → {f.remediation}")
    
    if not verbose and report.summary["OK"] > 0:
        print(f"\n({report.summary['OK']} OK findings hidden - use --verbose to show)")
    
    print("\n" + "=" * 60)


def main() -> int:
    """CLI entry point."""
    import sys
    import json
    
    # Parse args
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    json_output = "--json" in sys.argv
    no_resolution = "--no-resolution" in sys.argv
    
    report = run_paths_doctor(include_resolution_checks=not no_resolution)
    
    if json_output:
        # Convert to dict for JSON
        report_dict = {
            "ok": report.ok,
            "findings": [asdict(f) for f in report.findings],
            "summary": report.summary,
            "config_path": report.config_path,
        }
        print(json.dumps(report_dict, indent=2))
    else:
        _print_report(report, verbose=verbose)
    
    return 0 if report.ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
