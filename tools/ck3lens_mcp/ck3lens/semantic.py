"""
Semantic Analysis Module

Provides reference validation, autocomplete, and hover documentation
by analyzing parsed AST against the symbol database.

Phase 1 Implementation:
- Reference validation (undefined symbol detection)
- Autocomplete suggestions
- Hover documentation
- Scope context awareness
"""
from __future__ import annotations
import sqlite3
import sys
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any, Set, Tuple
from enum import Enum

# Add ck3raven to path if not installed
CK3RAVEN_PATH = Path(__file__).parent.parent.parent.parent / "src"
if CK3RAVEN_PATH.exists():
    sys.path.insert(0, str(CK3RAVEN_PATH))


# =============================================================================
# SCOPE TYPES - What scope are we currently in?
# =============================================================================

class ScopeType(Enum):
    """CK3 scope types for context-aware validation."""
    CHARACTER = "character"
    TITLE = "title"
    PROVINCE = "province"
    CULTURE = "culture"
    FAITH = "faith"
    RELIGION = "religion"
    DYNASTY = "dynasty"
    HOUSE = "house"
    ARTIFACT = "artifact"
    SCHEME = "scheme"
    ACTIVITY = "activity"
    ARMY = "army"
    COMBAT = "combat"
    STORY = "story"
    SECRET = "secret"
    NONE = "none"
    ANY = "any"  # Fallback


# Keys that define scope context
SCOPE_CHANGERS = {
    # Character scopes
    'root': ScopeType.CHARACTER,
    'this': ScopeType.ANY,
    'prev': ScopeType.ANY,
    'from': ScopeType.ANY,
    'liege': ScopeType.CHARACTER,
    'holder': ScopeType.CHARACTER,
    'host': ScopeType.CHARACTER,
    'killer': ScopeType.CHARACTER,
    'father': ScopeType.CHARACTER,
    'mother': ScopeType.CHARACTER,
    'spouse': ScopeType.CHARACTER,
    'primary_spouse': ScopeType.CHARACTER,
    'betrothed': ScopeType.CHARACTER,
    'player_heir': ScopeType.CHARACTER,
    'designated_heir': ScopeType.CHARACTER,
    'vassal': ScopeType.CHARACTER,
    
    # Title scopes
    'primary_title': ScopeType.TITLE,
    'title': ScopeType.TITLE,
    'capital_county': ScopeType.TITLE,
    'de_jure_liege': ScopeType.TITLE,
    
    # Province/location
    'capital_province': ScopeType.PROVINCE,
    'location': ScopeType.PROVINCE,
    'barony': ScopeType.TITLE,
    'county': ScopeType.TITLE,
    'duchy': ScopeType.TITLE,
    'kingdom': ScopeType.TITLE,
    'empire': ScopeType.TITLE,
    
    # Culture & Faith
    'culture': ScopeType.CULTURE,
    'faith': ScopeType.FAITH,
    'religion': ScopeType.RELIGION,
    
    # Dynasty/House
    'dynasty': ScopeType.DYNASTY,
    'house': ScopeType.HOUSE,
    
    # Objects
    'artifact': ScopeType.ARTIFACT,
    'scheme': ScopeType.SCHEME,
    'activity': ScopeType.ACTIVITY,
}


# =============================================================================
# REFERENCE KEYS - What type does this key reference?
# =============================================================================

