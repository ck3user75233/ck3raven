"""
Contribution Unit Extraction and Conflict Grouping

Implements the data contracts from the CK3 Lens spec:
1. Contribution Unit - what each source provides for a unit_key
2. Conflict Unit - a group of competing contributions
3. Resolution Choice - user's decision on how to resolve

A "unit" is a separately-resolvable block of CK3 content:
- on_action:on_yearly_pulse
- decision:restore_roman_empire
- scripted_effect:give_prestige_effect
- event:namespace.0001
- trait:brave
- etc.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any, Literal
from enum import Enum, auto
from datetime import datetime

from ck3raven.resolver.policies import MergePolicy, get_policy_for_folder, SubBlockPolicy, CONTENT_TYPE_CONFIGS


# =============================================================================
# ENUMS
# =============================================================================

class MergeCapability(Enum):
    """What kind of merge is possible for a conflict unit."""
    WINNER_ONLY = auto()      # Must pick one winner
    GUIDED_MERGE = auto()     # Can merge with rules (e.g., append lists)
    AI_MERGE = auto()         # Complex merge needs AI assistance


class RiskLevel(Enum):
    """Risk level for a conflict unit."""
    LOW = "low"
    MEDIUM = "med"
    HIGH = "high"


class UncertaintyLevel(Enum):
    """How uncertain we are about the merge behavior."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "med"
    HIGH = "high"


class ResolutionType(Enum):
    """Type of resolution decision."""
    WINNER = "winner"
    CUSTOM_MERGE = "custom_merge"
    DEFER = "defer"


# =============================================================================
# DATA CONTRACTS
# =============================================================================

@dataclass
class ContributionUnit:
    """
    What each source (vanilla/mod) provides for a specific unit_key.
    Extracted from raw AST per file - NOT resolved yet.
    """
    contrib_id: str                          # SHA256 hash of (cv_id, file_id, node_path)
    content_version_id: int                  # FK to content_versions
    file_id: int                             # FK to files
    domain: str                              # on_action, decision, event, trait, etc.
    unit_key: str                            # on_action:on_yearly_pulse, decision:restore_empire
    node_path: str                           # JSON path to AST node
    relpath: str                             # File path
    line_number: Optional[int]
    merge_behavior_hint: str                 # replace, append, merge_by_id, unknown
    symbols_defined: List[Dict[str, str]]    # [{"type":"on_action","name":"..."}]
    refs_used: List[Dict[str, str]]          # [{"type":"scripted_effect","name":"..."}]
    
    # Computed summaries
    node_hash: Optional[str] = None          # Hash of the AST node for diff detection
    summary: Optional[str] = None            # Human-readable summary
    
    def compute_id(self) -> str:
        """Compute a stable ID for this contribution."""
        key = f"{self.content_version_id}:{self.file_id}:{self.node_path}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictCandidate:
    """A candidate in a conflict - one of the competing contributions."""
    candidate_id: str
    source_name: str                         # mod name (including game files)
    content_version_id: int
    load_order_index: int
    contrib_id: str                          # FK to contribution
    file_id: int
    node_path: str
    relpath: str
    line_number: Optional[int]
    summary: Optional[str]
    node_hash: Optional[str]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ConflictUnit:
    """
    A group of competing contributions for the same unit_key.
    This is what the Compatch Helper shows as a decision card.
    """
    conflict_unit_id: str                    # SHA256 hash
    unit_key: str                            # on_action:on_yearly_pulse
    domain: str                              # on_action
    candidates: List[ConflictCandidate]
    merge_capability: MergeCapability
    risk: RiskLevel
    uncertainty: UncertaintyLevel
    reasons: List[str]                       # Why this is risky/uncertain
    
    # Resolution state
    resolution_status: str = "unresolved"    # unresolved, resolved, deferred
    resolution_id: Optional[str] = None      # FK to resolution if resolved
    
    def compute_id(self) -> str:
        """Compute a stable ID for this conflict unit."""
        return hashlib.sha256(self.unit_key.encode()).hexdigest()[:16]
    
    @property
    def candidate_count(self) -> int:
        return len(self.candidates)
    
    def get_winner_by_load_order(self) -> Optional[ConflictCandidate]:
        """Get the candidate that would win by load order (LIOS)."""
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.load_order_index)
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['merge_capability'] = self.merge_capability.name
        d['risk'] = self.risk.value
        d['uncertainty'] = self.uncertainty.value
        return d


