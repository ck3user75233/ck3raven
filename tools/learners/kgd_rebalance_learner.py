#!/usr/bin/env python3
"""
KGD Rebalance Pattern Learner v3

Improvements over v2:
- Captures terrain_bonus changes (nested structure)
- Captures counter changes
- Better structured output for rule application
"""

import json
import sqlite3
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import defaultdict
import statistics

# Paths
DB_PATH = Path.home() / ".ck3raven" / "ck3raven.db"
VANILLA_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game")
KGD_PATH = Path(r"C:\Program Files (x86)\Steam\steamapps\workshop\content\1158310\3422759424")
OUTPUT_PATH = Path.home() / ".ck3raven" / "wip"
VANILLA_CVID = 1
KGD_WORKSHOP_ID = "3422759424"

# Terrain types in CK3
TERRAIN_TYPES = [
    "plains", "farmlands", "hills", "mountains", "desert", "desert_mountains",
    "oasis", "jungle", "forest", "taiga", "wetlands", "steppe", "floodplains",
    "drylands", "sea", "coastal_sea", "ocean"
]

# Combat stat fields
COMBAT_STATS = ["damage", "toughness", "pursuit", "screen", "siege_value"]

MAA_NUMERIC_FIELDS = COMBAT_STATS + ["stack", "provision_cost"]


@dataclass
class TerrainBonus:
    """Terrain bonus for a single terrain type."""
    terrain: str
    damage: Optional[float] = None
    toughness: Optional[float] = None
    pursuit: Optional[float] = None
    screen: Optional[float] = None
    
    def to_dict(self) -> dict:
        return {k: v for k, v in {
            "damage": self.damage,
            "toughness": self.toughness,
            "pursuit": self.pursuit,
            "screen": self.screen,
        }.items() if v is not None}
    
    def __eq__(self, other):
        if not isinstance(other, TerrainBonus):
            return False
        return (self.terrain == other.terrain and 
                self.damage == other.damage and
                self.toughness == other.toughness and
                self.pursuit == other.pursuit and
                self.screen == other.screen)


@dataclass
class CounterInfo:
    """Counter relationship for an MAA."""
    counters: dict[str, float] = field(default_factory=dict)  # unit_type -> effectiveness
    
    def to_dict(self) -> dict:
        return self.counters.copy()


@dataclass
class MAADefinition:
    """Full MAA definition with all relevant fields."""
    name: str
    maa_type: str  # skirmishers, archers, etc.
    
    # Base stats
    damage: Optional[float] = None
    toughness: Optional[float] = None
    pursuit: Optional[float] = None
    screen: Optional[float] = None
    stack: Optional[float] = None
    siege_value: Optional[float] = None
    provision_cost: Optional[float] = None
    
    # Structured data
    terrain_bonuses: list[TerrainBonus] = field(default_factory=list)
    counters: CounterInfo = field(default_factory=CounterInfo)
    
    # Raw block for debugging
    raw_block: str = ""
    
    def get_terrain_bonus(self, terrain: str) -> Optional[TerrainBonus]:
        for tb in self.terrain_bonuses:
            if tb.terrain == terrain:
                return tb
        return None


@dataclass
class MAADiff:
    """Difference between vanilla and KGD for one MAA."""
    name: str
    maa_type: str
    vanilla: MAADefinition
    kgd: MAADefinition
    
    def numeric_changes(self) -> dict[str, tuple[float, float, Optional[float]]]:
        """Returns {field: (vanilla, kgd, multiplier)}."""
        changes = {}
        for field in MAA_NUMERIC_FIELDS:
            v_val = getattr(self.vanilla, field, None)
            k_val = getattr(self.kgd, field, None)
            
            if v_val is not None and k_val is not None:
                mult = k_val / v_val if v_val != 0 else None
                if v_val != k_val:
                    changes[field] = (v_val, k_val, mult)
        return changes
    
    def terrain_changes(self) -> list[dict]:
        """Returns list of terrain bonus changes."""
        changes = []
        
        # Get all terrain types from both
        all_terrains = set()
        for tb in self.vanilla.terrain_bonuses:
            all_terrains.add(tb.terrain)
        for tb in self.kgd.terrain_bonuses:
            all_terrains.add(tb.terrain)
        
        for terrain in sorted(all_terrains):
            van_tb = self.vanilla.get_terrain_bonus(terrain)
            kgd_tb = self.kgd.get_terrain_bonus(terrain)
            
            if van_tb != kgd_tb:
                change = {
                    "terrain": terrain,
                    "vanilla": van_tb.to_dict() if van_tb else None,
                    "kgd": kgd_tb.to_dict() if kgd_tb else None,
                }
                
                # Calculate field-level changes
                if van_tb and kgd_tb:
                    field_changes = {}
                    for stat in ["damage", "toughness", "pursuit", "screen"]:
                        v = getattr(van_tb, stat)
                        k = getattr(kgd_tb, stat)
                        if v != k:
                            field_changes[stat] = {"vanilla": v, "kgd": k}
                    change["field_changes"] = field_changes
                
                changes.append(change)
        
        return changes
    
    def counter_changes(self) -> dict:
        """Returns counter relationship changes."""
        van_counters = self.vanilla.counters.counters
        kgd_counters = self.kgd.counters.counters
        
        if van_counters == kgd_counters:
            return {}
        
        return {
            "vanilla": van_counters,
            "kgd": kgd_counters,
            "added": {k: v for k, v in kgd_counters.items() if k not in van_counters},
            "removed": {k: v for k, v in van_counters.items() if k not in kgd_counters},
            "changed": {k: {"vanilla": van_counters[k], "kgd": kgd_counters[k]} 
                       for k in van_counters if k in kgd_counters and van_counters[k] != kgd_counters[k]},
        }