REFERENCE_KEY_TYPES = {
    # Traits
    'has_trait': 'trait',
    'add_trait': 'trait',
    'remove_trait': 'trait',
    'trait': 'trait',
    
    # Perks & Focuses
    'has_perk': 'perk',
    'add_perk': 'perk',
    'perk': 'perk',
    'has_focus': 'focus',
    'set_focus': 'focus',
    'focus': 'focus',
    
    # Culture & Religion
    'has_culture': 'culture',
    'culture': 'culture',
    'has_religion': 'religion',
    'religion': 'religion',
    'faith': 'faith',
    'has_faith': 'faith',
    
    # Traditions & Innovations
    'has_tradition': 'tradition',
    'can_have_tradition': 'tradition',
    'tradition': 'tradition',
    'has_innovation': 'innovation',
    'innovation': 'innovation',
    
    # Government
    'government_type': 'government',
    'has_government': 'government',
    'government': 'government',
    
    # Events
    'trigger_event': 'event',
    'random_events_list': 'event',
    
    # Buildings
    'add_building': 'building',
    'has_building': 'building',
    'building': 'building',
    'has_building_or_higher': 'building',
    
    # Titles
    'title': 'title',
    'has_title': 'title',
    
    # Casus Belli
    'has_cb': 'cb_type',
    'casus_belli': 'cb_type',
    'cb_type': 'cb_type',
    
    # Laws
    'has_law': 'law',
    'add_law': 'law',
    'law': 'law',
    
    # Interactions & Schemes
    'run_interaction': 'interaction',
    'start_scheme': 'scheme',
    'scheme_type': 'scheme',
    
    # Activities
    'has_activity_type': 'activity',
    'activity_type': 'activity',
    'start_activity': 'activity',
    
    # Lifestyle
    'has_lifestyle': 'lifestyle',
    'lifestyle': 'lifestyle',
    
    # Artifacts
    'add_artifact': 'artifact',
    'has_artifact': 'artifact',
    'create_artifact': 'artifact',
    
    # Modifiers
    'add_modifier': 'modifier',
    'has_modifier': 'modifier',
    'remove_modifier': 'modifier',
    'modifier': 'modifier',
    
    # Scripted effects/triggers
    'run_effect': 'scripted_effect',
    'trigger_if': 'scripted_trigger',
    
    # On actions
    'on_action': 'on_action',
    'fire_on_action': 'on_action',
    
    # Decisions
    'decision': 'decision',
    'has_decision': 'decision',
    
    # Dynasty/House
    'dynasty': 'dynasty',
    'house': 'house',
    'dynasty_perk': 'dynasty_perk',
    'has_dynasty_perk': 'dynasty_perk',
}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class Diagnostic:
    """A validation diagnostic (error, warning, info)."""
    line: int
    column: int
    end_line: int
    end_column: int
    severity: str  # "error", "warning", "info", "hint"
    code: str
    message: str
    source: str = "ck3lens"
    related: List[Dict] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompletionItem:
    """An autocomplete suggestion."""
    label: str
    kind: str  # "symbol", "keyword", "snippet", "scope"
    detail: str
    documentation: str
    insert_text: str
    symbol_type: Optional[str] = None
    mod: Optional[str] = None
    sort_text: Optional[str] = None


@dataclass
class HoverInfo:
    """Hover documentation."""
    content: str  # Markdown content
    range: Optional[Dict[str, int]] = None  # {line, column, end_line, end_column}


@dataclass
class SymbolLocation:
    """Location of a symbol definition."""
    file_path: str
    line: int
    column: int = 0
    mod: str = "vanilla"


@dataclass
class ScopeContext:
    """Current scope context for validation."""
    scope_type: ScopeType
    parent_key: Optional[str]
    in_trigger: bool
    in_effect: bool
    depth: int


# =============================================================================
# SEMANTIC ANALYZER
# =============================================================================

