from __future__ import annotations
import re
from .config import LintConfig, in_allowlist
from .reporting import Reporter, Finding
from .scanner import SourceFile, get_line, in_banned_context
from .analysis import ModuleIndex

# === 2.2 Fixes ===
# - Stop treating attribute method names as raw IO (prevents false positives on WorldAdapter.resolve())
# - Treat Path.resolve / relative_to as PATH-ARITH (not IO), and ban outside WorldAdapter/handles.
# - Add explicit MUTATOR detection for SQL write keywords + file write APIs + subprocess.

# === 2.3 Updates (January 2026) ===
# - Added "legacy" and "fallback" concepts to banned terms
# - Fallbacks are often used to retain BANNED IDEAS during refactor - warn on else-fallback patterns

_RX_ORACLE_NAME = [
    re.compile(r"^can_", re.IGNORECASE),
    re.compile(r"^may_", re.IGNORECASE),
    re.compile(r"^allowed_", re.IGNORECASE),
    re.compile(r"is_.*(writable|editable|allowed|permitted|authorized|mutable|write_ok|writeable)", re.IGNORECASE),
]
_RX_PARALLEL_TRUTH = re.compile(r"(editable_mods_list|active_mods|enabled_mods|local_mods|live_mods|write_mods|allowed_mods|mutable_mods|visible_cvids|db_visibility)", re.IGNORECASE)

CONCEPT_TOKENS = (
    "playsetlens","lensworld","lensscope","lenssession","getlens","get_lens",
    "lensprovider","lensfactory","lensservice","lensadapter","lensresolver",
    "lenscontext","lensmanager","playsetworld","playscope","scopeworld","worldscope",
    # December 2025 additions - banned concepts
    "legacyvisibility", "legacy_visibility", "lens_enforcement", "legacy_enforcement",
    # January 2026 additions - "legacy" is context-dependent, these are specifically banned
    "invalidate_lens_cache",
)

# Banned phrases that indicate retention of deprecated concepts
BANNED_PHRASES = (
    "backward compat", "backwards compat", "legacy playset", "legacy format",
    "active_mod_paths", "legacy_file", "legacy visibility", "lens enforcement",
)

# Patterns that suggest fallback-to-banned-concept (ADVISORY)
# "Fallbacks are often used to retain BANNED IDEAS during refactor"
_FALLBACK_PATTERNS = [
    # else branch with visibility/scope/lens/legacy
    re.compile(r"else\s*:\s*.*(?:visibility|visible_cvids|lens|legacy|scope)", re.IGNORECASE),
    # or-fallback with banned concepts
    re.compile(r"\s+or\s+.*(?:visibility|visible_cvids|legacy)", re.IGNORECASE),
    # getattr fallback with banned concepts  
    re.compile(r"getattr\s*\(.*(?:visibility|visible_cvids|legacy)", re.IGNORECASE),
]

_RX_LENS_CTOR = re.compile(r"\b([A-Za-z_]*Lens[A-Za-z_]*|PlaysetLens|Lens)\s*\(", re.IGNORECASE)

# Name() calls we consider raw IO
RAW_IO_NAME_CALLS = {"open"}

# Dotted calls that are raw IO (explicit, prevents resolve()/relative_to() false positives)
RAW_IO_DOTTED_CALLS = {
    # pathlib reads/writes are IO
    "Path.read_text","Path.read_bytes","Path.write_text","Path.write_bytes","Path.open",
    # os
    "os.listdir","os.walk","os.remove","os.unlink","os.rmdir","os.mkdir","os.makedirs","os.rename","os.replace",
    # shutil
    "shutil.copy","shutil.copy2","shutil.copytree","shutil.move","shutil.rmtree",
    # glob
    "glob.glob","Path.rglob","Path.glob",
    # subprocess
    "subprocess.run","subprocess.Popen",
}

# Path arithmetic (not IO) that you want canonicalized through WorldAdapter
PATH_ARITH_DOTTED = {"Path.resolve","Path.relative_to"}

# Mutator signal patterns
_SQL_MUTATOR_RX = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|VACUUM|REINDEX)\b", re.IGNORECASE)
_SUBPROCESS_RX = re.compile(r"\b(subprocess\.run|subprocess\.Popen|os\.system)\b")
_FS_WRITE_RX = re.compile(r"\b(Path\.write_text|Path\.write_bytes|Path\.open|open\()\b")

INLINE_PATH_PATTERNS = [
    re.compile(r"os\.path\.(normpath|abspath|realpath)\(", re.IGNORECASE),
    re.compile(r"\.replace\(\s*[\'\"]\\\\\[\'\"]\\s*,\s*[\'\"]//+[\'\"]\s*\)"),
]

def _sev(cfg: LintConfig, suppressed: bool, default: str) -> str:
    if suppressed:
        return "INFO" if default == "ERROR" else default
    return default