@dataclass
class MergePolicy:
    """Custom merge policy for a resolution."""
    keep_unique_ids: bool = True
    prefer: List[Dict[str, str]] = field(default_factory=list)  # [{"keypath":"effect", "candidate":"Mod A"}]
    dedupe: List[Dict[str, str]] = field(default_factory=list)  # [{"by":"id"}]
    preserve_order: str = "load_order"       # load_order, alphabetical, custom


@dataclass
class ResolutionChoice:
    """
    User's decision on how to resolve a conflict unit.
    This becomes the plan/audit and drives patch generation.
    """
    resolution_id: str
    conflict_unit_id: str
    decision_type: ResolutionType
    winner_candidate_id: Optional[str] = None     # For WINNER type
    merge_policy: Optional[MergePolicy] = None    # For CUSTOM_MERGE type
    notes: Optional[str] = None
    applied_at: Optional[str] = None
    applied_by: str = "user"
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['decision_type'] = self.decision_type.value
        return d


# =============================================================================
# UNIT KEY SCHEME
# =============================================================================

# Maps domain to how unit_key is constructed
UNIT_KEY_SCHEMES: Dict[str, Dict[str, Any]] = {
    "on_action": {
        "prefix": "on_action",
        "key_source": "block_name",           # Top-level block name
        "examples": ["on_action:on_yearly_pulse", "on_action:on_birth_child"],
    },
    "decision": {
        "prefix": "decision",
        "key_source": "block_name",
        "examples": ["decision:restore_roman_empire", "decision:found_holy_order"],
    },
    "scripted_effect": {
        "prefix": "scripted_effect",
        "key_source": "block_name",
        "examples": ["scripted_effect:give_prestige_effect"],
    },
    "scripted_trigger": {
        "prefix": "scripted_trigger",
        "key_source": "block_name",
        "examples": ["scripted_trigger:is_valid_knight"],
    },
    "event": {
        "prefix": "event",
        "key_source": "namespace.id",         # namespace.0001
        "examples": ["event:feast.0001", "event:health.0010"],
    },
    "trait": {
        "prefix": "trait",
        "key_source": "block_name",
        "examples": ["trait:brave", "trait:craven"],
    },
    "culture": {
        "prefix": "culture",
        "key_source": "block_name",
        "examples": ["culture:english", "culture:norman"],
    },
    "tradition": {
        "prefix": "tradition",
        "key_source": "block_name",
        "examples": ["tradition:tradition_warrior_culture"],
    },
    "religion": {
        "prefix": "religion",
        "key_source": "block_name",
        "examples": ["religion:christianity", "religion:islam_religion"],
    },
    "faith": {
        "prefix": "faith",
        "key_source": "block_name",
        "examples": ["faith:catholic", "faith:orthodox"],
    },
    "doctrine": {
        "prefix": "doctrine",
        "key_source": "block_name",
        "examples": ["doctrine:doctrine_pluralism_fundamentalist"],
    },
    "modifier": {
        "prefix": "modifier",
        "key_source": "block_name",
        "examples": ["modifier:base_prestige_modifier"],
    },
    "character_interaction": {
        "prefix": "interaction",
        "key_source": "block_name",
        "examples": ["interaction:invite_to_court_interaction"],
    },
    "defines": {
        "prefix": "defines",
        "key_source": "namespace.key",        # NGame.START_DATE
        "examples": ["defines:NGame.START_DATE", "defines:NCharacter.MAX_STRESS"],
    },
    "localization": {
        "prefix": "loc",
        "key_source": "key",
        "examples": ["loc:brave", "loc:EVENT_TITLE_feast_0001"],
    },
    "maa_type": {
        "prefix": "maa",
        "key_source": "block_name",
        "examples": ["maa:pikemen", "maa:heavy_infantry"],
    },
    "building": {
        "prefix": "building",
        "key_source": "block_name",
        "examples": ["building:castle_01", "building:farm_estates_01"],
    },
    "holding": {
        "prefix": "holding",
        "key_source": "block_name",
        "examples": ["holding:castle_holding", "holding:city_holding"],
    },
    "law": {
        "prefix": "law",
        "key_source": "block_name",
        "examples": ["law:crown_authority_0", "law:succession_and_gender_laws"],
    },
    "casus_belli": {
        "prefix": "cb",
        "key_source": "block_name",
        "examples": ["cb:conquest_cb", "cb:religious_war"],
    },
    "scheme": {
        "prefix": "scheme",
        "key_source": "block_name",
        "examples": ["scheme:murder", "scheme:seduce"],
    },
}