def extract_block(content: str, start_pattern: str) -> Optional[str]:
    """Extract a brace-delimited block starting with pattern."""
    match = re.search(start_pattern, content, re.MULTILINE)
    if not match:
        return None
    
    start = match.start()
    brace_count = 0
    in_block = False
    
    for i, char in enumerate(content[start:]):
        if char == '{':
            brace_count += 1
            in_block = True
        elif char == '}':
            brace_count -= 1
            if in_block and brace_count == 0:
                return content[start:start + i + 1]
    
    return None


def extract_terrain_bonuses(block: str) -> list[TerrainBonus]:
    """Extract terrain_bonus block and parse it."""
    bonuses = []
    
    # Find terrain_bonus block
    tb_block = extract_block(block, r'\bterrain_bonus\s*=\s*\{')
    if not tb_block:
        return bonuses
    
    # Parse each terrain
    for terrain in TERRAIN_TYPES:
        pattern = rf'\b{terrain}\s*=\s*\{{'
        terrain_match = re.search(pattern, tb_block)
        if terrain_match:
            # Extract this terrain's bonuses
            terrain_block = extract_block(tb_block[terrain_match.start():], pattern)
            if terrain_block:
                tb = TerrainBonus(terrain=terrain)
                
                for stat in ["damage", "toughness", "pursuit", "screen"]:
                    stat_match = re.search(rf'\b{stat}\s*=\s*(-?\d+(?:\.\d+)?)', terrain_block)
                    if stat_match:
                        setattr(tb, stat, float(stat_match.group(1)))
                
                bonuses.append(tb)
    
    return bonuses


def extract_counters(block: str) -> CounterInfo:
    """Extract counters block."""
    counters = CounterInfo()
    
    counter_block = extract_block(block, r'\bcounters\s*=\s*\{')
    if not counter_block:
        return counters
    
    # Parse each counter: unit_type = value
    for match in re.finditer(r'(\w+)\s*=\s*(\d+(?:\.\d+)?)', counter_block):
        unit_type = match.group(1)
        if unit_type not in ["counters"]:  # Skip the block name itself
            counters.counters[unit_type] = float(match.group(2))
    
    return counters


def parse_maa_block(name: str, block: str, global_vars: dict[str, float]) -> MAADefinition:
    """Parse an MAA block into a structured definition."""
    maa = MAADefinition(name=name, raw_block=block, maa_type="unknown")
    
    # Get type
    type_match = re.search(r'\btype\s*=\s*(\w+)', block)
    if type_match:
        maa.maa_type = type_match.group(1)
    
    # Extract numeric fields
    for field in MAA_NUMERIC_FIELDS:
        pattern = rf'\b{field}\s*=\s*(@?[\w.]+)'
        match = re.search(pattern, block)
        if match:
            val_str = match.group(1)
            if val_str.startswith('@'):
                var_name = val_str[1:]
                if var_name in global_vars:
                    setattr(maa, field, global_vars[var_name])
            else:
                try:
                    setattr(maa, field, float(val_str))
                except ValueError:
                    pass
    
    # Extract terrain bonuses
    maa.terrain_bonuses = extract_terrain_bonuses(block)
    
    # Extract counters
    maa.counters = extract_counters(block)
    
    return maa


