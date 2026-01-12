"""
QBuilder Routing - Deterministic file type detection and envelope assignment.

The routing table (routing_table.json) is the SOLE AUTHORITY for what work a file requires.
This module loads the JSON and provides matching logic.

Usage:
    from qbuilder.routing import get_router
    
    router = get_router()
    result = router.route("common/traits/00_traits.txt")
    print(result.file_type)   # "TRAITS"
    print(result.envelope)    # "LOOKUP_TRAITS"
    print(result.steps)       # ["INGEST", "PARSE", "SYMBOLS", "REFS", "LOOKUP_TRAITS"]
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional
import functools


@dataclass(frozen=True)
class RoutingResult:
    """Result of routing a file path."""
    file_type: str
    envelope: str
    steps: tuple[str, ...]
    notes: str
    
    @property
    def should_skip(self) -> bool:
        """True if this file should not be processed."""
        return self.envelope == "SKIP"
    
    @property
    def step_count(self) -> int:
        return len(self.steps)


@dataclass(frozen=True)
class MatchRule:
    """A single file type matching rule."""
    file_type: str
    envelope: str
    notes: str
    path_prefixes: tuple[str, ...]
    extensions: tuple[str, ...]
    
    def matches(self, relpath: str, ext: str) -> bool:
        """Check if this rule matches the given path."""
        path_lower = relpath.lower().replace("\\", "/")
        
        # If rule has path_prefixes, at least one must match
        if self.path_prefixes:
            prefix_match = any(path_lower.startswith(p) for p in self.path_prefixes)
            if not prefix_match:
                return False
            # If rule also has extensions, extension must also match
            if self.extensions:
                return ext.lower() in self.extensions
            return True
        
        # If rule only has extensions, check extension
        if self.extensions:
            return ext.lower() in self.extensions
        
        # Empty match = fallback rule (matches everything)
        return True


class Router:
    """File router that assigns envelopes based on routing_table.json."""
    
    def __init__(self, routing_table: dict):
        self._table = routing_table
        self._version = routing_table.get("version", 0)
        self._envelopes = routing_table["envelopes"]
        self._steps = routing_table["steps"]
        self._file_types = routing_table["file_types"]
        self._match_order = routing_table["match_order"]
        
        # Pre-compile match rules in order
        self._rules: list[MatchRule] = []
        for ft_name in self._match_order:
            ft = self._file_types[ft_name]
            match = ft.get("match", {})
            self._rules.append(MatchRule(
                file_type=ft_name,
                envelope=ft["envelope"],
                notes=ft.get("notes", ""),
                path_prefixes=tuple(match.get("path_prefixes", [])),
                extensions=tuple(match.get("extensions", [])),
            ))
    
    @property
    def version(self) -> int:
        return self._version
    
    @property
    def envelope_names(self) -> list[str]:
        return list(self._envelopes.keys())
    
    @property
    def file_type_names(self) -> list[str]:
        return list(self._file_types.keys())
    
    def route(self, relpath: str) -> RoutingResult:
        """
        Route a file path to its processing envelope.
        
        This is DETERMINISTIC: same input always produces same output.
        
        Args:
            relpath: Relative path within content root
            
        Returns:
            RoutingResult with file_type, envelope, and steps
        """
        # Normalize path
        path = PurePosixPath(relpath.replace("\\", "/"))
        ext = path.suffix.lower()
        
        # Find first matching rule
        for rule in self._rules:
            if rule.matches(relpath, ext):
                envelope_def = self._envelopes[rule.envelope]
                return RoutingResult(
                    file_type=rule.file_type,
                    envelope=rule.envelope,
                    steps=tuple(envelope_def["steps"]),
                    notes=rule.notes,
                )
        
        # Should never happen if UNKNOWN is last in match_order
        raise ValueError(f"No routing rule matched: {relpath}")
    
    def get_envelope_steps(self, envelope_name: str) -> list[str]:
        """Get the ordered steps for an envelope."""
        return list(self._envelopes[envelope_name]["steps"])
    
    def get_step_order(self, step_name: str) -> int:
        """Get the execution order for a step (lower = earlier)."""
        return self._steps[step_name]["order"]


# Module-level singleton
_router: Optional[Router] = None


def get_router() -> Router:
    """Get the global router instance (lazy-loaded)."""
    global _router
    if _router is None:
        _router = load_router()
    return _router


def load_router(json_path: Optional[Path] = None) -> Router:
    """Load router from JSON file."""
    if json_path is None:
        json_path = Path(__file__).parent / "routing_table.json"
    
    with open(json_path) as f:
        routing_table = json.load(f)
    
    return Router(routing_table)


def reload_router() -> Router:
    """Force reload of the routing table."""
    global _router
    _router = load_router()
    return _router


# =============================================================================
# Self-test
# =============================================================================

if __name__ == "__main__":
    router = get_router()
    
    test_cases = [
        "common/traits/00_traits.txt",
        "events/lifestyle_events.txt",
        "common/on_action/yearly.txt",
        "localization/english/traits_l_english.yml",
        "common/genes/01_gene_categories.txt",
        "common/landed_titles/00_landed_titles.txt",
        "gfx/interface/icons/traits.dds",
        "common/scripted_effects/00_effects.txt",
        "descriptor.mod",
        "gui/window_character.gui",
    ]
    
    print(f"Routing Table v{router.version}")
    print(f"Envelopes: {len(router.envelope_names)}")
    print(f"File Types: {len(router.file_type_names)}")
    print()
    print("=" * 80)
    
    for path in test_cases:
        result = router.route(path)
        print(f"Path: {path}")
        print(f"  Type: {result.file_type}")
        print(f"  Envelope: {result.envelope}")
        print(f"  Steps: {result.steps}")
        print()
