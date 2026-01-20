"""
arch_lint v2.35 â€” Main runner and CLI.

Orchestrates all lint checks and handles CLI arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import LintConfig
from .scanner import load_sources, SourceFile
from .analysis import build_index, collect_repo_refs
from .reporting import Reporter, Finding
from .rules import (
    check_direct_terms,
    check_composites,
    check_comments,
    check_forbidden_filenames,
    check_path_apis,
    check_enforcement_sites,
    check_io_and_mutators,
    check_oracle_patterns,
    check_fallback_patterns,
    check_concept_explosion,
    check_unused_symbols,
    check_deprecated_symbols,
    check_doc_terms,
)


def run(root: Path, cfg: LintConfig | None = None) -> Reporter:
    """Run all lint checks and return a Reporter with findings."""
    cfg = cfg or LintConfig(root=root)
    reporter = Reporter()
    
    # Load sources
    sources = load_sources(cfg)
    python_sources = [s for s in sources if s.is_python]
    doc_sources = [s for s in sources if s.is_doc]
    
    # Collect repo-wide references for unused detection
    all_refs: set[str] = set()
    if cfg.warn_unused:
        for src in python_sources:
            all_refs |= collect_repo_refs(src)
    
    # Check forbidden filenames (doesn't need source content)
    for finding in check_forbidden_filenames(cfg, [s.path for s in python_sources]):
        reporter.add(finding)
    
    # Run checks on each Python file
    for src in python_sources:
        idx = build_index(src)
        
        # Direct term checks (tokenizer-based)
        for finding in check_direct_terms(cfg, src):
            reporter.add(finding)
        
        # Composite/near-window checks
        for finding in check_composites(cfg, src):
            reporter.add(finding)
        
        # Comment intelligence
        for finding in check_comments(cfg, src):
            reporter.add(finding)
        
        # Path API checks
        for finding in check_path_apis(cfg, src):
            reporter.add(finding)
        
        # Enforcement site checks
        for finding in check_enforcement_sites(cfg, src):
            reporter.add(finding)
        
        # I/O and mutator checks
        for finding in check_io_and_mutators(cfg, src, idx):
            reporter.add(finding)
        
        # Oracle pattern checks
        for finding in check_oracle_patterns(cfg, src, idx):
            reporter.add(finding)
        
        # Fallback pattern checks
        for finding in check_fallback_patterns(cfg, src):
            reporter.add(finding)
        
        # Concept explosion checks
        for finding in check_concept_explosion(cfg, src, idx):
            reporter.add(finding)
        
        # Deprecated symbol checks
        for finding in check_deprecated_symbols(cfg, src, idx):
            reporter.add(finding)
    
    # Unused symbol checks (needs all refs)
    for finding in check_unused_symbols(cfg, python_sources, all_refs):
        reporter.add(finding)
    
    # Doc checks
    for src in doc_sources:
        for finding in check_doc_terms(cfg, src):
            reporter.add(finding)
    
    return reporter


def main() -> int:
    """CLI entry point."""
    # Fix unicode output on Windows console
    if sys.platform == "win32":
        try:
            # sys.stdout/stderr may be TextIOWrapper which has reconfigure
            if hasattr(sys.stdout, 'reconfigure'):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
            if hasattr(sys.stderr, 'reconfigure'):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    
    parser = argparse.ArgumentParser(
        description=f"arch_lint v{__version__} â€” CK3Raven canonical architecture linter"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    parser.add_argument(
        "--errors-only",
        action="store_true",
        help="Only show ERROR severity",
    )
    parser.add_argument(
        "--no-unused",
        action="store_true",
        help="Skip unused symbol detection",
    )
    parser.add_argument(
        "--no-deprecated",
        action="store_true",
        help="Skip deprecated symbol detection",
    )
    parser.add_argument(
        "--no-comments",
        action="store_true",
        help="Skip comment keyword detection",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run in daemon mode (continuous watch)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.75,
        help="Daemon poll interval in seconds (default: 0.75)",
    )
    parser.add_argument(
        "--files",
        nargs="*",
        metavar="FILE",
        help="Lint only these specific files (disables directory scan)",
    )
    parser.add_argument(
        "--files-from",
        metavar="MANIFEST",
        help="Read file list from JSON manifest (array of paths)",
    )
    parser.add_argument(
        "--full-scan-mins",
        type=int,
        default=45,
        help="Daemon full scan interval in minutes (default: 45, 0 disables)",
    )
    
    args = parser.parse_args()
    
    root = Path(args.root).resolve()
    
    # Daemon mode
    if args.daemon:
        try:
            from .daemon import run_daemon
            return run_daemon(
                root=root,
                interval=max(0.1, args.interval),
                debounce_seconds=2.0,
                full_scan_mins=max(0, args.full_scan_mins),
            )
        except ImportError as e:
            print(f"Daemon mode requires watchdog: pip install watchdog")
            print(f"Error: {e}")
            return 1
    
    # Resolve explicit files if provided
    explicit_files = None
    if args.files:
        explicit_files = tuple(Path(f).resolve() for f in args.files)
    elif args.files_from:
        import json
        manifest_path = Path(args.files_from)
        if manifest_path.exists():
            manifest_data = json.loads(manifest_path.read_text())
            if isinstance(manifest_data, list):
                explicit_files = tuple(Path(f).resolve() for f in manifest_data)
            elif isinstance(manifest_data, dict) and "files" in manifest_data:
                explicit_files = tuple(Path(f).resolve() for f in manifest_data["files"])
    
    # Normal mode
    cfg = LintConfig(
        root=root,
        warn_unused=not args.no_unused,
        warn_deprecated_symbols=not args.no_deprecated,
        check_comments=not args.no_comments,
        json_output=args.json,
        errors_only=args.errors_only,
        explicit_files=explicit_files,
    )
    
    reporter = run(root, cfg)
    
    # Filter if needed
    if args.errors_only:
        reporter.findings = [f for f in reporter.findings if f.severity == "ERROR"]
    
    # Output
    if args.json:
        print(reporter.render_json())
    else:
        print(f"Scanned: {len(list(load_sources(cfg)))} files under {root}")
        print(reporter.render_human())
    
    # Return non-zero if any errors
    return 1 if reporter.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
