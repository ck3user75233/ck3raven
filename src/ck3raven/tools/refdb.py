# DEPRECATED: Use ck3raven.db.symbols instead
# This module outputs JSON; symbols.py outputs to SQLite (canonical)
# Kept for reference only - do not use in new code
"""
Reference Database Tool

Builds and queries a cross-reference database for CK3 content.
Tracks what references what - events calling effects, traits using modifiers, etc.

Usage:
    python -m ck3raven.tools.refdb build --path <vanilla> --output refdb.json
    python -m ck3raven.tools.refdb query --ref <name>
    python -m ck3raven.tools.refdb usages --of <definition>
"""

import json
import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set, Any, Optional
from dataclasses import dataclass, field

from ..parser import parse_file
from ..parser.parser import BlockNode, AssignmentNode, ValueNode


@dataclass
class Reference:
    """A reference from one thing to another."""
    source_file: str
    source_key: str
    source_line: int
    ref_type: str  # "calls", "uses", "requires", etc.
    target: str


@dataclass  
class Definition:
    """A definition of a named entity."""
    name: str
    def_type: str  # "scripted_effect", "trait", "event", etc.
    file: str
    line: int


class ReferenceDB:
    """Database of cross-references."""
    
    def __init__(self):
        self.definitions: Dict[str, Definition] = {}  # name -> Definition
        self.references: List[Reference] = []
        self.usages: Dict[str, List[Reference]] = defaultdict(list)  # target -> refs
    
    def add_definition(self, name: str, def_type: str, file: str, line: int):
        """Add a definition."""
        self.definitions[name] = Definition(
            name=name, def_type=def_type, file=file, line=line
        )
    
    def add_reference(self, source_file: str, source_key: str, source_line: int,
                     ref_type: str, target: str):
        """Add a reference."""
        ref = Reference(
            source_file=source_file,
            source_key=source_key, 
            source_line=source_line,
            ref_type=ref_type,
            target=target
        )
        self.references.append(ref)
        self.usages[target].append(ref)
    
    def get_usages(self, name: str) -> List[Reference]:
        """Get all usages of a name."""
        return self.usages.get(name, [])
    
    def get_definition(self, name: str) -> Optional[Definition]:
        """Get definition of a name."""
        return self.definitions.get(name)
    
    def to_dict(self) -> dict:
        """Export to dict."""
        return {
            "definitions": {
                k: {"name": v.name, "type": v.def_type, "file": v.file, "line": v.line}
                for k, v in self.definitions.items()
            },
            "references": [
                {
                    "source_file": r.source_file,
                    "source_key": r.source_key,
                    "source_line": r.source_line,
                    "ref_type": r.ref_type,
                    "target": r.target
                }
                for r in self.references
            ]
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ReferenceDB':
        """Load from dict."""
        db = cls()
        for k, v in data.get("definitions", {}).items():
            db.add_definition(v["name"], v["type"], v["file"], v["line"])
        for r in data.get("references", []):
            db.add_reference(
                r["source_file"], r["source_key"], r["source_line"],
                r["ref_type"], r["target"]
            )
        return db
    
    def save(self, path: Path):
        """Save to JSON."""
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, path: Path) -> 'ReferenceDB':
        """Load from JSON."""
        with open(path, 'r', encoding='utf-8') as f:
            return cls.from_dict(json.load(f))


# Known reference types
EFFECT_NAMES = {
    "trigger_event", "add_trait", "remove_trait", "add_modifier", "remove_modifier",
    "set_variable", "add_to_list", "run_interaction",
}

SCOPE_REFS = {
    "scope:actor", "scope:recipient", "scope:target", "scope:owner",
}