def get_domain_from_path(relpath: str) -> str:
    """
    Determine the content domain from a file path.
    
    Args:
        relpath: Relative path like "common/on_action/00_on_actions.txt"
    
    Returns:
        Domain string like "on_action"
    """
    path = relpath.replace("\\", "/").lower()
    
    # Order matters - check more specific paths first
    if "common/on_action" in path:
        return "on_action"
    if "common/decisions" in path:
        return "decision"
    if "common/scripted_effects" in path:
        return "scripted_effect"
    if "common/scripted_triggers" in path:
        return "scripted_trigger"
    if "common/traits" in path:
        return "trait"
    if "common/culture/traditions" in path:
        return "tradition"
    if "common/culture/cultures" in path:
        return "culture"
    if "common/religion/religions" in path:
        return "religion"
    if "common/religion/doctrines" in path:
        return "doctrine"
    if "common/modifiers" in path:
        return "modifier"
    if "common/character_interactions" in path:
        return "character_interaction"
    if "common/defines" in path:
        return "defines"
    if "common/men_at_arms_types" in path:
        return "maa_type"
    if "common/buildings" in path:
        return "building"
    if "common/casus_belli_types" in path:
        return "casus_belli"
    if "common/schemes" in path:
        return "scheme"
    if "common/laws" in path:
        return "law"
    if "events/" in path:
        return "event"
    if "localization/" in path:
        return "localization"
    if "gui/" in path:
        return "gui"
    
    # Default to generic "content"
    return "content"


def make_unit_key(domain: str, name: str, namespace: Optional[str] = None) -> str:
    """
    Construct a unit_key from domain and name.
    
    Args:
        domain: Content domain (on_action, decision, etc.)
        name: Symbol/block name
        namespace: Optional namespace for events
    
    Returns:
        Unit key like "on_action:on_yearly_pulse"
    """
    scheme = UNIT_KEY_SCHEMES.get(domain, {"prefix": domain})
    prefix = scheme["prefix"]
    
    if domain == "event" and namespace:
        return f"{prefix}:{namespace}.{name}"
    elif domain == "defines" and namespace:
        return f"{prefix}:{namespace}.{name}"
    else:
        return f"{prefix}:{name}"


def get_merge_behavior(domain: str, relpath: str) -> str:
    """
    Get the merge behavior hint for a domain.
    
    Returns:
        'replace' - Last definition wins entirely
        'append' - List items are appended
        'merge_by_id' - Can merge by matching IDs within
        'unknown' - Behavior not well defined
    """
    policy = get_policy_for_folder(relpath)
    
    if policy == MergePolicy.OVERRIDE:
        return "replace"
    elif policy == MergePolicy.CONTAINER_MERGE:
        return "append"  # Simplified - actual merge depends on sub-blocks
    elif policy == MergePolicy.PER_KEY_OVERRIDE:
        return "merge_by_id"
    elif policy == MergePolicy.FIOS:
        return "replace"  # First wins, but still replace semantics
    else:
        return "unknown"


# =============================================================================
# RISK SCORING
# =============================================================================

# Domain base risk weights
DOMAIN_RISK_WEIGHTS: Dict[str, int] = {
    "on_action": 30,          # High - merge semantics complex
    "event": 25,              # High - namespace conflicts
    "scripted_effect": 15,    # Medium - can cause cascading issues
    "scripted_trigger": 15,   # Medium - used everywhere
    "decision": 10,           # Medium-low - usually isolated
    "trait": 10,              # Medium-low - usually isolated
    "defines": 15,            # Medium - global state
    "gui": 25,                # High - FIOS is confusing
    "localization": 5,        # Low - easy to merge
    "culture": 10,
    "tradition": 10,
    "religion": 15,
    "faith": 15,
    "modifier": 5,
    "maa_type": 10,
    "building": 10,
    "content": 10,            # Default
}

