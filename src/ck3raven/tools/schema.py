"""
CK3 Schema Learner

Learns validation rules from vanilla game files by analyzing:
- What blocks/keys are valid in each file type
- What scope types are available in different contexts
- What effects/triggers are commonly used where

This creates a "learned schema" that reduces false positives in linting.

Usage:
    python -m ck3raven.tools.schema learn --vanilla <path>
    python -m ck3raven.tools.schema show --type character_interactions
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
class ContextSchema:
    """Schema for a specific context (e.g., character_interactions)."""
    context_type: str
    
    scope_variables: Dict[str, str] = field(default_factory=dict)
    valid_blocks: Set[str] = field(default_factory=set)
    effects_used: Set[str] = field(default_factory=set)
    triggers_used: Set[str] = field(default_factory=set)
    value_patterns: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    files_analyzed: int = 0
    
    def to_dict(self) -> dict:
        return {
            "context_type": self.context_type,
            "scope_variables": self.scope_variables,
            "valid_blocks": sorted(self.valid_blocks),
            "effects_used": sorted(self.effects_used),
            "triggers_used": sorted(self.triggers_used),
            "value_patterns": {k: sorted(v) for k, v in self.value_patterns.items()},
            "files_analyzed": self.files_analyzed
        }
    
    @staticmethod
    def from_dict(data: dict) -> 'ContextSchema':
        schema = ContextSchema(context_type=data["context_type"])
        schema.scope_variables = data.get("scope_variables", {})
        schema.valid_blocks = set(data.get("valid_blocks", []))
        schema.effects_used = set(data.get("effects_used", []))
        schema.triggers_used = set(data.get("triggers_used", []))
        schema.value_patterns = defaultdict(set, {k: set(v) for k, v in data.get("value_patterns", {}).items()})
        schema.files_analyzed = data.get("files_analyzed", 0)
        return schema


# Known scope providers per context
SCOPE_PROVIDERS = {
    "character_interactions": {
        "actor": "character",
        "recipient": "character",
        "secondary_actor": "character",
        "secondary_recipient": "character",
        "scope:actor": "character",
        "scope:recipient": "character",
    },
    "events": {
        "root": "character",
        "scope:owner": "character",
        "scope:actor": "character",
    },
    "decisions": {
        "root": "character",
    },
}

# Known trigger vs effect blocks
TRIGGER_BLOCKS = {
    "is_shown", "is_valid", "trigger", "limit", "filter", 
    "can_pick", "potential", "allow", "ai_will_do",
}

EFFECT_BLOCKS = {
    "effect", "on_accept", "on_decline", "immediate", "after", "option",
}


class SchemaLearner:
    """Learn CK3 script schemas from vanilla game files."""
    
    def __init__(self, vanilla_path: Path):
        self.vanilla_path = vanilla_path
        self.schemas: Dict[str, ContextSchema] = {}
        self.all_scripted_effects: Set[str] = set()
        self.all_scripted_triggers: Set[str] = set()
        self.all_traits: Set[str] = set()
    
    def learn_all(self, content_types: List[str] = None):
        """Learn schemas from vanilla files."""
        if content_types is None:
            content_types = [
                "character_interactions",
                "events",
                "decisions",
                "on_actions",
                "scripted_effects",
                "scripted_triggers",
            ]
        
        # First pass: collect definitions
        print("Pass 1: Collecting definitions...")
        self._collect_definitions()
        
        # Second pass: learn schemas
        print("\nPass 2: Learning schemas...")
        for ct in content_types:
            print(f"  Learning {ct}...")
            self._learn_content_type(ct)
    
    def _collect_definitions(self):
        """Collect scripted effect/trigger names."""
        effects_path = self.vanilla_path / "common" / "scripted_effects"
        if effects_path.exists():
            for file in effects_path.glob("*.txt"):
                try:
                    ast = parse_file(str(file))
                    for node in ast.children:
                        if isinstance(node, BlockNode):
                            self.all_scripted_effects.add(node.name)
                except:
                    pass
        
        triggers_path = self.vanilla_path / "common" / "scripted_triggers"
        if triggers_path.exists():
            for file in triggers_path.glob("*.txt"):
                try:
                    ast = parse_file(str(file))
                    for node in ast.children:
                        if isinstance(node, BlockNode):
                            self.all_scripted_triggers.add(node.name)
                except:
                    pass
        
        print(f"  Found {len(self.all_scripted_effects)} scripted effects")
        print(f"  Found {len(self.all_scripted_triggers)} scripted triggers")
    
    def _learn_content_type(self, content_type: str):
        """Learn schema for a content type."""
        schema = ContextSchema(context_type=content_type)
        
        if content_type in SCOPE_PROVIDERS:
            schema.scope_variables.update(SCOPE_PROVIDERS[content_type])
        
        path_map = {
            "character_interactions": self.vanilla_path / "common" / "character_interactions",
            "events": self.vanilla_path / "events",
            "decisions": self.vanilla_path / "common" / "decisions",
            "on_actions": self.vanilla_path / "common" / "on_action",
            "scripted_effects": self.vanilla_path / "common" / "scripted_effects",
            "scripted_triggers": self.vanilla_path / "common" / "scripted_triggers",
        }
        
        path = path_map.get(content_type)
        if not path or not path.exists():
            return
        
        count = 0
        for file in path.glob("*.txt"):
            try:
                self._analyze_file(file, schema)
                count += 1
            except:
                pass
        
        schema.files_analyzed = count
        self.schemas[content_type] = schema
        
        print(f"    Analyzed {count} files, found {len(schema.valid_blocks)} blocks")
    
    def _analyze_file(self, file_path: Path, schema: ContextSchema):
        """Analyze a file to extract schema info."""
        ast = parse_file(str(file_path))
        
        for node in ast.children:
            if isinstance(node, BlockNode):
                for child in node.children:
                    if isinstance(child, AssignmentNode):
                        schema.valid_blocks.add(child.key)
                        
                        if child.key in TRIGGER_BLOCKS:
                            self._collect_triggers(child, schema)
                        elif child.key in EFFECT_BLOCKS:
                            self._collect_effects(child, schema)
                            
                    elif isinstance(child, BlockNode):
                        schema.valid_blocks.add(child.name)
    
    def _collect_triggers(self, node, schema: ContextSchema):
        """Collect trigger names from a trigger block."""
        if isinstance(node, BlockNode):
            for child in node.children:
                if isinstance(child, AssignmentNode):
                    schema.triggers_used.add(child.key)
                    self._collect_triggers(child.value, schema)
                elif isinstance(child, BlockNode):
                    schema.triggers_used.add(child.name)
                    self._collect_triggers(child, schema)
        elif isinstance(node, AssignmentNode):
            if isinstance(node.value, BlockNode):
                self._collect_triggers(node.value, schema)
    
    def _collect_effects(self, node, schema: ContextSchema):
        """Collect effect names from an effect block."""
        if isinstance(node, BlockNode):
            for child in node.children:
                if isinstance(child, AssignmentNode):
                    schema.effects_used.add(child.key)
                    self._collect_effects(child.value, schema)
                elif isinstance(child, BlockNode):
                    schema.effects_used.add(child.name)
                    self._collect_effects(child, schema)
        elif isinstance(node, AssignmentNode):
            if isinstance(node.value, BlockNode):
                self._collect_effects(node.value, schema)
    
    def save(self, output_path: Path):
        """Save learned schemas to JSON."""
        data = {
            "schemas": {k: v.to_dict() for k, v in self.schemas.items()},
            "scripted_effects": sorted(self.all_scripted_effects),
            "scripted_triggers": sorted(self.all_scripted_triggers),
        }
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, input_path: Path) -> 'SchemaLearner':
        """Load schemas from JSON."""
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        learner = cls(Path("."))  # dummy path
        learner.schemas = {k: ContextSchema.from_dict(v) for k, v in data.get("schemas", {}).items()}
        learner.all_scripted_effects = set(data.get("scripted_effects", []))
        learner.all_scripted_triggers = set(data.get("scripted_triggers", []))
        return learner


def main():
    parser = argparse.ArgumentParser(description="Learn CK3 schemas from vanilla files")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    learn_parser = subparsers.add_parser("learn", help="Learn schemas from vanilla")
    learn_parser.add_argument("--vanilla", type=Path, required=True,
                             help="Path to vanilla game folder")
    learn_parser.add_argument("--output", "-o", type=Path, default=Path("learned_schema.json"),
                             help="Output JSON file")
    
    show_parser = subparsers.add_parser("show", help="Show learned schema")
    show_parser.add_argument("--input", "-i", type=Path, default=Path("learned_schema.json"),
                            help="Schema JSON file")
    show_parser.add_argument("--type", "-t", help="Content type to show")
    
    args = parser.parse_args()
    
    if args.command == "learn":
        if not args.vanilla.exists():
            print(f"Error: {args.vanilla} not found", file=sys.stderr)
            sys.exit(1)
        
        learner = SchemaLearner(args.vanilla)
        learner.learn_all()
        learner.save(args.output)
        print(f"\nSchemas saved to {args.output}")
    
    elif args.command == "show":
        if not args.input.exists():
            print(f"Error: {args.input} not found", file=sys.stderr)
            sys.exit(1)
        
        learner = SchemaLearner.load(args.input)
        
        if args.type:
            if args.type in learner.schemas:
                print(json.dumps(learner.schemas[args.type].to_dict(), indent=2))
            else:
                print(f"Unknown type: {args.type}")
                print(f"Available: {', '.join(learner.schemas.keys())}")
        else:
            print("Available schemas:")
            for name, schema in learner.schemas.items():
                print(f"  {name}: {schema.files_analyzed} files, {len(schema.valid_blocks)} blocks")


if __name__ == "__main__":
    main()