def extract_all_maa_blocks(content: str) -> dict[str, str]:
    """Extract all MAA definition blocks from content."""
    blocks = {}
    pattern = r'^(\w+)\s*=\s*\{'
    
    for match in re.finditer(pattern, content, re.MULTILINE):
        name = match.group(1)
        if name.startswith('@'):
            continue
        
        block = extract_block(content, rf'^{re.escape(name)}\s*=\s*\{{')
        if block:
            blocks[name] = block
    
    return blocks


def load_global_variables(path: Path) -> dict[str, float]:
    """Load @variable definitions from all MAA files."""
    var_defs = {}
    maa_dir = path / "common" / "men_at_arms_types"
    
    if maa_dir.exists():
        for file in maa_dir.glob("*.txt"):
            try:
                content = file.read_text(encoding='utf-8-sig')
                for match in re.finditer(r'^@(\w+)\s*=\s*(\d+(?:\.\d+)?)', content, re.MULTILINE):
                    var_defs[match.group(1)] = float(match.group(2))
            except Exception:
                pass
    
    return var_defs


def find_matching_files(vanilla_files: list[Path], kgd_files: list[Path]) -> list[tuple[Path, Path]]:
    """Match vanilla files to KGD equivalents."""
    matches = []
    
    kgd_by_suffix = {}
    for kgd_file in kgd_files:
        name = kgd_file.name
        if name.startswith('kBKT_'):
            name = name[5:]
        name = re.sub(r'^\d+_', '', name)
        kgd_by_suffix[name] = kgd_file
    
    for van_file in vanilla_files:
        name = van_file.name
        name = re.sub(r'^\d+_', '', name)
        
        if name in kgd_by_suffix:
            matches.append((van_file, kgd_by_suffix[name]))
    
    return matches


def analyze_maa_changes() -> tuple[list[MAADiff], dict, dict]:
    """Analyze all MAA changes between vanilla and KGD."""
    vanilla_maa_dir = VANILLA_PATH / "common" / "men_at_arms_types"
    kgd_maa_dir = KGD_PATH / "common" / "men_at_arms_types"
    
    vanilla_vars = load_global_variables(VANILLA_PATH)
    kgd_vars = load_global_variables(KGD_PATH)
    
    print(f"Loaded {len(vanilla_vars)} vanilla @variables, {len(kgd_vars)} KGD @variables")
    
    vanilla_files = list(vanilla_maa_dir.glob("*.txt"))
    kgd_files = list(kgd_maa_dir.glob("*.txt"))
    
    matched_pairs = find_matching_files(vanilla_files, kgd_files)
    print(f"Matched {len(matched_pairs)} file pairs")
    
    all_diffs = []
    
    for van_file, kgd_file in matched_pairs:
        try:
            van_content = van_file.read_text(encoding='utf-8-sig')
            kgd_content = kgd_file.read_text(encoding='utf-8-sig')
            
            van_blocks = extract_all_maa_blocks(van_content)
            kgd_blocks = extract_all_maa_blocks(kgd_content)
            
            for name in set(van_blocks.keys()) & set(kgd_blocks.keys()):
                van_maa = parse_maa_block(name, van_blocks[name], vanilla_vars)
                kgd_maa = parse_maa_block(name, kgd_blocks[name], kgd_vars)
                
                diff = MAADiff(
                    name=name,
                    maa_type=van_maa.maa_type,
                    vanilla=van_maa,
                    kgd=kgd_maa,
                )
                all_diffs.append(diff)
                
        except Exception as e:
            print(f"Error processing {van_file.name}: {e}")
    
    return all_diffs, vanilla_vars, kgd_vars


def aggregate_terrain_patterns(diffs: list[MAADiff]) -> dict:
    """Aggregate terrain bonus patterns across all MAAs."""
    # Group by maa_type and terrain
    patterns = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    
    for diff in diffs:
        for tc in diff.terrain_changes():
            terrain = tc["terrain"]
            if tc.get("field_changes"):
                for stat, change in tc["field_changes"].items():
                    v = change.get("vanilla")
                    k = change.get("kgd")
                    if v is not None and k is not None:
                        patterns[diff.maa_type][terrain][stat].append({
                            "maa": diff.name,
                            "vanilla": v,
                            "kgd": k,
                            "delta": k - v,
                        })
    
    return dict(patterns)


