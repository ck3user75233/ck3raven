from __future__ import annotations
import argparse
import sys
from pathlib import Path
from .config import LintConfig
from .reporting import Reporter
from .scanner import load_sources, is_doc_file
from .analysis import build_index, collect_repo_refs
from .rules import run_python_rules, run_doc_rules

def run(root: Path, cfg: LintConfig | None = None, reporter: Reporter | None = None) -> Reporter:
    cfg = cfg or LintConfig(root=root)
    reporter = reporter or Reporter()

    sources = load_sources(root)
    # Collect repo-wide refs for unused detection
    repo_refs: set[str] = set()
    if cfg.warn_unused:
        for src in sources:
            if not is_doc_file(src.path):
                repo_refs |= collect_repo_refs(src)

    for src in sources:
        if is_doc_file(src.path):
            run_doc_rules(cfg, src, reporter)
        else:
            idx = build_index(src)
            run_python_rules(cfg, src, idx, reporter, repo_refs)

    return reporter

def main() -> int:
    # Fix unicode output on Windows console
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    
    parser = argparse.ArgumentParser(description="arch_lint v2.2 - CK3Raven canonical architecture linter")
    parser.add_argument("root", nargs="?", default=".", help="Root directory to scan (default: .)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--no-unused", action="store_true", help="Skip unused symbol detection")
    parser.add_argument("--no-deprecated", action="store_true", help="Skip deprecated symbol detection")
    parser.add_argument("--errors-only", action="store_true", help="Only show ERROR severity")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    cfg = LintConfig(
        root=root,
        warn_unused=not args.no_unused,
        warn_deprecated_symbols=not args.no_deprecated,
    )
    reporter = run(root, cfg)

    if args.errors_only:
        reporter.findings = [f for f in reporter.findings if f.severity == "ERROR"]

    if args.json:
        import json
        print(json.dumps([f.__dict__ for f in reporter.findings], indent=2, default=str))
    else:
        print(reporter.render_human())

    # Return non-zero if any errors
    return 1 if any(f.severity == "ERROR" for f in reporter.findings) else 0

if __name__ == "__main__":
    raise SystemExit(main())
