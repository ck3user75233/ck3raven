#!/usr/bin/env python3
"""
KGD Building Values Learner

Extracts and compares building script_values between vanilla and KGD.
KGD conveniently includes vanilla values in comments, making extraction easier.
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

# Paths
VANILLA_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game")
KGD_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310\3422759424")
OUTPUT_PATH = Path.home() / ".ck3raven" / "wip"


@dataclass
class VariableChange:
    """A single @variable change."""
    name: str
    vanilla_value: float
    kgd_value: float
    multiplier: Optional[float] = None
    category: str = "unknown"
    
    def __post_init__(self):
        if self.vanilla_value != 0:
            self.multiplier = self.kgd_value / self.vanilla_value


def parse_variables(content: str) -> dict[str, float]:
    """Extract all @variable = value definitions."""
    variables = {}
    for match in re.finditer(r'^@(\w+)\s*=\s*(-?[\d.]+)', content, re.MULTILINE):
        name = match.group(1)
        try:
            value = float(match.group(2))
            variables[name] = value
        except ValueError:
            pass
    return variables


def parse_variables_with_comments(content: str) -> dict[str, tuple[float, Optional[float]]]:
    """
    Extract @variable definitions with vanilla values from comments.
    Returns {name: (kgd_value, vanilla_value_from_comment)}
    
    KGD format: @var = 0.125    #0.25
    """
    variables = {}
    
    # Pattern: @name = value with optional #comment containing vanilla value
    pattern = r'^@(\w+)\s*=\s*(-?[\d.]+)\s*(?:#.*?(-?[\d.]+))?'
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        name = match.group(1)
        try:
            kgd_value = float(match.group(2))
            vanilla_value = None
            if match.group(3):
                try:
                    vanilla_value = float(match.group(3))
                except ValueError:
                    pass
            variables[name] = (kgd_value, vanilla_value)
        except ValueError:
            pass
    
    return variables


def categorize_variable(name: str) -> str:
    """Categorize a variable by its name."""
    name_lower = name.lower()
    
    if 'tax' in name_lower:
        return 'tax'
    elif 'levy' in name_lower:
        return 'levy'
    elif 'supply' in name_lower:
        return 'supply_limit'
    elif 'maa' in name_lower or 'maintenance' in name_lower:
        return 'maa_maintenance'
    elif 'development' in name_lower or 'dev_' in name_lower:
        return 'development'
    elif 'advantage' in name_lower:
        return 'advantage'
    elif 'garrison' in name_lower:
        return 'garrison'
    elif 'build' in name_lower and 'speed' in name_lower:
        return 'build_speed'
    elif 'cost' in name_lower:
        return 'cost'
    elif 'fort_level' in name_lower:
        return 'fort_level'
    elif 'scheme' in name_lower:
        return 'scheme'
    else:
        return 'other'


def analyze_building_values() -> dict:
    """Compare vanilla and KGD building values."""
    
    vanilla_file = VANILLA_PATH / "common" / "script_values" / "00_building_values.txt"
    kgd_file = KGD_PATH / "common" / "script_values" / "BKT_building_values.txt"
    
    if not vanilla_file.exists():
        raise FileNotFoundError(f"Vanilla file not found: {vanilla_file}")
    if not kgd_file.exists():
        raise FileNotFoundError(f"KGD file not found: {kgd_file}")
    
    vanilla_content = vanilla_file.read_text(encoding='utf-8-sig')
    kgd_content = kgd_file.read_text(encoding='utf-8-sig')
    
    # Parse vanilla values
    vanilla_vars = parse_variables(vanilla_content)
    
    # Parse KGD values with embedded vanilla comments
    kgd_vars_with_comments = parse_variables_with_comments(kgd_content)
    
    # Build comparison
    changes = []
    unchanged = []
    kgd_only = []
    
    # Check all KGD variables
    for name, (kgd_val, comment_vanilla) in kgd_vars_with_comments.items():
        # Try to find vanilla value from comment or actual vanilla file
        vanilla_val = comment_vanilla if comment_vanilla is not None else vanilla_vars.get(name)
        
        if vanilla_val is not None:
            if vanilla_val != kgd_val:
                change = VariableChange(
                    name=name,
                    vanilla_value=vanilla_val,
                    kgd_value=kgd_val,
                    category=categorize_variable(name)
                )
                changes.append(change)
            else:
                unchanged.append(name)
        else:
            kgd_only.append((name, kgd_val))
    
    # Aggregate patterns by category
    by_category = defaultdict(list)
    for change in changes:
        by_category[change.category].append(change)
    
    # Compute category statistics
    category_stats = {}
    for category, cat_changes in by_category.items():
        multipliers = [c.multiplier for c in cat_changes if c.multiplier is not None and c.multiplier > 0]
        if multipliers:
            category_stats[category] = {
                "count": len(cat_changes),
                "avg_multiplier": sum(multipliers) / len(multipliers),
                "min_multiplier": min(multipliers),
                "max_multiplier": max(multipliers),
                "examples": [
                    {
                        "name": c.name,
                        "vanilla": c.vanilla_value,
                        "kgd": c.kgd_value,
                        "multiplier": c.multiplier
                    }
                    for c in cat_changes[:5]
                ]
            }
    
    return {
        "metadata": {
            "source_mod": "KGD: The Great Rebalance",
            "workshop_id": "3422759424",
            "analysis_type": "building_values",
            "vanilla_file": str(vanilla_file),
            "kgd_file": str(kgd_file),
        },
        "summary": {
            "total_variables_compared": len(changes) + len(unchanged),
            "changed": len(changes),
            "unchanged": len(unchanged),
            "kgd_only": len(kgd_only),
        },
        "category_stats": category_stats,
        "all_changes": [
            {
                "name": c.name,
                "category": c.category,
                "vanilla": c.vanilla_value,
                "kgd": c.kgd_value,
                "multiplier": c.multiplier
            }
            for c in sorted(changes, key=lambda x: (x.category, x.name))
        ],
        "unchanged_variables": unchanged,
        "kgd_only_variables": [
            {"name": name, "value": val}
            for name, val in kgd_only
        ]
    }


def main():
    print("Analyzing KGD building values...")
    
    result = analyze_building_values()
    
    # Print summary
    print(f"\nSummary:")
    print(f"  Changed variables: {result['summary']['changed']}")
    print(f"  Unchanged variables: {result['summary']['unchanged']}")
    print(f"  KGD-only variables: {result['summary']['kgd_only']}")
    
    print(f"\nBy category:")
    for cat, stats in result['category_stats'].items():
        print(f"  {cat}: {stats['count']} changes, avg multiplier {stats['avg_multiplier']:.2f}x")
    
    # Save to file
    output_file = OUTPUT_PATH / "kgd_building_values.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    print(f"\nResults saved to {output_file}")


if __name__ == "__main__":
    main()