def run_python_rules(cfg: LintConfig, src: SourceFile, idx: ModuleIndex, reporter: Reporter, repo_refs: set[str]) -> None:
    p = str(src.path)
    allow_raw_io = in_allowlist(p, cfg.allow_raw_io_in)
    allow_path_arith = in_allowlist(p, cfg.allow_path_arithmetic_in)
    allow_mutators = in_allowlist(p, cfg.allow_mutators_in)

    # Deprecated hits
    if cfg.warn_deprecated_symbols:
        for d in idx.defs:
            if d.deprecated:
                reporter.add(Finding(
                    rule_id="DEPRECATED-01",
                    severity="WARN",
                    path=p,
                    line=d.line,
                    col=d.col,
                    symbol=d.name,
                    deprecated=True,
                    message=f"Symbol '{d.name}' is marked #deprecated but still resident.",
                    evidence=get_line(src.lines, d.line).strip(),
                ))

    # Unused symbols (best effort)
    if cfg.warn_unused:
        for d in idx.defs:
            if any(d.name.startswith(pref) for pref in cfg.unused_name_allowlist_prefixes):
                continue
            if d.name in cfg.unused_name_allowlist_exact:
                continue
            if d.name not in repo_refs:
                reporter.add(Finding(
                    rule_id="UNUSED-01",
                    severity=cfg.unused_severity,
                    path=p,
                    line=d.line,
                    col=d.col,
                    symbol=d.name,
                    message=f"Symbol '{d.name}' appears unused (no repo references found).",
                ))

    # Oracle / parallel truth
    for d in idx.defs:
        if any(rx.search(d.name) for rx in _RX_ORACLE_NAME):
            line = get_line(src.lines, d.line)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
            reporter.add(Finding(
                rule_id="ORACLE-01",
                severity=_sev(cfg, suppressed, "ERROR"),
                path=p, line=d.line, col=d.col, symbol=d.name,
                message=f"Oracle-style symbol '{d.name}' is banned outside enforcement.",
                evidence=line.strip(),
                suggested_fix="Delete oracle helpers; gate mutations via canonical handles/policy at the boundary.",
            ))

        if _RX_PARALLEL_TRUTH.search(d.name):
            line = get_line(src.lines, d.line)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
            reporter.add(Finding(
                rule_id="TRUTH-01",
                severity=_sev(cfg, suppressed, "ERROR"),
                path=p, line=d.line, col=d.col, symbol=d.name,
                message=f"Parallel truth symbol '{d.name}' suggests recomputing scope/editability outside the canonical handles.",
                evidence=line.strip(),
                suggested_fix="Delete parallel lists; derive visibility and access only via WorldAdapter/Builder handles.",
            ))

    # If-conditions referencing oracle patterns
    for test_src, ln, col in idx.if_tests:
        if not test_src:
            continue
        if any(rx.search(test_src) for rx in _RX_ORACLE_NAME) or _RX_PARALLEL_TRUTH.search(test_src):
            line = get_line(src.lines, ln)
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
            reporter.add(Finding(
                rule_id="ORACLE-02",
                severity=_sev(cfg, suppressed, "ERROR"),
                path=p, line=ln, col=col,
                message="Permission branching / oracle-style gating detected in if-condition.",
                evidence=line.strip(),
                suggested_fix="Remove permission pre-checks; use canonical boundary gates (handles/policy) at mutation sites.",
            ))

    # === FALLBACK-01 (2.3): Fallbacks often retain banned ideas ===
    for i, line in enumerate(src.lines, start=1):
        for pattern in _FALLBACK_PATTERNS:
            if pattern.search(line):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="FALLBACK-01",
                    severity=_sev(cfg, suppressed, "WARN"),
                    path=p, line=i, col=0,
                    message="Fallback pattern detected - fallbacks often retain BANNED IDEAS during refactor.",
                    evidence=line.strip(),
                    suggested_fix="Review: if this is a fallback to deprecated visibility/scope patterns, delete it.",
                ))
                break  # Only one per line

    # === IO-01 (2.2): explicit only, avoids false positives on resolve()/WorldAdapter.resolve() ===
    if not allow_raw_io:
        for callee, ln, col in idx.calls:
            if callee in RAW_IO_NAME_CALLS:
                line = get_line(src.lines, ln)
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="IO-01",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=ln, col=col, symbol=callee,
                    message=f"Raw IO call '{callee}(...)' outside allowlisted handle/WorldAdapter modules.",
                    evidence=line.strip(),
                    suggested_fix="Route IO through FS/DB handles minted by WorldAdapter/Builder.",
                ))

        for dotted, ln, col in idx.dotted_calls:
            if dotted in RAW_IO_DOTTED_CALLS:
                line = get_line(src.lines, ln)
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="IO-01",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=ln, col=col, symbol=dotted,
                    message=f"Raw IO call '{dotted}(...)' outside allowlisted handle/WorldAdapter modules.",
                    evidence=line.strip(),
                    suggested_fix="Route IO through FS/DB handles minted by WorldAdapter/Builder.",
                ))

    # === PATH-ARITH-01 (2.2): Path.resolve / relative_to banned outside WorldAdapter/handles ===
    if not allow_path_arith:
        for dotted, ln, col in idx.dotted_calls:
            if dotted in PATH_ARITH_DOTTED:
                line = get_line(src.lines, ln)
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="PATH-ARITH-01",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=ln, col=col, symbol=dotted,
                    message=f"Path arithmetic '{dotted}(...)' must be centralized in WorldAdapter/handles.",
                    evidence=line.strip(),
                    suggested_fix="Call WorldAdapter for canonical absolute/relative path operations.",
                ))

    # Inline path normalization drift
    for i, line in enumerate(src.lines, start=1):
        if any(rx.search(line) for rx in INLINE_PATH_PATTERNS):
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
            reporter.add(Finding(
                rule_id="PATH-01",
                severity=_sev(cfg, suppressed, "WARN"),
                path=p, line=i, col=0,
                message="Inline path normalization detected.",
                evidence=line.strip(),
                suggested_fix="Use WorldAdapter for canonical path normalization.",
            ))

    # Concept explosion: Lens/PlaysetLens/etc
    sev = "ERROR" if cfg.concept_explosion_is_error else "WARN"
    if not in_allowlist(p, cfg.worldadapter_paths):
        for d in idx.defs:
            n = d.name.lower()
            if n == "lens" or n == "playsetlens" or any(tok in n for tok in CONCEPT_TOKENS):
                line = get_line(src.lines, d.line)
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="CONCEPT-01",
                    severity=_sev(cfg, suppressed, sev),
                    path=p, line=d.line, col=d.col, symbol=d.name,
                    message=f"Concept explosion: Lens-like noun '{d.name}' overlaps canonical Session/WorldAdapter/handles.",
                    evidence=line.strip(),
                    suggested_fix="Do not introduce Lens wrappers. Use Session + WorldAdapter + canonical handles.",
                ))
        for i, line in enumerate(src.lines, start=1):
            m = _RX_LENS_CTOR.search(line)
            if m:
                token = m.group(1)
                suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="CONCEPT-03",
                    severity=_sev(cfg, suppressed, sev),
                    path=p, line=i, col=m.start(1), symbol=token,
                    message=f"Concept explosion: constructor '{token}(...)' suggests creating overlapping Lens objects.",
                    evidence=line.strip(),
                    suggested_fix="Do not create Lens objects. Use WorldAdapter + canonical handles.",
                ))

    # === MUTATOR-01 (2.2): SQL/file/subprocess mutator signals outside builder/write-handle ===
    if not allow_mutators:
        for i, line in enumerate(src.lines, start=1):
            l = line.strip()
            if not l:
                continue
            # SQL mutators
            if _SQL_MUTATOR_RX.search(l) and ("execute" in l or "executescript" in l or "executemany" in l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="MUTATOR-01",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=i, col=0,
                    message="SQL mutator detected outside builder/write-handle modules.",
                    evidence=l,
                    suggested_fix="Route DB writes through builder.db_write_handle only.",
                ))
            # File write mutators
            if _FS_WRITE_RX.search(l) and ("write_" in l or "open(" in l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="MUTATOR-02",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=i, col=0,
                    message="Filesystem write mutator detected outside builder/write-handle modules.",
                    evidence=l,
                    suggested_fix="Route file writes through builder.fs_write_handle only.",
                ))
            # Subprocess mutators
            if _SUBPROCESS_RX.search(l):
                suppressed = cfg.suppress_in_banned_context and in_banned_context(l, cfg.banned_context_keywords)
                reporter.add(Finding(
                    rule_id="MUTATOR-03",
                    severity=_sev(cfg, suppressed, "ERROR"),
                    path=p, line=i, col=0,
                    message="Subprocess/system call detected outside builder/write-handle modules.",
                    evidence=l,
                    suggested_fix="Route side-effecting exec through builder.exec_write_handle only.",
                ))

