"""
PDX Script Linter

Checks PDX/CK3 script files for common issues:
- Invalid scope usage (e.g., has_title in culture scope)
- Missing required fields
- Deprecated syntax
- Suspicious patterns

Usage:
    python -m ck3raven.tools.lint <file>                    # Lint single file
    python -m ck3raven.tools.lint <directory> --recursive   # Lint all files
    python -m ck3raven.tools.lint <file> --fix              # Auto-fix where possible
"""

import argparse
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

from ..parser import parse_file, parse_source
from ..parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode


class Severity(Enum):
    """Lint issue severity levels."""
    ERROR = "error"         # Will cause game errors/crashes
    WARNING = "warning"     # Likely a bug but may not crash
    INFO = "info"           # Style issues or suggestions
    HINT = "hint"           # Minor improvements


@dataclass
class LintIssue:
    """A single lint issue found in the code."""
    severity: Severity
    code: str               # e.g., "E001", "W002"
    message: str
    file: str
    line: int
    column: int = 0
    context: str = ""       # The problematic code snippet
    suggestion: str = ""    # How to fix it
    
    def __str__(self):
        prefix = {
            Severity.ERROR: "[ERROR]",
            Severity.WARNING: "[WARNING]",
            Severity.INFO: "[INFO]",
            Severity.HINT: "[HINT]"
        }[self.severity]
        
        loc = f"{self.file}:{self.line}"
        if self.column:
            loc += f":{self.column}"
        
        msg = f"{prefix} {self.code} {loc}: {self.message}"
        if self.context:
            msg += f"\n    {self.context}"
        if self.suggestion:
            msg += f"\n    -> {self.suggestion}"
        return msg


# ============================================================================
# SCOPE DEFINITIONS
# ============================================================================

SCOPES = {
    "character": {
        "valid_triggers": {
            "has_trait", "has_title", "is_ruler", "is_alive", "age", "gold",
            "prestige", "piety", "dynasty", "culture", "faith", "realm_size",
            "has_realm_law", "has_government", "any_held_title", "any_vassal",
            "any_courtier", "any_realm_county", "is_ai", "is_female", "is_male",
            "has_character_flag", "has_character_modifier", "num_of_children",
            "has_perk", "has_lifestyle", "diplomacy", "martial", "stewardship",
            "intrigue", "learning", "prowess", "health", "stress", "dread",
            "tyranny", "has_relation", "opinion", "reverse_opinion",
            "number_maa_soldiers_of_base_type", "has_claim_on",
        },
        "child_scopes": {
            "liege", "host", "top_liege", "dynasty_head", "house_head",
            "primary_spouse", "betrothed", "father", "mother", "primary_heir",
            "player_heir", "designated_heir", "killer", "real_father",
            "any_child", "any_sibling", "any_spouse", "any_consort",
        }
    },
    "culture": {
        "valid_triggers": {
            "has_cultural_pillar", "has_cultural_tradition", "has_cultural_era",
            "has_innovation", "culture_age", "any_parent_culture",
            "has_same_culture_heritage", "culture_number_of_counties",
        },
        "child_scopes": {
            "culture_head",
        }
    },
    "title": {
        "valid_triggers": {
            "tier", "is_held", "holder", "de_jure_liege", "capital_county",
            "has_de_jure_county",
        },
        "child_scopes": {
            "holder", "de_jure_liege", "de_facto_liege",
        }
    },
    "faith": {
        "valid_triggers": {
            "has_doctrine", "religion", "has_doctrine_parameter",
            "fervor", "is_reformed",
        },
        "child_scopes": {
            "religious_head",
        }
    }
}

SCOPE_SPECIFIC_TRIGGERS = {
    "has_title": ["character"],
    "has_claim_on": ["character"],
    "is_ruler": ["character"],
    "has_trait": ["character"],
    "has_cultural_pillar": ["culture"],
    "has_cultural_tradition": ["culture"],
    "has_innovation": ["culture"],
    "has_doctrine": ["faith"],
    "tier": ["title"],
}


# ============================================================================
# LINTER RULES
# ============================================================================

class LintRule:
    """Base class for lint rules."""
    
    code: str = "X000"
    severity: Severity = Severity.WARNING
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        """Check a node and return any issues found."""
        raise NotImplementedError


class ScopeViolationRule(LintRule):
    """Check for triggers used in wrong scopes."""
    
    code = "E001"
    severity = Severity.ERROR
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        issues = []
        current_scope = context.get("scope", "unknown")
        file = context.get("file", "<unknown>")
        
        if isinstance(node, AssignmentNode):
            trigger = node.key
            
            if trigger in SCOPE_SPECIFIC_TRIGGERS:
                valid_scopes = SCOPE_SPECIFIC_TRIGGERS[trigger]
                if current_scope not in valid_scopes and current_scope != "unknown":
                    issues.append(LintIssue(
                        severity=self.severity,
                        code=self.code,
                        message=f"'{trigger}' requires {valid_scopes} scope, but found in '{current_scope}' scope",
                        file=file,
                        line=node.line,
                        context=f"{trigger} = ...",
                        suggestion=f"Wrap in scope:character = {{ {trigger} = ... }}"
                    ))
        
        return issues