class SemanticAnalyzer:
    """
    Analyzes CK3 script for semantic errors, provides autocomplete and hover.
    
    Connects to the ck3raven database for symbol lookup.
    """
    
    def __init__(self, db_path: Path, playset_id: int = 1):
        """
        Initialize analyzer with database connection.
        
        Args:
            db_path: Path to ck3raven.db
            playset_id: Active playset for symbol resolution
        """
        self.db_path = db_path
        self.playset_id = playset_id
        self._conn: Optional[sqlite3.Connection] = None
        self._symbol_cache: Dict[str, Set[str]] = {}  # type -> set of names
        self._all_symbols: Optional[Set[str]] = None
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Lazy database connection."""
        if self._conn is None:
            from ck3raven.db.schema import get_connection
            self._conn = get_connection(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    # =========================================================================
    # SYMBOL LOOKUP
    # =========================================================================
    
    def get_symbols_by_type(self, symbol_type: str) -> Set[str]:
        """Get all symbol names of a given type (cached)."""
        if symbol_type not in self._symbol_cache:
            sql = """
                SELECT DISTINCT s.name
                FROM symbols s
                JOIN files f ON s.defining_file_id = f.file_id
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN playset_mods pm ON cv.content_version_id = pm.content_version_id
                    AND pm.playset_id = ? AND pm.enabled = 1
                JOIN playsets p ON p.playset_id = ?
                WHERE (
                    cv.kind = 'vanilla' AND cv.vanilla_version_id = p.vanilla_version_id
                    OR pm.playset_id = ?
                )
                AND s.symbol_type = ?
            """
            rows = self.conn.execute(sql, (self.playset_id, self.playset_id, self.playset_id, symbol_type)).fetchall()
            self._symbol_cache[symbol_type] = {row["name"] for row in rows}
        return self._symbol_cache[symbol_type]
    
    def get_all_symbols(self) -> Set[str]:
        """Get all symbol names (for existence checks)."""
        if self._all_symbols is None:
            sql = """
                SELECT DISTINCT s.name
                FROM symbols s
                JOIN files f ON s.defining_file_id = f.file_id
                JOIN content_versions cv ON f.content_version_id = cv.content_version_id
                LEFT JOIN playset_mods pm ON cv.content_version_id = pm.content_version_id
                    AND pm.playset_id = ? AND pm.enabled = 1
                JOIN playsets p ON p.playset_id = ?
                WHERE (
                    cv.kind = 'vanilla' AND cv.vanilla_version_id = p.vanilla_version_id
                    OR pm.playset_id = ?
                )
            """
            rows = self.conn.execute(sql, (self.playset_id, self.playset_id, self.playset_id)).fetchall()
            self._all_symbols = {row["name"] for row in rows}
        return self._all_symbols
    
    def symbol_exists(self, name: str, symbol_type: Optional[str] = None) -> bool:
        """Check if a symbol exists."""
        if symbol_type:
            return name in self.get_symbols_by_type(symbol_type)
        return name in self.get_all_symbols()
    
    def get_symbol_info(self, name: str, symbol_type: Optional[str] = None) -> Optional[Dict]:
        """Get detailed info about a symbol for hover."""
        sql = """
            SELECT 
                s.symbol_id, s.name, s.symbol_type, s.line_number,
                f.relpath,
                COALESCE(mp.name, 'vanilla') as mod_name
            FROM symbols s
            JOIN files f ON s.defining_file_id = f.file_id
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            LEFT JOIN playset_mods pm ON cv.content_version_id = pm.content_version_id
                AND pm.playset_id = ? AND pm.enabled = 1
            JOIN playsets p ON p.playset_id = ?
            WHERE (
                cv.kind = 'vanilla' AND cv.vanilla_version_id = p.vanilla_version_id
                OR pm.playset_id = ?
            )
            AND s.name = ?
        """
        params = [self.playset_id, self.playset_id, self.playset_id, name]
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params.append(symbol_type)
        
        sql += " LIMIT 1"
        
        row = self.conn.execute(sql, params).fetchone()
        if row:
            return {
                "symbol_id": row["symbol_id"],
                "name": row["name"],
                "symbol_type": row["symbol_type"],
                "line": row["line_number"],
                "file": row["relpath"],
                "mod": row["mod_name"]
            }
        return None
    
    def search_symbols(
        self,
        prefix: str,
        symbol_type: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """Search symbols by prefix for autocomplete."""
        sql = """
            SELECT 
                s.name, s.symbol_type,
                f.relpath,
                COALESCE(mp.name, 'vanilla') as mod_name
            FROM symbols s
            JOIN files f ON s.defining_file_id = f.file_id
            JOIN content_versions cv ON f.content_version_id = cv.content_version_id
            LEFT JOIN mod_packages mp ON cv.mod_package_id = mp.mod_package_id
            LEFT JOIN playset_mods pm ON cv.content_version_id = pm.content_version_id
                AND pm.playset_id = ? AND pm.enabled = 1
            JOIN playsets p ON p.playset_id = ?
            WHERE (
                cv.kind = 'vanilla' AND cv.vanilla_version_id = p.vanilla_version_id
                OR pm.playset_id = ?
            )
            AND s.name LIKE ?
        """
        params = [self.playset_id, self.playset_id, self.playset_id, f"{prefix}%"]
        
        if symbol_type:
            sql += " AND s.symbol_type = ?"
            params.append(symbol_type)
        
        sql += " ORDER BY LENGTH(s.name), s.name LIMIT ?"
        params.append(limit)
        
        rows = self.conn.execute(sql, params).fetchall()
        return [
            {
                "name": row["name"],
                "symbol_type": row["symbol_type"],
                "file": row["relpath"],
                "mod": row["mod_name"]
            }
            for row in rows
        ]
    
    def find_similar(self, name: str, symbol_type: Optional[str] = None, limit: int = 5) -> List[str]:
        """Find similar symbol names (for typo suggestions)."""
        # Get candidates
        if symbol_type:
            candidates = self.get_symbols_by_type(symbol_type)
        else:
            candidates = self.get_all_symbols()
        
        # Simple edit distance (Levenshtein) scoring
        def edit_distance(s1: str, s2: str) -> int:
            if len(s1) < len(s2):
                return edit_distance(s2, s1)
            if len(s2) == 0:
                return len(s1)
            
            prev_row = range(len(s2) + 1)
            for i, c1 in enumerate(s1):
                curr_row = [i + 1]
                for j, c2 in enumerate(s2):
                    insertions = prev_row[j + 1] + 1
                    deletions = curr_row[j] + 1
                    substitutions = prev_row[j] + (c1 != c2)
                    curr_row.append(min(insertions, deletions, substitutions))
                prev_row = curr_row
            return prev_row[-1]
        
        # Score and filter
        name_lower = name.lower()
        scored = []
        for candidate in candidates:
            distance = edit_distance(name_lower, candidate.lower())
            # Only suggest if reasonably close
            if distance <= max(3, len(name) // 2):
                scored.append((distance, candidate))
        
        scored.sort(key=lambda x: (x[0], x[1]))
        return [s[1] for s in scored[:limit]]
    
    # =========================================================================
    # REFERENCE VALIDATION
    # =========================================================================
    
    def validate_references(
        self,
        content: str,
        filename: str = "inline.txt"
    ) -> List[Diagnostic]:
        """
        Validate all references in CK3 script content.
        
        Parses content and checks all identifiers against symbol database.
        """
        diagnostics = []
        
        try:
            from ck3raven.parser import parse_source
        except ImportError:
            return [Diagnostic(
                line=1, column=0, end_line=1, end_column=0,
                severity="error", code="IMPORT_ERROR",
                message="Could not import ck3raven parser"
            )]
        
        # Parse content
        try:
            ast = parse_source(content)
        except Exception as e:
            # Parse error - return early
            line = 1
            if match := re.search(r'line\s+(\d+)', str(e), re.IGNORECASE):
                line = int(match.group(1))
            return [Diagnostic(
                line=line, column=0, end_line=line, end_column=0,
                severity="error", code="PARSE_ERROR",
                message=str(e)
            )]
        
        # Walk AST and validate references
        diagnostics.extend(self._validate_ast(ast, ScopeContext(
            scope_type=ScopeType.ANY,
            parent_key=None,
            in_trigger=False,
            in_effect=False,
            depth=0
        )))
        
        return diagnostics
    
    def _validate_ast(self, node, ctx: ScopeContext) -> List[Diagnostic]:
        """Recursively validate AST nodes."""
        from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode
        
        diagnostics = []
        
        if isinstance(node, RootNode):
            for child in node.children:
                diagnostics.extend(self._validate_ast(child, ctx))
        
        elif isinstance(node, BlockNode):
            # Determine new context
            new_ctx = self._update_context(ctx, node.name)
            
            # Check if block name is a valid reference
            if self._should_validate_block_name(node.name, ctx):
                diag = self._check_reference(node.name, node.line, getattr(node, 'column', 0), ctx)
                if diag:
                    diagnostics.append(diag)
            
            # Validate children
            for child in node.children:
                diagnostics.extend(self._validate_ast(child, new_ctx))
        
        elif isinstance(node, AssignmentNode):
            key = node.key
            line = node.line
            column = getattr(node, 'column', 0)
            
            # Check if this key's value should be validated as a reference
            if key in REFERENCE_KEY_TYPES:
                expected_type = REFERENCE_KEY_TYPES[key]
                
                # Get the value
                if isinstance(node.value, ValueNode):
                    value = node.value.value
                    # Skip special values
                    if not self._is_special_value(value):
                        if not self.symbol_exists(value, expected_type):
                            # Try without type constraint
                            if not self.symbol_exists(value):
                                similar = self.find_similar(value, expected_type)
                                msg = f"Unknown {expected_type}: '{value}'"
                                if similar:
                                    msg += f". Did you mean: {', '.join(similar[:3])}?"
                                
                                diagnostics.append(Diagnostic(
                                    line=line,
                                    column=column,
                                    end_line=line,
                                    end_column=column + len(key) + len(value) + 3,
                                    severity="warning",
                                    code="UNDEFINED_REFERENCE",
                                    message=msg,
                                    data={"symbol": value, "expected_type": expected_type, "similar": similar}
                                ))
            
            # Update context and validate value
            new_ctx = self._update_context(ctx, key)
            if isinstance(node.value, (BlockNode, ListNode)):
                diagnostics.extend(self._validate_ast(node.value, new_ctx))
        
        elif isinstance(node, ListNode):
            for item in node.items:
                diagnostics.extend(self._validate_ast(item, ctx))
        
        return diagnostics
    
    def _update_context(self, ctx: ScopeContext, key: str) -> ScopeContext:
        """Update scope context based on key."""
        new_scope = SCOPE_CHANGERS.get(key.lower(), ctx.scope_type)
        
        in_trigger = ctx.in_trigger or key in ('trigger', 'limit', 'potential', 'is_valid', 'is_shown')
        in_effect = ctx.in_effect or key in ('effect', 'on_action', 'on_accept', 'on_decline')
        
        return ScopeContext(
            scope_type=new_scope,
            parent_key=key,
            in_trigger=in_trigger,
            in_effect=in_effect,
            depth=ctx.depth + 1
        )
    
    def _should_validate_block_name(self, name: str, ctx: ScopeContext) -> bool:
        """Check if we should validate this block name as a reference."""
        # Skip common keywords
        if name.lower() in {'if', 'else', 'else_if', 'while', 'limit', 'trigger', 'effect', 'modifier', 'AND', 'OR', 'NOT', 'NOR', 'NAND'}:
            return False
        # Skip scope changers
        if name.lower() in SCOPE_CHANGERS:
            return False
        return False  # For now, don't validate block names - too many false positives
    
    def _check_reference(self, name: str, line: int, column: int, ctx: ScopeContext) -> Optional[Diagnostic]:
        """Check a reference and return diagnostic if undefined."""
        if self._is_special_value(name):
            return None
        
        if not self.symbol_exists(name):
            similar = self.find_similar(name)
            msg = f"Undefined reference: '{name}'"
            if similar:
                msg += f". Did you mean: {', '.join(similar[:3])}?"
            
            return Diagnostic(
                line=line, column=column,
                end_line=line, end_column=column + len(name),
                severity="warning", code="UNDEFINED_REFERENCE",
                message=msg,
                data={"symbol": name, "similar": similar}
            )
        return None
    
    def _is_special_value(self, value: str) -> bool:
        """Check if value is a special keyword that shouldn't be validated."""
        # Boolean/yes/no
        if value.lower() in ('yes', 'no', 'true', 'false'):
            return True
        # Numbers
        if re.match(r'^-?\d+(\.\d+)?$', value):
            return True
        # Variables
        if value.startswith('@'):
            return True
        # Scripted values with scope
        if '.' in value or ':' in value:
            return True
        # Empty
        if not value.strip():
            return True
        return False
    
    # =========================================================================
    # AUTOCOMPLETE
    # =========================================================================
    
    def get_completions(
        self,
        content: str,
        line: int,
        column: int,
        filename: str = "inline.txt"
    ) -> List[CompletionItem]:
        """
        Get autocomplete suggestions at cursor position.
        
        Args:
            content: Full file content
            line: 1-based line number
            column: 0-based column
            filename: For context hints
        """
        completions = []
        
        # Get the partial word at cursor
        lines = content.split('\n')
        if line < 1 or line > len(lines):
            return []
        
        current_line = lines[line - 1]
        prefix = self._get_word_at_position(current_line, column)
        
        # Determine context from surrounding text
        context = self._determine_completion_context(lines, line, column)
        
        # Add symbol completions
        if context.get("after_equals"):
            # Completing a value
            parent_key = context.get("parent_key", "")
            expected_type = REFERENCE_KEY_TYPES.get(parent_key)
            
            symbols = self.search_symbols(prefix, symbol_type=expected_type, limit=50)
            for sym in symbols:
                completions.append(CompletionItem(
                    label=sym["name"],
                    kind="symbol",
                    detail=f'{sym["symbol_type"]} ({sym["mod"]})',
                    documentation=f'Defined in: {sym["file"]}',
                    insert_text=sym["name"],
                    symbol_type=sym["symbol_type"],
                    mod=sym["mod"],
                    sort_text=f"0_{sym['name']}"  # Prioritize
                ))
        
        else:
            # Completing a key or block name
            # Add scope changers
            for scope_name in SCOPE_CHANGERS.keys():
                if scope_name.lower().startswith(prefix.lower()):
                    completions.append(CompletionItem(
                        label=scope_name,
                        kind="scope",
                        detail="Scope changer",
                        documentation=f"Changes scope to {SCOPE_CHANGERS[scope_name].value}",
                        insert_text=scope_name,
                        sort_text=f"1_{scope_name}"
                    ))
            
            # Add common keywords
            for keyword in ['if', 'else', 'else_if', 'limit', 'trigger', 'effect', 'modifier']:
                if keyword.startswith(prefix.lower()):
                    completions.append(CompletionItem(
                        label=keyword,
                        kind="keyword",
                        detail="Keyword",
                        documentation=f"CK3 script keyword: {keyword}",
                        insert_text=keyword,
                        sort_text=f"2_{keyword}"
                    ))
            
            # Add reference key completions
            for key in REFERENCE_KEY_TYPES.keys():
                if key.startswith(prefix.lower()):
                    completions.append(CompletionItem(
                        label=key,
                        kind="keyword",
                        detail=f"References: {REFERENCE_KEY_TYPES[key]}",
                        documentation=f"Key that references a {REFERENCE_KEY_TYPES[key]}",
                        insert_text=key,
                        sort_text=f"3_{key}"
                    ))
        
        return completions
    
    def _get_word_at_position(self, line: str, column: int) -> str:
        """Extract the partial word at cursor position."""
        if column > len(line):
            column = len(line)
        
        # Find word start
        start = column
        while start > 0 and re.match(r'[\w_@]', line[start - 1]):
            start -= 1
        
        return line[start:column]
    
    def _determine_completion_context(
        self,
        lines: List[str],
        line: int,
        column: int
    ) -> Dict[str, Any]:
        """Determine context for completions."""
        context = {
            "after_equals": False,
            "in_block": False,
            "parent_key": None
        }
        
        if line < 1 or line > len(lines):
            return context
        
        current_line = lines[line - 1]
        before_cursor = current_line[:column]
        
        # Check if after equals
        if '=' in before_cursor:
            context["after_equals"] = True
            # Get the key before equals
            match = re.search(r'(\w+)\s*=\s*$', before_cursor)
            if match:
                context["parent_key"] = match.group(1)
        
        # Check brace depth
        brace_depth = 0
        for i in range(line - 1, -1, -1):
            line_text = lines[i]
            brace_depth += line_text.count('{') - line_text.count('}')
        
        context["in_block"] = brace_depth > 0
        
        return context
    
    # =========================================================================
    # HOVER
    # =========================================================================
    
    def get_hover(
        self,
        content: str,
        line: int,
        column: int,
        filename: str = "inline.txt"
    ) -> Optional[HoverInfo]:
        """
        Get hover documentation for symbol at position.
        
        Args:
            content: Full file content
            line: 1-based line number
            column: 0-based column
        """
        lines = content.split('\n')
        if line < 1 or line > len(lines):
            return None
        
        current_line = lines[line - 1]
        
        # Get the word at position
        word, word_start, word_end = self._get_word_bounds(current_line, column)
        if not word:
            return None
        
        # Look up in database
        info = self.get_symbol_info(word)
        if not info:
            # Check if it's a known keyword
            if word in REFERENCE_KEY_TYPES:
                return HoverInfo(
                    content=f"**{word}**\n\nReferences: `{REFERENCE_KEY_TYPES[word]}`",
                    range={"line": line, "column": word_start, "end_line": line, "end_column": word_end}
                )
            if word in SCOPE_CHANGERS:
                return HoverInfo(
                    content=f"**{word}**\n\nScope changer → `{SCOPE_CHANGERS[word].value}`",
                    range={"line": line, "column": word_start, "end_line": line, "end_column": word_end}
                )
            return None
        
        # Build markdown documentation
        md_parts = [
            f"**{info['name']}**",
            f"\n\nType: `{info['symbol_type']}`",
            f"\n\nSource: `{info['mod']}`",
            f"\n\nFile: `{info['file']}`",
        ]
        if info.get('line'):
            md_parts.append(f" (line {info['line']})")
        
        return HoverInfo(
            content="".join(md_parts),
            range={"line": line, "column": word_start, "end_line": line, "end_column": word_end}
        )
    
    def _get_word_bounds(self, line: str, column: int) -> Tuple[str, int, int]:
        """Get word and its bounds at column position."""
        if column > len(line):
            column = len(line)
        
        # Find word start
        start = column
        while start > 0 and re.match(r'[\w_@]', line[start - 1]):
            start -= 1
        
        # Find word end
        end = column
        while end < len(line) and re.match(r'[\w_@]', line[end]):
            end += 1
        
        word = line[start:end]
        return word, start, end
    
    # =========================================================================
    # GO TO DEFINITION
    # =========================================================================
    
    def get_definition(
        self,
        content: str,
        line: int,
        column: int,
        filename: str = "inline.txt"
    ) -> Optional[SymbolLocation]:
        """
        Get definition location for symbol at position.
        """
        lines = content.split('\n')
        if line < 1 or line > len(lines):
            return None
        
        current_line = lines[line - 1]
        word, _, _ = self._get_word_bounds(current_line, column)
        
        if not word:
            return None
        
        info = self.get_symbol_info(word)
        if not info:
            return None
        
        return SymbolLocation(
            file_path=info['file'],
            line=info.get('line', 1) or 1,
            column=0,
            mod=info['mod']
        )


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def validate_content(
    content: str,
    db_path: Path,
    playset_id: int = 1,
    filename: str = "inline.txt"
) -> Dict[str, Any]:
    """
    Validate CK3 script content.
    
    Returns:
        {
            "success": bool,
            "errors": [...],
            "warnings": [...]
        }
    """
    analyzer = SemanticAnalyzer(db_path, playset_id)
    try:
        diagnostics = analyzer.validate_references(content, filename)
        
        errors = [d for d in diagnostics if d.severity == "error"]
        warnings = [d for d in diagnostics if d.severity == "warning"]
        
        return {
            "success": len(errors) == 0,
            "errors": [_diag_to_dict(d) for d in errors],
            "warnings": [_diag_to_dict(d) for d in warnings]
        }
    finally:
        analyzer.close()