class RefDBBuilder:
    """Build a reference database from game files."""
    
    def __init__(self, base_path: Path):
        self.base_path = base_path
        self.db = ReferenceDB()
    
    def build(self):
        """Build the reference database."""
        print("Collecting definitions...")
        self._collect_definitions()
        
        print("Collecting references...")
        self._collect_references()
    
    def _collect_definitions(self):
        """Collect all named definitions."""
        # Scripted effects
        effects_path = self.base_path / "common" / "scripted_effects"
        if effects_path.exists():
            for file in effects_path.glob("*.txt"):
                self._collect_from_file(file, "scripted_effect")
        
        # Scripted triggers
        triggers_path = self.base_path / "common" / "scripted_triggers"
        if triggers_path.exists():
            for file in triggers_path.glob("*.txt"):
                self._collect_from_file(file, "scripted_trigger")
        
        # Traits
        traits_path = self.base_path / "common" / "traits"
        if traits_path.exists():
            for file in traits_path.glob("*.txt"):
                self._collect_from_file(file, "trait")
        
        # Events
        events_path = self.base_path / "events"
        if events_path.exists():
            for file in events_path.glob("*.txt"):
                self._collect_from_file(file, "event")
        
        print(f"  Found {len(self.db.definitions)} definitions")
    
    def _collect_from_file(self, file_path: Path, def_type: str):
        """Collect definitions from a file."""
        try:
            ast = parse_file(str(file_path))
            rel_path = str(file_path.relative_to(self.base_path))
            
            for node in ast.children:
                if isinstance(node, BlockNode) and not node.name.startswith('@'):
                    self.db.add_definition(node.name, def_type, rel_path, node.line)
        except:
            pass
    
    def _collect_references(self):
        """Collect all references."""
        # Scan common folders
        for folder in ["scripted_effects", "scripted_triggers", "character_interactions",
                       "decisions", "on_action"]:
            path = self.base_path / "common" / folder
            if path.exists():
                for file in path.rglob("*.txt"):
                    self._scan_file_for_refs(file)
        
        # Events
        events_path = self.base_path / "events"
        if events_path.exists():
            for file in events_path.rglob("*.txt"):
                self._scan_file_for_refs(file)
        
        print(f"  Found {len(self.db.references)} references")
    
    def _scan_file_for_refs(self, file_path: Path):
        """Scan a file for references to known definitions."""
        try:
            ast = parse_file(str(file_path))
            rel_path = str(file_path.relative_to(self.base_path))
            
            def walk(node, context_key=""):
                if isinstance(node, AssignmentNode):
                    # Check if this references a known definition
                    if isinstance(node.value, ValueNode):
                        target = str(node.value.value)
                        if target in self.db.definitions:
                            self.db.add_reference(
                                rel_path, context_key, node.line,
                                "uses", target
                            )
                    
                    # Check for effect calls
                    if node.key in self.db.definitions:
                        self.db.add_reference(
                            rel_path, context_key, node.line,
                            "calls", node.key
                        )
                    
                    if isinstance(node.value, BlockNode):
                        walk(node.value, context_key or node.key)
                        
                elif isinstance(node, BlockNode):
                    if node.name in self.db.definitions:
                        self.db.add_reference(
                            rel_path, context_key, node.line,
                            "calls", node.name
                        )
                    
                    for child in node.children:
                        walk(child, context_key or node.name)
                        
                elif hasattr(node, 'children'):
                    for child in node.children:
                        walk(child, context_key)
            
            walk(ast)
        except:
            pass


def main():
    parser = argparse.ArgumentParser(description="Reference database tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    build_parser = subparsers.add_parser("build", help="Build reference database")
    build_parser.add_argument("--path", "-p", type=Path, required=True,
                             help="Path to game/mod folder")
    build_parser.add_argument("--output", "-o", type=Path, default=Path("refdb.json"),
                             help="Output JSON file")
    
    query_parser = subparsers.add_parser("query", help="Query a reference")
    query_parser.add_argument("--input", "-i", type=Path, default=Path("refdb.json"))
    query_parser.add_argument("--ref", "-r", required=True, help="Name to look up")
    
    usages_parser = subparsers.add_parser("usages", help="Find usages")
    usages_parser.add_argument("--input", "-i", type=Path, default=Path("refdb.json"))
    usages_parser.add_argument("--of", required=True, help="Name to find usages of")
    
    args = parser.parse_args()
    
    if args.command == "build":
        builder = RefDBBuilder(args.path)
        builder.build()
        builder.db.save(args.output)
        print(f"\nDatabase saved to {args.output}")
    
    elif args.command == "query":
        db = ReferenceDB.load(args.input)
        defn = db.get_definition(args.ref)
        
        if defn:
            print(f"Definition: {defn.name}")
            print(f"  Type: {defn.def_type}")
            print(f"  File: {defn.file}")
            print(f"  Line: {defn.line}")
        else:
            print(f"No definition found for '{args.ref}'")
    
    elif args.command == "usages":
        db = ReferenceDB.load(args.input)
        usages = db.get_usages(getattr(args, 'of'))
        
        if usages:
            print(f"Usages of '{getattr(args, 'of')}' ({len(usages)} found):")
            for ref in usages[:20]:
                print(f"  {ref.source_file}:{ref.source_line} ({ref.ref_type})")
            if len(usages) > 20:
                print(f"  ... and {len(usages) - 20} more")
        else:
            print(f"No usages found for '{getattr(args, 'of')}'")


if __name__ == "__main__":
    main()