def main():
    """Main entry point."""
    print("=" * 70)
    print("KGD Rebalance Pattern Learner v3 (with Terrain & Counters)")
    print("=" * 70)
    
    diffs, vanilla_vars, kgd_vars = analyze_maa_changes()
    print(f"\nFound {len(diffs)} MAA definitions with both vanilla and KGD versions")
    
    # Collect all changes
    all_numeric_changes = []
    all_terrain_changes = []
    all_counter_changes = []
    
    for diff in diffs:
        nc = diff.numeric_changes()
        if nc:
            all_numeric_changes.append({"name": diff.name, "type": diff.maa_type, "changes": nc})
        
        tc = diff.terrain_changes()
        if tc:
            all_terrain_changes.append({"name": diff.name, "type": diff.maa_type, "changes": tc})
        
        cc = diff.counter_changes()
        if cc and (cc.get("added") or cc.get("removed") or cc.get("changed")):
            all_counter_changes.append({"name": diff.name, "type": diff.maa_type, "changes": cc})
    
    # Print terrain changes
    print("\n" + "=" * 70)
    print("TERRAIN BONUS CHANGES")
    print("=" * 70)
    
    terrain_patterns = aggregate_terrain_patterns(diffs)
    for maa_type in sorted(terrain_patterns.keys()):
        terrains = terrain_patterns[maa_type]
        if terrains:
            print(f"\n{maa_type.upper()}:")
            for terrain in sorted(terrains.keys()):
                stats = terrains[terrain]
                stat_strs = []
                for stat, changes in stats.items():
                    deltas = [c["delta"] for c in changes]
                    mean_delta = statistics.mean(deltas)
                    if abs(mean_delta) > 0.1:
                        stat_strs.append(f"{stat}: {mean_delta:+.1f}")
                if stat_strs:
                    print(f"  {terrain}: {', '.join(stat_strs)}")
    
    # Print counter changes
    print("\n" + "=" * 70)
    print("COUNTER RELATIONSHIP CHANGES")
    print("=" * 70)
    
    for cc in all_counter_changes[:10]:  # Show first 10
        print(f"\n{cc['name']} ({cc['type']}):")
        changes = cc["changes"]
        if changes.get("added"):
            print(f"  Added: {changes['added']}")
        if changes.get("removed"):
            print(f"  Removed: {changes['removed']}")
        if changes.get("changed"):
            print(f"  Changed: {changes['changed']}")
    
    if len(all_counter_changes) > 10:
        print(f"\n... and {len(all_counter_changes) - 10} more counter changes")
    
    # Summary statistics
    print("\n" + "=" * 70)
    print("SUMMARY STATISTICS")
    print("=" * 70)
    
    # Stack changes
    stack_mults = []
    for nc in all_numeric_changes:
        if "stack" in nc["changes"]:
            _, _, mult = nc["changes"]["stack"]
            if mult:
                stack_mults.append(mult)
    
    if stack_mults:
        print(f"\nSTACK (Regiment Size): n={len(stack_mults)}")
        print(f"  Mean: x{statistics.mean(stack_mults):.2f} ({(statistics.mean(stack_mults)-1)*100:+.0f}%)")
        print(f"  Range: x{min(stack_mults):.2f} to x{max(stack_mults):.2f}")
    
    # Terrain bonus summary
    total_terrain_changes = sum(len(tc["changes"]) for tc in all_terrain_changes)
    print(f"\nTERRAIN BONUSES:")
    print(f"  {len(all_terrain_changes)} MAAs with terrain changes")
    print(f"  {total_terrain_changes} individual terrain modifications")
    
    print(f"\nCOUNTERS:")
    print(f"  {len(all_counter_changes)} MAAs with counter changes")
    
    # Save full output
    output = {
        "metadata": {
            "source_mod": "KGD: The Great Rebalance",
            "workshop_id": KGD_WORKSHOP_ID,
            "analysis_version": "3.0",
            "maa_count": len(diffs),
        },
        "global_variables": {
            "vanilla": {k: v for k, v in vanilla_vars.items() if 'provisions' in k or 'maa' in k},
            "kgd": {k: v for k, v in kgd_vars.items() if 'provisions' in k or 'maa' in k},
        },
        "numeric_changes": all_numeric_changes,
        "terrain_changes": all_terrain_changes,
        "counter_changes": all_counter_changes,
        "terrain_patterns": {
            maa_type: {
                terrain: {
                    stat: {
                        "mean_delta": statistics.mean([c["delta"] for c in changes]),
                        "samples": len(changes),
                    }
                    for stat, changes in stats.items()
                }
                for terrain, stats in terrains.items()
            }
            for maa_type, terrains in terrain_patterns.items()
        }
    }
    
    output_path = OUTPUT_PATH / "kgd_maa_patterns_v3.json"
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nFull analysis saved to: {output_path}")
    
    print("\n" + "=" * 70)
    print("Analysis complete!")


if __name__ == "__main__":
    main()