def run_doc_rules(cfg: LintConfig, src: SourceFile, reporter: Reporter) -> None:
    if not cfg.report_doc_banned_term_mentions:
        return
    p = str(src.path)
    # Banned terms - both underscore and space-separated versions
    tokens = (
        "playsetlens", "getlens", "get.lens", "lensworld",
        "editable_mods", "live_mods", "local_mods",  # underscore versions
        "live mod", "local mod",  # space versions (catch docstrings)
        "is_writable", "can_write",
        # December 2025 additions
        "legacyvisibility", "legacy_visibility", "lens_enforcement", "legacy_enforcement",
        "visible_cvids", "db_visibility",
        "backward compat", "backwards compat", "legacy playset",
        "active_mod_paths", "legacy_file",
        # January 2026 additions
        "invalidate_lens_cache",
    )
    for i, line in enumerate(src.lines, start=1):
        lc = line.lower()
        if any(t in lc for t in tokens):
            suppressed = cfg.suppress_in_banned_context and in_banned_context(line, cfg.banned_context_keywords)
            reporter.add(Finding(
                rule_id="DOC-TERM",
                severity="DOC-WARN",
                path=p, line=i, col=0, is_doc=True,
                message="Banned/concept-expansion term mentioned in documentation (segregated).",
                evidence=line.strip() if suppressed else line.strip(),
            ))