class MissingRequiredFieldRule(LintRule):
    """Check for missing required fields in blocks."""
    
    code = "W001"
    severity = Severity.WARNING
    
    REQUIRED_FIELDS = {
        "tradition_": ["category", "is_shown", "can_pick", "cost"],
        "decision_": ["is_shown", "is_valid", "effect"],
        "event_": ["type", "title", "desc"],
    }
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        issues = []
        file = context.get("file", "<unknown>")
        
        if isinstance(node, BlockNode):
            for prefix, required in self.REQUIRED_FIELDS.items():
                if node.name.startswith(prefix):
                    keys = set()
                    for child in node.children:
                        if isinstance(child, AssignmentNode):
                            keys.add(child.key)
                        elif isinstance(child, BlockNode):
                            keys.add(child.name)
                    
                    for field in required:
                        if field not in keys:
                            issues.append(LintIssue(
                                severity=self.severity,
                                code=self.code,
                                message=f"Missing required field '{field}' in {node.name}",
                                file=file,
                                line=node.line,
                                context=f"{node.name} = {{ ... }}",
                                suggestion=f"Add '{field} = {{ ... }}' to the block"
                            ))
        
        return issues


class DeprecatedSyntaxRule(LintRule):
    """Check for deprecated or outdated syntax."""
    
    code = "W002"
    severity = Severity.WARNING
    
    DEPRECATED = {
        "e_roman_empire": ("title name", "Use 'h_roman_empire' for 1.18+"),
        "random_list": ("trigger context", "Use 'random' with 'chance' for triggers"),
    }
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        issues = []
        file = context.get("file", "<unknown>")
        
        if isinstance(node, ValueNode):
            for deprecated, (ctx, suggestion) in self.DEPRECATED.items():
                if deprecated in str(node.value):
                    issues.append(LintIssue(
                        severity=self.severity,
                        code=self.code,
                        message=f"Deprecated {ctx}: '{deprecated}'",
                        file=file,
                        line=node.line,
                        context=str(node.value),
                        suggestion=suggestion
                    ))
        
        return issues


class DuplicateKeyRule(LintRule):
    """Check for duplicate keys in the same block (usually a bug)."""
    
    code = "W003"
    severity = Severity.WARNING
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        issues = []
        file = context.get("file", "<unknown>")
        
        if isinstance(node, BlockNode):
            keys_seen = defaultdict(list)
            
            for child in node.children:
                if isinstance(child, AssignmentNode):
                    keys_seen[child.key].append(child.line)
                elif isinstance(child, BlockNode):
                    keys_seen[child.name].append(child.line)
            
            for key, lines in keys_seen.items():
                if len(lines) > 1:
                    allowed_duplicates = {
                        'if', 'else', 'else_if', 'switch', 'trigger_if', 'trigger_else',
                        'limit', 'trigger', 'modifier', 'has_trait', 'has_title',
                        'has_cultural_pillar', 'has_cultural_tradition', 'has_innovation',
                        'has_doctrine', 'has_relation', 'has_character_flag', 'has_realm_law',
                        'has_perk', 'has_lifestyle', 'has_government',
                        'add', 'subtract', 'multiply', 'divide', 'min', 'max',
                        'any_ruler', 'any_vassal', 'any_courtier', 'any_child',
                        'any_spouse', 'any_sibling', 'any_in_list', 'every_ruler',
                        'random_ruler', 'ordered_ruler',
                        'custom_tooltip', 'desc', 'show_as_tooltip',
                        'add_trait', 'remove_trait', 'add_modifier', 'add_character_flag',
                    }
                    if key not in allowed_duplicates:
                        issues.append(LintIssue(
                            severity=self.severity,
                            code=self.code,
                            message=f"Duplicate key '{key}' in block (lines {lines})",
                            file=file,
                            line=lines[0],
                            context=f"{key} appears {len(lines)} times",
                            suggestion="Remove duplicate or use list syntax"
                        ))
        
        return issues


class EmptyBlockRule(LintRule):
    """Check for empty blocks that may be unintentional."""
    
    code = "I001"
    severity = Severity.INFO
    
    def check(self, node, context: Dict[str, Any]) -> List[LintIssue]:
        issues = []
        file = context.get("file", "<unknown>")
        
        if isinstance(node, BlockNode):
            if not node.children:
                if node.name not in {'modifier', 'ai_will_do', 'parameters'}:
                    issues.append(LintIssue(
                        severity=self.severity,
                        code=self.code,
                        message=f"Empty block '{node.name}'",
                        file=file,
                        line=node.line,
                        suggestion="Add content or remove if unneeded"
                    ))
        
        return issues