# Risk modifiers
RISK_MOD_PER_EXTRA_CANDIDATE = 10
RISK_MOD_UNKNOWN_MERGE = 20
RISK_MOD_RENAME_PATTERN = 20
RISK_MOD_UNKNOWN_REFS = 15
RISK_MOD_VANILLA_OVERWRITE = 5


def compute_risk_score(
    domain: str,
    candidate_count: int,
    merge_behavior: str,
    has_vanilla: bool,
    has_unknown_refs: bool,
    has_rename_pattern: bool,
) -> Tuple[int, RiskLevel, List[str]]:
    """
    Compute a risk score (0-100) and bucket for a conflict unit.
    
    Returns:
        Tuple of (score, RiskLevel, reasons)
    """
    score = DOMAIN_RISK_WEIGHTS.get(domain, 10)
    reasons = []
    
    # More candidates = more risk
    if candidate_count > 2:
        extra = (candidate_count - 2) * RISK_MOD_PER_EXTRA_CANDIDATE
        score += extra
        reasons.append(f"{candidate_count} mods touching same unit")
    
    # Unknown merge behavior
    if merge_behavior == "unknown":
        score += RISK_MOD_UNKNOWN_MERGE
        reasons.append("unknown merge semantics")
    
    # Vanilla overwrite
    if has_vanilla and candidate_count > 1:
        score += RISK_MOD_VANILLA_OVERWRITE
        reasons.append("vanilla content overwritten")
    
    # Unknown refs
    if has_unknown_refs:
        score += RISK_MOD_UNKNOWN_REFS
        reasons.append("introduces unknown references")
    
    # Rename pattern detected
    if has_rename_pattern:
        score += RISK_MOD_RENAME_PATTERN
        reasons.append("rename/refactor pattern detected")
    
    # Cap at 100
    score = min(score, 100)
    
    # Bucket
    if score >= 60:
        level = RiskLevel.HIGH
    elif score >= 30:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW
    
    return score, level, reasons


def compute_uncertainty(
    domain: str,
    merge_behavior: str,
    candidates_differ_significantly: bool,
) -> UncertaintyLevel:
    """
    Compute uncertainty level for a conflict.
    
    Uncertainty is about whether we correctly understand the merge behavior,
    not about the risk of the conflict itself.
    """
    # on_action sub-blocks are uncertain
    if domain == "on_action":
        return UncertaintyLevel.MEDIUM
    
    # Unknown merge behavior
    if merge_behavior == "unknown":
        return UncertaintyLevel.HIGH
    
    # Significant differences
    if candidates_differ_significantly:
        return UncertaintyLevel.MEDIUM
    
    return UncertaintyLevel.LOW


def get_merge_capability(domain: str, merge_behavior: str) -> MergeCapability:
    """
    Determine what kind of merge is possible for this domain.
    """
    if merge_behavior == "append":
        return MergeCapability.GUIDED_MERGE
    elif merge_behavior == "merge_by_id":
        return MergeCapability.GUIDED_MERGE
    elif merge_behavior == "replace":
        return MergeCapability.WINNER_ONLY
    else:
        return MergeCapability.AI_MERGE


# =============================================================================
# DATABASE SCHEMA ADDITIONS
# =============================================================================

# NOTE: Schema is now defined in ck3raven.db.schema.py
# Contribution tables are created with init_database()
# This constant is kept for backward compatibility with init_contribution_schema()