def get_completions(
    content: str,
    line: int,
    column: int,
    db_path: Path,
    playset_id: int = 1
) -> List[Dict]:
    """Get autocomplete suggestions."""
    analyzer = SemanticAnalyzer(db_path, playset_id)
    try:
        items = analyzer.get_completions(content, line, column)
        return [_completion_to_dict(item) for item in items]
    finally:
        analyzer.close()


def get_hover(
    content: str,
    line: int,
    column: int,
    db_path: Path,
    playset_id: int = 1
) -> Optional[Dict]:
    """Get hover documentation."""
    analyzer = SemanticAnalyzer(db_path, playset_id)
    try:
        info = analyzer.get_hover(content, line, column)
        if info:
            return {"content": info.content, "range": info.range}
        return None
    finally:
        analyzer.close()


def _diag_to_dict(d: Diagnostic) -> Dict:
    """Convert Diagnostic to dict."""
    return {
        "line": d.line,
        "column": d.column,
        "end_line": d.end_line,
        "end_column": d.end_column,
        "severity": d.severity,
        "code": d.code,
        "message": d.message,
        "source": d.source,
        "data": d.data
    }


def _completion_to_dict(c: CompletionItem) -> Dict:
    """Convert CompletionItem to dict."""
    return {
        "label": c.label,
        "kind": c.kind,
        "detail": c.detail,
        "documentation": c.documentation,
        "insertText": c.insert_text,
        "symbolType": c.symbol_type,
        "mod": c.mod,
        "sortText": c.sort_text
    }