# ============================================================================
# LINTER ENGINE
# ============================================================================

class PDXLinter:
    """
    Main linter class that runs rules against PDX files.
    """
    
    def __init__(self, rules: List[LintRule] = None):
        self.rules = rules or [
            ScopeViolationRule(),
            MissingRequiredFieldRule(),
            DeprecatedSyntaxRule(),
            DuplicateKeyRule(),
            EmptyBlockRule(),
        ]
    
    def lint_file(self, file_path: Path) -> List[LintIssue]:
        """Lint a file and return all issues."""
        try:
            ast = parse_file(str(file_path))
            return self.lint_ast(ast, str(file_path))
        except Exception as e:
            return [LintIssue(
                severity=Severity.ERROR,
                code="E000",
                message=f"Parse error: {e}",
                file=str(file_path),
                line=0
            )]
    
    def lint_ast(self, root: RootNode, filename: str = "<unknown>") -> List[LintIssue]:
        """Lint an AST and return all issues."""
        issues = []
        context = {"file": filename, "scope": "root"}
        
        self._walk(root, context, issues)
        
        return sorted(issues, key=lambda i: (i.file, i.line, i.severity.value))
    
    def _walk(self, node, context: Dict[str, Any], issues: List[LintIssue]):
        """Walk the AST and apply rules."""
        for rule in self.rules:
            issues.extend(rule.check(node, context))
        
        child_context = context.copy()
        
        if isinstance(node, BlockNode):
            if node.name in ["is_shown", "can_pick", "is_valid", "trigger"]:
                if "tradition_" in context.get("parent_name", ""):
                    child_context["scope"] = "culture"
            elif node.name.startswith("scope:"):
                child_context["scope"] = node.name.split(":")[1]
            
            child_context["parent_name"] = node.name
            
            for child in node.children:
                self._walk(child, child_context, issues)
        
        elif isinstance(node, RootNode):
            for child in node.children:
                self._walk(child, child_context, issues)
        
        elif isinstance(node, AssignmentNode):
            if node.value:
                self._walk(node.value, child_context, issues)


def lint_file(file_path: Path) -> List[LintIssue]:
    """Convenience function to lint a file."""
    linter = PDXLinter()
    return linter.lint_file(file_path)


def lint_directory(dir_path: Path, pattern: str = "*.txt",
                   recursive: bool = True) -> Dict[str, List[LintIssue]]:
    """Lint all matching files in a directory."""
    linter = PDXLinter()
    results = {}
    
    glob_method = dir_path.rglob if recursive else dir_path.glob
    
    for file_path in glob_method(pattern):
        if not file_path.is_file():
            continue
        
        issues = linter.lint_file(file_path)
        if issues:
            results[str(file_path)] = issues
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Lint PDX/CK3 script files")
    parser.add_argument("path", type=Path, help="File or directory to lint")
    parser.add_argument("--recursive", "-r", action="store_true",
                       help="Recursively lint directory")
    parser.add_argument("--severity", "-s", choices=["error", "warning", "info", "hint"],
                       default="warning", help="Minimum severity to report")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")
    
    args = parser.parse_args()
    
    min_severity = {
        "error": 0,
        "warning": 1,
        "info": 2,
        "hint": 3
    }[args.severity]
    
    severity_order = [Severity.ERROR, Severity.WARNING, Severity.INFO, Severity.HINT]
    
    linter = PDXLinter()
    all_issues = []
    
    if args.path.is_file():
        all_issues = linter.lint_file(args.path)
    elif args.path.is_dir():
        results = lint_directory(args.path, recursive=args.recursive)
        for issues in results.values():
            all_issues.extend(issues)
    else:
        print(f"Error: {args.path} not found", file=sys.stderr)
        sys.exit(1)
    
    all_issues = [i for i in all_issues 
                  if severity_order.index(i.severity) <= min_severity]
    
    if args.json:
        import json
        output = [
            {
                "severity": i.severity.value,
                "code": i.code,
                "message": i.message,
                "file": i.file,
                "line": i.line,
                "column": i.column,
                "context": i.context,
                "suggestion": i.suggestion
            }
            for i in all_issues
        ]
        print(json.dumps(output, indent=2))
    else:
        for issue in all_issues:
            print(issue)
            print()
        
        counts = defaultdict(int)
        for i in all_issues:
            counts[i.severity] += 1
        
        print(f"\nSummary: {len(all_issues)} issues found")
        for sev in Severity:
            if counts[sev]:
                print(f"  {sev.value}: {counts[sev]}")
    
    error_count = sum(1 for i in all_issues if i.severity == Severity.ERROR)
    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()