CONTRIBUTION_SCHEMA = """
-- Contribution Units - what each source provides for a unit_key
-- Extracted per content_version (mod or vanilla), NOT per playset
-- Same contribution is reused across all playsets containing that mod/vanilla
CREATE TABLE IF NOT EXISTS contribution_units (
    contrib_id TEXT PRIMARY KEY,
    content_version_id INTEGER NOT NULL,      -- FK to content_versions
    file_id INTEGER NOT NULL,                 -- FK to files
    domain TEXT NOT NULL,                     -- on_action, decision, event, etc.
    unit_key TEXT NOT NULL,                   -- on_action:on_yearly_pulse
    node_path TEXT,                           -- JSON path to AST node
    relpath TEXT NOT NULL,                    -- File path
    line_number INTEGER,
    merge_behavior TEXT NOT NULL,             -- replace, append, merge_by_id, unknown
    symbols_json TEXT,                        -- JSON array of defined symbols
    refs_json TEXT,                           -- JSON array of used references
    node_hash TEXT,                           -- Hash of AST node for diff detection
    summary TEXT,                             -- Human-readable summary
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (content_version_id) REFERENCES content_versions(content_version_id),
    FOREIGN KEY (file_id) REFERENCES files(file_id)
);

CREATE INDEX IF NOT EXISTS idx_contrib_unit_key ON contribution_units(unit_key);
CREATE INDEX IF NOT EXISTS idx_contrib_domain ON contribution_units(domain);
CREATE INDEX IF NOT EXISTS idx_contrib_cv ON contribution_units(content_version_id);
CREATE INDEX IF NOT EXISTS idx_contrib_file ON contribution_units(file_id);

-- Conflict Units - groups of competing contributions for a playset
CREATE TABLE IF NOT EXISTS conflict_units (
    conflict_unit_id TEXT PRIMARY KEY,
    playset_id INTEGER NOT NULL,              -- FK to playsets
    unit_key TEXT NOT NULL,                   -- on_action:on_yearly_pulse
    domain TEXT NOT NULL,                     -- on_action
    candidate_count INTEGER NOT NULL,
    merge_capability TEXT NOT NULL,           -- winner_only, guided_merge, ai_merge
    risk TEXT NOT NULL,                       -- low, med, high
    risk_score INTEGER NOT NULL,              -- 0-100
    uncertainty TEXT NOT NULL,                -- none, low, med, high
    reasons_json TEXT,                        -- JSON array of risk reasons
    resolution_status TEXT NOT NULL DEFAULT 'unresolved',  -- unresolved, resolved, deferred
    resolution_id TEXT,                       -- FK to resolution if resolved
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (playset_id) REFERENCES playsets(playset_id)
);

CREATE INDEX IF NOT EXISTS idx_conflict_playset ON conflict_units(playset_id);
CREATE INDEX IF NOT EXISTS idx_conflict_unit_key ON conflict_units(unit_key);
CREATE INDEX IF NOT EXISTS idx_conflict_domain ON conflict_units(domain);
CREATE INDEX IF NOT EXISTS idx_conflict_risk ON conflict_units(risk);
CREATE INDEX IF NOT EXISTS idx_conflict_status ON conflict_units(resolution_status);

-- Conflict Candidates - link conflict units to contribution units
CREATE TABLE IF NOT EXISTS conflict_candidates (
    conflict_unit_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,               -- Unique within conflict
    contrib_id TEXT NOT NULL,                 -- FK to contribution_units
    source_name TEXT NOT NULL,                -- Mod name (including game files)
    load_order_index INTEGER NOT NULL,
    is_winner INTEGER NOT NULL DEFAULT 0,     -- 1 if this would win by load order
    PRIMARY KEY (conflict_unit_id, candidate_id),
    FOREIGN KEY (conflict_unit_id) REFERENCES conflict_units(conflict_unit_id),
    FOREIGN KEY (contrib_id) REFERENCES contribution_units(contrib_id)
);

-- Resolution Choices - user decisions
CREATE TABLE IF NOT EXISTS resolution_choices (
    resolution_id TEXT PRIMARY KEY,
    conflict_unit_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,              -- winner, custom_merge, defer
    winner_candidate_id TEXT,                 -- For winner type
    merge_policy_json TEXT,                   -- For custom_merge type
    notes TEXT,
    applied_at TEXT,
    applied_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (conflict_unit_id) REFERENCES conflict_units(conflict_unit_id)
);

CREATE INDEX IF NOT EXISTS idx_resolution_conflict ON resolution_choices(conflict_unit_id);
"""


def init_contribution_schema(conn: sqlite3.Connection):
    """Initialize the contribution/conflict schema."""
    conn.executescript(CONTRIBUTION_SCHEMA)
    conn.commit()
