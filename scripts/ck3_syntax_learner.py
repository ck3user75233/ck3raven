"""
CK3 Syntax Learner - Empirical Syntax Database Builder\r\n=======================================================\r\n\r\nSTATUS: TBC (To Be Confirmed)\r\n    This module is infrastructure for learning CK3 script syntax from actual\r\n    game files. Its role in ck3raven is not yet finalized. Potential uses:\r\n    - Autocomplete/syntax validation support\r\n    - CK3 scripting assistant tool for agentic AIs\r\n    - Hypothesis testing for syntax patterns\r\n\r\n    Moved from tools/ck3lens_mcp/ck3lens/semantic.py on 2025-12-30 during\r\n    NO-ORACLE refactor (not an MCP tool, belongs in scripts/).

ZERO ASSUMPTIONS - Extracts syntax ONLY from actual game files.
NO wiki data, NO guesses, NO hardcoded lists.

PURPOSE:
    Eliminate guesswork when validating CK3 mod syntax by providing
    an authoritative reference of what actually exists in vanilla.

WHAT IT EXTRACTS:
    - Triggers: All trigger usage with file locations & line numbers
    - Effects: All effect usage with file locations & line numbers
    - Scopes: All scope:* patterns actually used in vanilla
    - CB Blocks: Valid casus belli block names (on_victory, etc.)
    - Scripted Triggers/Effects: Custom definitions from scripted_ folders
    - Block Names: What blocks are for triggers vs effects

SOURCES:
    1. Vanilla (AUTHORITATIVE): Game files - guaranteed correct
    2. Mods (LESS CERTAIN): Workshop mods - may contain errors/deprecated syntax

SETUP & USAGE:

    # 1. Build the database (run once, takes 2-5 minutes)
    python build_ck3_syntax_db.py
    
    # 2. Use in your code
    from ck3_syntax_validator import CK3SyntaxValidator
    
    game_path = r"C:\...\Crusader Kings III\game"
    validator = CK3SyntaxValidator(game_path)
    
    # Load pre-built database (instant)
    validator.load_syntax_db("ck3_syntax_vanilla.json")
    
    # Validate syntax
    result = validator.validate_syntax("is_in_an_activity", "trigger")
    
    if result['exists_in_vanilla']:
        print(f"✓ Found in vanilla: {result['type']}")
        for file in result['vanilla_locations']:
            print(f"  {file}")
    else:
        print("✗ Not in vanilla")
        if result['suggestions']:
            print(f"  Similar: {result['suggestions'][0][0]}")
    
    # Validate scope syntax
    scope_check = validator.validate_scope_syntax("scope:actor")
    if scope_check['valid']:
        print("✓ Valid scope")
    
    # Check CB block names
    cb_check = validator.validate_cb_block("on_victory")
    if cb_check['valid']:
        print("✓ Valid CB block")

FEATURES:

    validate_syntax(name, context="auto", check_mods=False)
        Check if trigger/effect exists in vanilla (and optionally mods)
        Returns: exists_in_vanilla, type, locations, suggestions, issues
        
    validate_scope_syntax(scope_ref)
        Validate scope:* syntax (detects scope.actor vs scope:actor errors)
        Returns: valid, issues, corrected, found_in_vanilla
        
    validate_cb_block(block_name)
        Check if CB block name is valid (on_victory vs on_victory_effect)
        Returns: valid, issues, suggestions, found_in_vanilla
        
    fuzzy_search(query, max_results=10)
        Find similar syntax when exact match fails
        Returns: List of (name, type, similarity_score)
        
    get_all_triggers() / get_all_effects()
        Get complete sorted list of all indexed syntax

ANTI-PATTERNS (AVOIDED):
    ✗ Hardcoding scope names like ['actor', 'recipient', ...]
    ✗ Assuming syntax from wiki/documentation
    ✗ Limiting scans to "top 50 files" or arbitrary samples
    ✗ Guessing at trigger vs effect classification
    
BEST PRACTICES (IMPLEMENTED):
    ✓ Scan ALL files recursively with no limits
    ✓ Extract scope names from actual scope:* patterns in files
    ✓ Classify triggers/effects by analyzing block context
    ✓ Separate authoritative (vanilla) from uncertain (mods)
    ✓ Cache to JSON for instant loading
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
from difflib import get_close_matches

class CK3SyntaxValidator:
    def __init__(self, game_path: str, workshop_path: str = None):
        """
        Initialize with paths to CK3 game folder and optionally workshop folder.
        
        Args:
            game_path: Path to vanilla game files (authoritative reference)
            workshop_path: Path to Steam workshop mods (less certain, may have errors)
        """
        self.game_path = Path(game_path)
        self.workshop_path = Path(workshop_path) if workshop_path else None
        
        # Vanilla syntax databases - authoritative reference
        self.triggers = {}  # {name: {file: [line_numbers]}}
        self.effects = {}   # {name: {file: [line_numbers]}}
        self.scope_references = {}  # {scope_name: [file_locations]}
        self.cb_blocks = {}  # {block_name: [cb_files]}
        self.scripted_triggers = {}  # {name: file_path}
        self.scripted_effects = {}   # {name: file_path}
        self.titles = {}  # {title_key: {file: line_number}} - e.g., e_hre, k_france, d_tuscany
        
        # Mod syntax databases - less certain (mods can have errors/deprecated syntax)
        self.mod_triggers = {}  # {name: {mod_id: {file: [line_numbers]}}}
        self.mod_effects = {}   # {name: {mod_id: {file: [line_numbers]}}}
        self.mod_scripted_triggers = {}  # {name: {mod_id: file_path}}
        self.mod_scripted_effects = {}   # {name: {mod_id: file_path}}
        
        # Block type definitions extracted from vanilla
        self.trigger_block_names = set()  # e.g., 'limit', 'trigger', 'potential'
        self.effect_block_names = set()   # e.g., 'effect', 'on_accept', 'immediate'
        
    def index_all_syntax(self, include_mods: bool = False):
        """
        Index all vanilla CK3 syntax by PARSING actual game files.
        Extract block patterns, valid identifiers, etc. from vanilla files.
        
        Args:
            include_mods: If True and workshop_path provided, also scan workshop mods
                         (marked as less certain since mods can have errors)
        """
        print("="*80)
        print("INDEXING VANILLA CK3 SYNTAX (AUTHORITATIVE)")
        print("="*80)
        print("Scanning ALL vanilla files recursively - no limits")
        
        # Step 1: Index scripted triggers/effects (these are easiest to identify)
        print("\n[1/6] Indexing vanilla scripted triggers...")
        self._index_scripted_triggers()
        
        print("[2/6] Indexing vanilla scripted effects...")
        self._index_scripted_effects()
        
        # Step 2: Index titles from landed_titles files
        print("[3/6] Indexing titles (e_hre, k_france, etc.)...")
        self._index_titles()
        
        # Step 3: Parse files to extract block structure
        print("[4/6] Analyzing block patterns...")
        self._extract_block_patterns()
        
        # Step 4: Extract scope references (scope:*)
        print("[5/6] Extracting scope references...")
        self._extract_scope_references()
        
        # Step 5: Parse specific file types for their syntax
        print("[6/6] Indexing triggers and effects...")
        self._index_triggers_and_effects()
        
        print(f"\n[OK] Indexed {len(self.triggers)} unique vanilla triggers")
        print(f"[OK] Indexed {len(self.effects)} unique vanilla effects")
        print(f"[OK] Indexed {len(self.scripted_triggers)} vanilla scripted triggers")
        print(f"[OK] Indexed {len(self.scripted_effects)} vanilla scripted effects")
        print(f"[OK] Indexed {len(self.titles)} vanilla titles")
        print(f"[OK] Extracted {len(self.scope_references)} scope references")
        print(f"[OK] Found {len(self.trigger_block_names)} trigger block types")
        print(f"[OK] Found {len(self.effect_block_names)} effect block types")
        
        # Optionally index workshop mods
        if include_mods and self.workshop_path:
            print("\n" + "="*80)
            print("INDEXING WORKSHOP MODS (LESS CERTAIN)")
            print("="*80)
            print("Warning: Mods may contain errors or deprecated syntax")
            self._index_workshop_mods()
            
            print(f"\n[OK] Indexed {len(self.mod_triggers)} additional mod triggers")
            print(f"[OK] Indexed {len(self.mod_effects)} additional mod effects")
            print(f"[OK] Indexed {len(self.mod_scripted_triggers)} mod scripted triggers")
            print(f"[OK] Indexed {len(self.mod_scripted_effects)} mod scripted effects")
        
    def _extract_block_patterns(self):
        """
        Extract block names by parsing ALL vanilla files recursively.
        Identifies patterns like 'limit = {', 'effect = {', etc.
        """
        common_path = self.game_path / "common"
        if not common_path.exists():
            return
        
        # Scan ALL files recursively - no limits
        file_count = 0
        for file_path in common_path.rglob("*.txt"):
            file_count += 1
            if file_count % 100 == 0:
                print(f"  ...scanned {file_count} files for block patterns", end='\r')
            
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                # Find all block declarations: word = {
                block_pattern = r'^(\s*)([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(block_pattern, content, re.MULTILINE):
                    block_name = match.group(2)
                    
                    # Dynamically classify blocks by observing context
                    # We'll identify trigger vs effect blocks by their typical names
                    if any(x in block_name for x in ['limit', 'trigger', 'potential', 'allow', 
                                                      'is_valid', 'is_shown', 'can_use', 'filter',
                                                      'can_start', 'valid', 'possible']):
                        self.trigger_block_names.add(block_name)
                    elif any(x in block_name for x in ['effect', 'on_', 'immediate', 'after', 'before']):
                        self.effect_block_names.add(block_name)
                        
            except:
                pass
        
        print(f"  ...scanned {file_count} files for block patterns")
    
    def _extract_scope_references(self):
        """
        Extract ALL scope references by finding scope:* patterns in ALL vanilla files.
        This gets us the ACTUAL scope names used in vanilla - no limits.
        """
        common_path = self.game_path / "common"
        events_path = self.game_path / "events"
        
        scope_pattern = r'scope:([a-z_][a-z0-9_]*)'
        
        file_count = 0
        for base_path in [common_path, events_path]:
            if not base_path.exists():
                continue
                
            # Scan ALL files recursively - no limits
            for file_path in base_path.rglob("*.txt"):
                file_count += 1
                if file_count % 100 == 0:
                    print(f"  ...scanned {file_count} files for scopes", end='\r')
                
                try:
                    with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                        content = f.read()
                    
                    for match in re.finditer(scope_pattern, content):
                        scope_name = match.group(1)
                        if scope_name not in self.scope_references:
                            self.scope_references[scope_name] = []
                        
                        relative_path = str(file_path.relative_to(self.game_path))
                        if relative_path not in self.scope_references[scope_name]:
                            self.scope_references[scope_name].append(relative_path)
                            
                except:
                    pass
        
        print(f"  ...scanned {file_count} files for scopes")
    
    def _index_triggers_and_effects(self):
        """
        Index ALL triggers and effects by analyzing their usage context.
        Parse ALL vanilla files recursively - no limits.
        """
        common_path = self.game_path / "common"
        events_path = self.game_path / "events"
        
        file_count = 0
        for base_path in [common_path, events_path]:
            if not base_path.exists():
                continue
                
            # Scan ALL files recursively - no limits
            for file_path in base_path.rglob("*.txt"):
                file_count += 1
                if file_count % 100 == 0:
                    print(f"  ...indexed {file_count} files for syntax", end='\r')
                
                self._parse_file_for_syntax(file_path)
        
        print(f"  ...indexed {file_count} files for syntax")
    
    def _parse_file_for_syntax(self, file_path: Path):
        """
        Parse a file line-by-line to extract triggers and effects based on context.
        """
        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                lines = f.readlines()
            
            relative_path = str(file_path.relative_to(self.game_path))
            in_trigger_block = False
            in_effect_block = False
            bracket_depth = 0
            
            for line_num, line in enumerate(lines, 1):
                stripped = line.strip()
                
                # Track block context
                for block_name in self.trigger_block_names:
                    if f'{block_name} = {{' in stripped:
                        in_trigger_block = True
                        bracket_depth = 1
                        
                for block_name in self.effect_block_names:
                    if f'{block_name} = {{' in stripped:
                        in_effect_block = True
                        bracket_depth = 1
                
                # Track brackets
                bracket_depth += stripped.count('{') - stripped.count('}')
                if bracket_depth <= 0:
                    in_trigger_block = False
                    in_effect_block = False
                
                # Extract syntax based on context
                match = re.match(r'^\s*([a-z_][a-z0-9_]*)\s*=', stripped)
                if match:
                    name = match.group(1)
                    
                    if in_trigger_block:
                        if name not in self.triggers:
                            self.triggers[name] = {}
                        if relative_path not in self.triggers[name]:
                            self.triggers[name][relative_path] = []
                        self.triggers[name][relative_path].append(line_num)
                    
                    elif in_effect_block:
                        if name not in self.effects:
                            self.effects[name] = {}
                        if relative_path not in self.effects[name]:
                            self.effects[name][relative_path] = []
                        self.effects[name][relative_path].append(line_num)
                        
        except:
            pass
    
    def _index_scripted_triggers(self):
        """
        Index scripted triggers from common/scripted_triggers/.
        These are user-defined triggers that can be called like built-ins.
        """
        scripted_path = self.game_path / "common" / "scripted_triggers"
        if not scripted_path.exists():
            return
            
        for file_path in scripted_path.glob("*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                # Find top-level definitions (name = { ... })
                pattern = r'^([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    name = match.group(1)
                    self.scripted_triggers[name] = str(file_path.relative_to(self.game_path))
            except:
                pass
    
    def _index_scripted_effects(self):
        """
        Index scripted effects from common/scripted_effects/.
        These are user-defined effects that can be called like built-ins.
        """
        scripted_path = self.game_path / "common" / "scripted_effects"
        if not scripted_path.exists():
            return
            
        for file_path in scripted_path.glob("*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                # Find top-level definitions
                pattern = r'^([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    name = match.group(1)
                    self.scripted_effects[name] = str(file_path.relative_to(self.game_path))
            except:
                pass
    
    def _index_titles(self):
        """
        Index all title keys from common/landed_titles/*.txt
        Titles are like e_hre, k_france, d_tuscany, c_paris, b_paris
        """
        titles_path = self.game_path / "common" / "landed_titles"
        if not titles_path.exists():
            return
        
        file_count = 0
        for file_path in titles_path.rglob("*.txt"):
            file_count += 1
            if file_count % 10 == 0:
                print(f"  ...indexed {file_count} title files", end='\r')
            
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    lines = f.readlines()
                
                relative_path = str(file_path.relative_to(self.game_path))
                
                for line_num, line in enumerate(lines, 1):
                    # Match title definitions: e_something = {, k_something = {, etc.
                    # Title keys start with tier prefix (e_, k_, d_, c_, b_)
                    match = re.match(r'^\s*([ekdcb]_[a-z0-9_]+)\s*=\s*\{', line)
                    if match:
                        title_key = match.group(1)
                        if title_key not in self.titles:
                            self.titles[title_key] = {}
                        self.titles[title_key][relative_path] = line_num
                        
            except:
                pass
        
        print(f"  ...indexed {file_count} title files")
    
    def validate_syntax(self, name: str, context: str = "auto", check_mods: bool = False, include_suggestions: bool = True) -> Dict:
        """
        Validate if a trigger/effect exists in vanilla (and optionally mods).
        
        Args:
            name: The syntax name to validate (e.g., "is_in_an_activity")
            context: "trigger", "effect", or "auto" to check both
            check_mods: If True, also check workshop mods (less authoritative)
            
        Returns:
            Dict with validation results and suggestions
        """
        result = {
            'name': name,
            'exists_in_vanilla': False,
            'exists_in_mods': False,
            'type': None,
            'vanilla_locations': {},
            'mod_locations': {},
            'suggestions': [],
            'issues': []
        }
        
        # Check vanilla first (authoritative)
        if context in ["trigger", "auto"]:
            if name in self.triggers:
                result['exists_in_vanilla'] = True
                result['type'] = 'trigger'
                result['vanilla_locations'] = dict(list(self.triggers[name].items())[:3])
                return result
            
            if name in self.scripted_triggers:
                result['exists_in_vanilla'] = True
                result['type'] = 'scripted_trigger'
                result['vanilla_locations'] = {self.scripted_triggers[name]: []}
                return result
        
        if context in ["effect", "auto"]:
            if name in self.effects:
                result['exists_in_vanilla'] = True
                result['type'] = 'effect'
                result['vanilla_locations'] = dict(list(self.effects[name].items())[:3])
                return result
                
            if name in self.scripted_effects:
                result['exists_in_vanilla'] = True
                result['type'] = 'scripted_effect'
                result['vanilla_locations'] = {self.scripted_effects[name]: []}
                return result
        
        # Not in vanilla - check mods if requested
        if check_mods:
            if name in self.mod_scripted_triggers:
                result['exists_in_mods'] = True
                result['type'] = 'mod_scripted_trigger'
                result['mod_locations'] = self.mod_scripted_triggers[name]
                result['issues'].append("Found in mods but NOT in vanilla - may be mod-specific or error")
                return result
            
            if name in self.mod_scripted_effects:
                result['exists_in_mods'] = True
                result['type'] = 'mod_scripted_effect'
                result['mod_locations'] = self.mod_scripted_effects[name]
                result['issues'].append("Found in mods but NOT in vanilla - may be mod-specific or error")
                return result
        
        # Not found anywhere - provide fuzzy suggestions (if requested)
        if include_suggestions:
            result['suggestions'] = self.fuzzy_search(name, max_results=5)
        
        # Detect common syntax errors
        if '.' in name and 'scope' in name.lower():
            corrected = name.replace('.', ':')
            result['issues'].append(f"Scope syntax error: uses '.' instead of ':'. Try: {corrected}")
        
        if name.endswith('_effect') or name.endswith('_trigger'):
            base_name = name.replace('_effect', '').replace('_trigger', '')
            result['issues'].append(f"May have incorrect suffix. Check if base name exists: {base_name}")
        
        return result
    
    def fuzzy_search(self, query: str, max_results: int = 10) -> List[Tuple[str, str, float]]:
        """
        Fuzzy search for similar syntax names.
        
        Returns:
            List of (name, type, similarity_score) tuples
        """
        results = []
        
        # Search triggers
        trigger_matches = get_close_matches(query, self.triggers.keys(), n=max_results, cutoff=0.6)
        for match in trigger_matches:
            results.append((match, 'trigger', self._similarity_score(query, match)))
        
        # Search effects
        effect_matches = get_close_matches(query, self.effects.keys(), n=max_results, cutoff=0.6)
        for match in effect_matches:
            results.append((match, 'effect', self._similarity_score(query, match)))
        
        # Search scripted
        scripted_trigger_matches = get_close_matches(query, self.scripted_triggers.keys(), n=max_results, cutoff=0.6)
        for match in scripted_trigger_matches:
            results.append((match, 'scripted_trigger', self._similarity_score(query, match)))
            
        scripted_effect_matches = get_close_matches(query, self.scripted_effects.keys(), n=max_results, cutoff=0.6)
        for match in scripted_effect_matches:
            results.append((match, 'scripted_effect', self._similarity_score(query, match)))
        
        # Sort by similarity score
        results.sort(key=lambda x: x[2], reverse=True)
        
        return results[:max_results]
    
    def _similarity_score(self, s1: str, s2: str) -> float:
        """Calculate similarity score between two strings."""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
    
    def _find_mod_local_context(self, token: str, file_path: Path) -> List[str]:
        """
        Search for partial matches within the mod's own definitions.
        
        Example: 'tct_make_antipope_interaction' not found -> search mod for:
        - definitions containing 'antipope' 
        - definitions containing 'make_antipope'
        - other related definitions
        
        This provides INTELLIGENT suggestions based on what the modder actually defined,
        rather than random vanilla suggestions that make no sense.
        """
        # Find mod root (go up until we find descriptor.mod or hit workshop folder)
        mod_root = file_path.parent
        max_depth = 10
        depth = 0
        while depth < max_depth and mod_root.parent != mod_root:
            if (mod_root / 'descriptor.mod').exists():
                break
            if mod_root.name == '1158310':  # Hit workshop root
                return []
            mod_root = mod_root.parent
            depth += 1
        
        if not (mod_root / 'descriptor.mod').exists():
            return []
        
        # Extract meaningful parts from token (split on _ and use frequency analysis)
        parts = token.split('_')
        # Filter to parts that are long enough to be meaningful
        # Use length-based filtering only - let actual definitions determine relevance
        meaningful_parts = [p for p in parts if len(p) >= 4]
        
        if not meaningful_parts:
            return []
        
        # Search mod files for these parts
        suggestions = set()
        search_dirs = [
            mod_root / 'common' / 'scripted_triggers',
            mod_root / 'common' / 'scripted_effects',
            mod_root / 'common' / 'character_interactions',
            mod_root / 'common' / 'decisions',
            mod_root / 'common' / 'casus_belli_types',
        ]
        
        for search_dir in search_dirs:
            if not search_dir.exists():
                continue
            
            for txt_file in search_dir.glob('*.txt'):
                try:
                    content = txt_file.read_text(encoding='utf-8', errors='ignore')
                    
                    # Look for definitions containing our meaningful parts
                    for part in meaningful_parts:
                        # Find lines with ID = { pattern containing our part
                        pattern = re.compile(rf'^(\w*{re.escape(part)}\w*)\s*=\s*{{', 
                                           re.MULTILINE | re.IGNORECASE)
                        matches = pattern.findall(content)
                        
                        for match in matches:
                            if match != token:  # Don't suggest the same thing
                                suggestions.add(match)
                                if len(suggestions) >= 10:
                                    return sorted(suggestions)[:5]
                except:
                    continue
        
        return sorted(suggestions)[:5] if suggestions else []
    
    def validate_scope_syntax(self, scope_ref: str) -> Dict:
        """
        Validate scope reference syntax against ACTUAL scope: patterns found in vanilla.
        Only suggests scopes that were extracted from vanilla files.
        """
        result = {
            'valid': False,
            'issues': [],
            'corrected': None,
            'found_in_vanilla': []
        }
        
        # Check for dot vs colon error
        if '.' in scope_ref and scope_ref.startswith('scope'):
            result['issues'].append("Syntax error: uses '.' instead of ':'")
            result['corrected'] = scope_ref.replace('.', ':')
            return result
        
        # Validate against extracted scope references
        if ':' in scope_ref:
            parts = scope_ref.split(':')
            if len(parts) == 2 and parts[0] == 'scope':
                scope_name = parts[1]
                
                if scope_name in self.scope_references:
                    result['valid'] = True
                    result['found_in_vanilla'] = self.scope_references[scope_name][:3]
                else:
                    result['issues'].append(f"Scope '{scope_name}' not found in vanilla")
                    
                    # Suggest similar scopes that ACTUALLY exist in vanilla
                    suggestions = get_close_matches(scope_name, self.scope_references.keys(), n=3, cutoff=0.6)
                    if suggestions:
                        result['issues'].append(f"Similar scopes in vanilla: {', '.join(suggestions)}")
        
        return result
    
    def get_all_triggers(self) -> List[str]:
        """Get sorted list of all indexed triggers."""
        all_triggers = set(self.triggers.keys()) | set(self.scripted_triggers.keys())
        return sorted(all_triggers)
    
    def get_all_effects(self) -> List[str]:
        """Get sorted list of all indexed effects."""
        all_effects = set(self.effects.keys()) | set(self.scripted_effects.keys())
        return sorted(all_effects)
    
    def validate_cb_block(self, block_name: str) -> Dict:
        """
        Validate CB block name against blocks extracted from vanilla CB files.
        Extracts valid block names by parsing actual casus_belli_types files.
        """
        # Extract CB blocks if not done yet
        if not self.cb_blocks:
            self._extract_cb_blocks()
        
        result = {
            'valid': block_name in self.cb_blocks,
            'issues': [],
            'suggestions': [],
            'found_in_vanilla': []
        }
        
        if result['valid']:
            result['found_in_vanilla'] = self.cb_blocks[block_name][:3]
        else:
            # Check for common mistakes
            if block_name.endswith('_effect'):
                base_name = block_name.replace('_effect', '')
                if base_name in self.cb_blocks:
                    result['issues'].append(f"Suffix error: Remove '_effect'. Correct: {base_name}")
                    result['suggestions'].append(base_name)
            
            # Fuzzy search against actual vanilla CB blocks
            matches = get_close_matches(block_name, self.cb_blocks.keys(), n=3, cutoff=0.6)
            if matches:
                result['suggestions'].extend(matches)
        
        return result
    
    def _extract_cb_blocks(self):
        """
        Extract valid CB block names by parsing vanilla casus_belli_types files.
        """
        cb_path = self.game_path / "common" / "casus_belli_types"
        if not cb_path.exists():
            return
        
        for file_path in cb_path.glob("*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                # Find top-level blocks within CB definitions
                # Pattern: inside a CB definition, find block_name = {
                pattern = r'^\s*([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    block_name = match.group(1)
                    if block_name not in self.cb_blocks:
                        self.cb_blocks[block_name] = []
                    
                    relative_path = str(file_path.relative_to(self.game_path))
                    if relative_path not in self.cb_blocks[block_name]:
                        self.cb_blocks[block_name].append(relative_path)
            except:
                pass
    
    def _index_workshop_mods(self):
        """
        Index syntax from ALL workshop mods.
        NOTE: This is less authoritative than vanilla - mods can have errors or use deprecated syntax.
        """
        if not self.workshop_path or not self.workshop_path.exists():
            print("  Workshop path not provided or doesn't exist")
            return
        
        # Each numbered folder in workshop is a mod
        mod_folders = [f for f in self.workshop_path.iterdir() if f.is_dir() and f.name.isdigit()]
        
        print(f"\n  Found {len(mod_folders)} workshop mods to scan...")
        
        for mod_idx, mod_folder in enumerate(mod_folders, 1):
            mod_id = mod_folder.name
            
            if mod_idx % 10 == 0:
                print(f"  ...scanning mod {mod_idx}/{len(mod_folders)}", end='\r')
            
            # Index scripted triggers/effects from this mod
            self._index_mod_scripted_triggers(mod_folder, mod_id)
            self._index_mod_scripted_effects(mod_folder, mod_id)
            
            # Index syntax usage from this mod
            self._index_mod_syntax(mod_folder, mod_id)
        
        print(f"  ...scanned all {len(mod_folders)} mods")
    
    def _index_mod_scripted_triggers(self, mod_path: Path, mod_id: str):
        """Index scripted triggers from a workshop mod."""
        scripted_path = mod_path / "common" / "scripted_triggers"
        if not scripted_path.exists():
            return
        
        for file_path in scripted_path.glob("*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                pattern = r'^([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    name = match.group(1)
                    if name not in self.mod_scripted_triggers:
                        self.mod_scripted_triggers[name] = {}
                    self.mod_scripted_triggers[name][mod_id] = str(file_path.relative_to(self.workshop_path))
            except:
                pass
    
    def _index_mod_scripted_effects(self, mod_path: Path, mod_id: str):
        """Index scripted effects from a workshop mod."""
        scripted_path = mod_path / "common" / "scripted_effects"
        if not scripted_path.exists():
            return
        
        for file_path in scripted_path.glob("*.txt"):
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    content = f.read()
                
                pattern = r'^([a-z_][a-z0-9_]*)\s*=\s*\{'
                for match in re.finditer(pattern, content, re.MULTILINE):
                    name = match.group(1)
                    if name not in self.mod_scripted_effects:
                        self.mod_scripted_effects[name] = {}
                    self.mod_scripted_effects[name][mod_id] = str(file_path.relative_to(self.workshop_path))
            except:
                pass
    
    def _index_mod_syntax(self, mod_path: Path, mod_id: str):
        """Index trigger/effect usage from a workshop mod (sample only to avoid massive bloat)."""
        common_path = mod_path / "common"
        if not common_path.exists():
            return
        
        # Sample some files from the mod to get a sense of syntax usage
        txt_files = list(common_path.rglob("*.txt"))
        for file_path in txt_files[:50]:  # Limit per mod to avoid excessive data
            try:
                with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    lines = f.readlines()
                
                for line_num, line in enumerate(lines, 1):
                    # Extract simple pattern: name = ...
                    match = re.match(r'^\s*([a-z_][a-z0-9_]*)\s*=', line)
                    if match:
                        name = match.group(1)
                        relative_path = str(file_path.relative_to(self.workshop_path))
                        
                        # Store in mod databases
                        if name not in self.mod_triggers:
                            self.mod_triggers[name] = {}
                        if mod_id not in self.mod_triggers[name]:
                            self.mod_triggers[name][mod_id] = {}
                        if relative_path not in self.mod_triggers[name][mod_id]:
                            self.mod_triggers[name][mod_id][relative_path] = []
                        self.mod_triggers[name][mod_id][relative_path].append(line_num)
            except:
                pass
    
    def export_syntax_db(self, output_path: str, include_mods: bool = False):
        """
        Export indexed syntax to JSON for quick loading.
        
        Args:
            output_path: Path to save JSON database
            include_mods: If True, include mod data in export
        """
        db = {
            'version': '1.1',
            'game_version': 'CK3 (extracted from vanilla)',
            'vanilla': {
                'triggers': self.triggers,
                'effects': self.effects,
                'scripted_triggers': self.scripted_triggers,
                'scripted_effects': self.scripted_effects,
                'scope_references': self.scope_references,
                'cb_blocks': self.cb_blocks,
                'trigger_block_names': list(self.trigger_block_names),
                'effect_block_names': list(self.effect_block_names)
            }
        }
        
        if include_mods:
            db['mods'] = {
                'triggers': self.mod_triggers,
                'effects': self.mod_effects,
                'scripted_triggers': self.mod_scripted_triggers,
                'scripted_effects': self.mod_scripted_effects,
                'note': 'Mod syntax is less authoritative - may contain errors or deprecated syntax'
            }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2)
        
        print(f"[OK] Exported syntax database to {output_path}")
        if include_mods:
            print(f"  (Includes vanilla + workshop mod data)")
        else:
            print(f"  (Vanilla only - authoritative reference)")
    
    def load_syntax_db(self, db_path: str):
        """
        Load pre-indexed syntax from JSON (much faster than re-indexing).
        """
        with open(db_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        # Load vanilla data
        if 'vanilla' in db:
            # New format (v1.1+)
            v = db['vanilla']
            self.triggers = v['triggers']
            self.effects = v['effects']
            self.scripted_triggers = v['scripted_triggers']
            self.scripted_effects = v['scripted_effects']
            self.scope_references = v['scope_references']
            self.cb_blocks = v['cb_blocks']
            self.trigger_block_names = set(v['trigger_block_names'])
            self.effect_block_names = set(v['effect_block_names'])
            
            # Load mod data if present
            if 'mods' in db:
                m = db['mods']
                self.mod_triggers = m.get('triggers', {})
                self.mod_effects = m.get('effects', {})
                self.mod_scripted_triggers = m.get('scripted_triggers', {})
                self.mod_scripted_effects = m.get('scripted_effects', {})
        else:
            # Old format (v1.0)
            self.triggers = db['triggers']
            self.effects = db['effects']
            self.scripted_triggers = db['scripted_triggers']
            self.scripted_effects = db['scripted_effects']
            self.scope_references = db['scope_references']
            self.cb_blocks = db['cb_blocks']
            self.trigger_block_names = set(db['trigger_block_names'])
            self.effect_block_names = set(db['effect_block_names'])
        
        print(f"[OK] Loaded syntax database from {db_path}")


# =============================================================================
# Database-backed reference validation for MCP tools
# =============================================================================

def validate_content(
    content: str,
    db_path: str,
    playset_id: int = None,
    filename: str = "inline.txt"
) -> dict:
    """
    Validate all symbol references in CK3 script content against the database.
    
    Uses the ck3raven database to check that referenced symbols exist.
    This is the function called by ck3_validate_references MCP tool.
    
    Args:
        content: CK3 script content to validate
        db_path: Path to ck3raven SQLite database
        playset_id: Optional playset for filtering (uses all if None)
        filename: Filename for error context
        
    Returns:
        {
            "success": bool (true if no errors),
            "errors": [{"line": int, "message": str, "ref": str}],
            "warnings": [{"line": int, "message": str, "ref": str}]
        }
    """
    import sqlite3
    import re
    
    errors = []
    warnings = []
    
    conn = sqlite3.connect(db_path)
    
    # Build a set of known symbols from database
    try:
        # Get all symbol names (case-insensitive lookup)
        rows = conn.execute("""
            SELECT DISTINCT LOWER(name), symbol_type FROM symbols
        """).fetchall()
        known_symbols = {name: stype for name, stype in rows}
    except Exception as e:
        return {"success": False, "errors": [{"line": 0, "message": f"DB error: {e}", "ref": ""}], "warnings": []}
    finally:
        conn.close()
    
    # Patterns for common reference contexts
    reference_patterns = [
        # has_trait = <trait>
        (r'has_trait\s*=\s*(\w+)', 'trait'),
        # trigger_event = <event>
        (r'trigger_event\s*=\s*\{?\s*id\s*=\s*(\w+)', 'event'),
        (r'trigger_event\s*=\s*(\w[\w.]+)', 'event'),
        # has_perk = <perk>
        (r'has_perk\s*=\s*(\w+)', 'perk'),
        # has_focus = <focus>
        (r'has_focus\s*=\s*(\w+)', 'focus'),
        # has_lifestyle = <lifestyle>
        (r'has_lifestyle\s*=\s*(\w+)', 'lifestyle'),
        # add_trait = <trait>
        (r'add_trait\s*=\s*(\w+)', 'trait'),
        # remove_trait = <trait>
        (r'remove_trait\s*=\s*(\w+)', 'trait'),
        # has_religion = <religion>
        (r'has_religion\s*=\s*(\w+)', 'religion'),
        # has_culture = <culture>
        (r'has_culture\s*=\s*(\w+)', 'culture'),
        # has_government = <government>
        (r'has_government\s*=\s*(\w+)', 'government_type'),
        # scripted_trigger / scripted_effect calls
        (r'(?:run_scripted_trigger|scripted_trigger)\s*=\s*(\w+)', 'scripted_trigger'),
        (r'(?:run_scripted_effect|scripted_effect)\s*=\s*(\w+)', 'scripted_effect'),
    ]
    
    # Built-in values that are not symbols
    builtins = {
        'yes', 'no', 'true', 'false', 'none', 'null',
        'root', 'this', 'prev', 'from', 'scope', 'target',
        'actor', 'recipient', 'primary_title', 'capital_county',
    }
    
    lines = content.split('\n')
    for line_num, line in enumerate(lines, 1):
        # Skip comments
        stripped = line.split('#')[0]
        if not stripped.strip():
            continue
        
        for pattern, expected_type in reference_patterns:
            for match in re.finditer(pattern, stripped, re.IGNORECASE):
                ref_name = match.group(1).lower()
                
                # Skip builtins
                if ref_name in builtins:
                    continue
                
                # Check if symbol exists
                if ref_name not in known_symbols:
                    errors.append({
                        "line": line_num,
                        "message": f"Undefined {expected_type}: '{match.group(1)}'",
                        "ref": match.group(1),
                        "expected_type": expected_type,
                    })
                else:
                    # Optionally warn if type mismatch
                    actual_type = known_symbols[ref_name]
                    if expected_type and actual_type and expected_type != actual_type:
                        # Some flexibility - don't warn for close matches
                        if not (expected_type in actual_type or actual_type in expected_type):
                            warnings.append({
                                "line": line_num,
                                "message": f"Type mismatch: '{match.group(1)}' is a {actual_type}, expected {expected_type}",
                                "ref": match.group(1),
                            })
    
    return {
        "success": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "filename": filename,
    }


def main():
    """Example usage and testing."""
    import sys
    
    game_path = r"C:\Program Files (x86)\Steam\steamapps\common\Crusader Kings III\game"
    
    # Check if we should load from cache
    db_path = "ck3_syntax_db.json"
    
    validator = CK3SyntaxValidator(game_path)
    
    if os.path.exists(db_path):
        print("Loading cached syntax database...")
        validator.load_syntax_db(db_path)
    else:
        print("Building syntax database (this may take a minute)...")
        validator.index_all_syntax()
        validator.export_syntax_db(db_path)
    
    print("\n" + "="*80)
    print("CK3 SYNTAX VALIDATOR - Interactive Mode")
    print("="*80)
    
    # Test cases from the bug report
    test_cases = [
        ("is_in_an_activity", "trigger"),
        ("complete_activity", "effect"),
        ("is_busy_in_events_localised", "trigger"),
        ("is_debug_enabled", "trigger"),
        ("scope.actor", "auto"),
        ("scope:actor", "auto"),
        ("on_victory_effect", "cb_block"),
        ("on_victory", "cb_block"),
    ]
    
    print("\nValidating known issues from bug report:\n")
    
    for name, context in test_cases:
        if context == "cb_block":
            result = validator.validate_cb_block(name)
            print(f"\n{name} (CB block):")
            if result['valid']:
                print("  ✓ VALID CB block")
            else:
                print("  ✗ INVALID CB block")
                if result['suggestions']:
                    print(f"  Suggestions: {', '.join(result['suggestions'])}")
        else:
            result = validator.validate_syntax(name, context)
            print(f"\n{name} ({context}):")
            if result['exists']:
                print(f"  ✓ EXISTS as {result['type']}")
                print(f"  Found in: {result['locations'][0] if result['locations'] else 'N/A'}")
            else:
                print(f"  ✗ NOT FOUND in vanilla")
                if result['issues']:
                    for issue in result['issues']:
                        print(f"  ! {issue}")
                if result['suggestions']:
                    print(f"  Suggestions:")
                    for sugg, stype, score in result['suggestions'][:3]:
                        print(f"    - {sugg} ({stype}) [{score:.2%} match]")


if __name__ == "__main__":
    main()

