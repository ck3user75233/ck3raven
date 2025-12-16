# CK3 Lens Design Specification

## Version 1.0 - Game State Explorer + Compatch Helper

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [UI State Objects](#ui-state-objects)
3. [Unit Key Schemes](#unit-key-schemes)
4. [Data Contracts](#data-contracts)
5. [Webview Message Protocol](#webview-message-protocol)
6. [Implementation Phases](#implementation-phases)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         VS Code Extension                            │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │
│  │ Activity Bar    │  │ Sidebar Views   │  │ Webview Panels  │      │
│  │ "CK3 Lens"      │  │ (WebviewView)   │  │ (Detail/Merge)  │      │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘      │
│           │                    │                    │                │
│           └────────────────────┼────────────────────┘                │
│                                │                                     │
│                    ┌───────────▼───────────┐                         │
│                    │   Extension Host      │                         │
│                    │   (TypeScript)        │                         │
│                    │   - Command handlers  │                         │
│                    │   - State management  │                         │
│                    │   - File operations   │                         │
│                    └───────────┬───────────┘                         │
└────────────────────────────────┼─────────────────────────────────────┘
                                 │ JSON-RPC / stdio
┌────────────────────────────────▼─────────────────────────────────────┐
│                        Python Backend                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐       │
│  │ ck3raven        │  │ Conflict Engine │  │ Patch Generator │       │
│  │ - Parser        │  │ - Unit Extractor│  │ - Syntax Emit   │       │
│  │ - Resolver      │  │ - Risk Scorer   │  │ - Validation    │       │
│  │ - SQLite DB     │  │ - Merge Engine  │  │ - Audit Log     │       │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## UI State Objects

These JSON schemas drive the webview rendering. The extension host maintains state and pushes updates to webviews.

### 1. Global App State

```typescript
interface AppState {
  // Active context
  activePlayset: PlaysetInfo | null;
  activeBuild: BuildInfo | null;
  activeView: 'explorer' | 'compatch' | 'reports';
  
  // Build status
  buildStatus: 'idle' | 'building' | 'ready' | 'error';
  buildProgress?: {
    phase: string;
    current: number;
    total: number;
  };
  
  // Summary stats (always visible)
  stats: {
    totalNodes: number;
    uncertainNodes: number;
    conflictUnits: number;
    unresolvedConflicts: number;
  };
}
```

### 2. Explorer View State

```typescript
interface ExplorerState {
  // Context bar
  context: {
    playsetId: string;
    vanillaVersion: string;
    buildId: string;
    parserVersion: string;
  };
  
  // Search
  search: {
    scope: 'raw' | 'symbols' | 'refs' | 'ast';
    query: string;
    results: SearchResult[];
    loading: boolean;
  };
  
  // Tree navigation
  tree: {
    expandedPaths: string[];  // e.g., ["common", "common/on_action"]
    selectedPath: string | null;
  };
  
  // Filters
  filters: {
    showUncertain: boolean;
    showMerged: boolean;
    showVanillaOnly: boolean;
    showModOnly: boolean;
    domainFilter: string | null;
    modFilter: string | null;
  };
}

interface SearchResult {
  nodeId: string;
  unitKey: string;
  domain: string;
  path: string;
  line: number;
  snippet: string;
  matchType: 'exact' | 'fuzzy' | 'ref';
  source: SourceInfo;
}
```

### 3. Node Detail State

```typescript
interface NodeDetailState {
  nodeId: string;
  unitKey: string;
  
  // View mode
  viewMode: 'syntax' | 'ast';
  
  // Content
  syntax: {
    content: string;
    highlights: SyntaxHighlight[];
  };
  ast: ASTNode;
  
  // Provenance
  provenance: ProvenanceEntry[];
  winner: {
    source: SourceInfo;
    reason: string;
  };
  
  // Uncertainty
  uncertainty: {
    level: 'none' | 'low' | 'medium' | 'high';
    reasonCode: string;
    explanation: string;
    recommendedValidation: string | null;
  };
  
  // References
  refs: {
    defines: SymbolRef[];
    uses: SymbolRef[];
    unknownRefs: SymbolRef[];
  };
  
  // Diagnostics
  diagnostics: Diagnostic[];
}

interface SyntaxHighlight {
  startLine: number;
  endLine: number;
  type: 'winner' | 'overridden' | 'appended' | 'uncertain';
  source: SourceInfo;
}

interface ProvenanceEntry {
  order: number;
  source: SourceInfo;
  operation: 'replace' | 'append' | 'merge_by_key' | 'merge_by_index' | 'unknown';
  span: { startLine: number; endLine: number };
  overrides: SourceInfo[];
  isWinner: boolean;
}

interface SourceInfo {
  kind: 'vanilla' | 'mod';
  name: string;
  contentVersionId: string;
  fileId: string;
  path: string;
  line: number;
}
```

### 4. Compatch View State

```typescript
interface CompatchState {
  // Build setup
  setup: {
    playsetId: string;
    targetVanilla: string;
    patchProjectPath: string;
    strategyPreset: 'conservative' | 'preserve_content' | 'minimal_diff';
  };
  
  // Scan status
  scanStatus: 'idle' | 'scanning' | 'ready' | 'error';
  
  // Conflict summary
  summary: {
    total: number;
    high: number;
    medium: number;
    low: number;
    uncertain: number;
    resolved: number;
    unresolved: number;
  };
  
  // Filters
  filters: {
    riskFilter: ('high' | 'medium' | 'low')[];
    showUncertain: boolean;
    domainFilter: string | null;
    modFilter: string | null;
    statusFilter: 'all' | 'resolved' | 'unresolved';
    searchQuery: string;
  };
  
  // Conflict list (paginated)
  conflicts: ConflictUnitSummary[];
  pagination: {
    page: number;
    pageSize: number;
    totalItems: number;
  };
  
  // Selected conflict
  selectedConflictId: string | null;
}

interface ConflictUnitSummary {
  conflictUnitId: string;
  unitKey: string;
  domain: string;
  risk: 'low' | 'medium' | 'high';
  uncertainty: 'none' | 'low' | 'medium' | 'high';
  candidateCount: number;
  candidateMods: string[];
  status: 'unresolved' | 'winner_chosen' | 'custom_merged' | 'deferred' | 'expected';
  chosenWinner?: string;
}
```

### 5. Decision Card State

```typescript
interface DecisionCardState {
  conflictUnit: ConflictUnit;
  
  // View mode for previews
  previewMode: 'syntax_diff' | 'ast_diff' | 'refs_impact' | 'load_order';
  
  // Current decision (in progress)
  decision: {
    type: 'winner' | 'custom_merge' | 'defer' | 'expected' | null;
    winnerId: string | null;
    mergePolicy: MergePolicy | null;
    notes: string;
  };
  
  // Validation result
  validation: {
    status: 'pending' | 'valid' | 'invalid';
    errors: string[];
    warnings: string[];
  };
}

interface ConflictUnit {
  conflictUnitId: string;
  unitKey: string;
  domain: string;
  
  candidates: Candidate[];
  
  mergeCapability: 'winner_only' | 'guided_merge' | 'ai_merge';
  risk: 'low' | 'medium' | 'high';
  uncertainty: 'none' | 'low' | 'medium' | 'high';
  reasons: string[];
}

interface Candidate {
  candidateId: string;
  source: SourceInfo;
  contribId: string;
  
  // Preview content
  syntax: string;
  ast: ASTNode;
  
  // Impact analysis
  symbolsDefined: SymbolRef[];
  refsUsed: SymbolRef[];
  unknownRefsIfChosen: SymbolRef[];
  
  summary: string;  // AI-generated or template: "Adds effect X, removes effect Y"
}

interface MergePolicy {
  keepUniqueIds: boolean;
  appendMissingListItems: boolean;
  preferKeyValues: { keypath: string; candidateId: string }[];
  deduplicateBy: string[];
  preserveOrder: 'load_order' | 'candidate_a' | 'candidate_b' | 'alphabetical';
  customRules: string[];  // For advanced users
}
```

### 6. Merge Editor State

```typescript
interface MergeEditorState {
  conflictUnitId: string;
  unitKey: string;
  
  // Left/Right candidates
  left: {
    candidateId: string;
    viewMode: 'syntax' | 'ast';
    content: string;
    ast: ASTNode;
  };
  right: {
    candidateId: string;
    viewMode: 'syntax' | 'ast';
    content: string;
    ast: ASTNode;
  };
  
  // Result (live preview)
  result: {
    content: string;
    ast: ASTNode;
    valid: boolean;
    errors: string[];
  };
  
  // Merge controls
  controls: MergePolicy;
  
  // AI assist
  aiAssist: {
    enabled: boolean;
    status: 'idle' | 'generating' | 'validating' | 'ready' | 'error';
    outputContract: 'strict' | 'flexible';
    generatedContent: string | null;
    validationResult: {
      parsed: boolean;
      meetsContract: boolean;
      errors: string[];
    } | null;
  };
}
```

### 7. Reports View State

```typescript
interface ReportsState {
  // Available report types
  availableReports: ReportType[];
  
  // Active report
  activeReport: {
    type: ReportType;
    status: 'idle' | 'generating' | 'ready' | 'error';
    data: ReportData | null;
  } | null;
  
  // Diff configuration
  diffConfig: {
    buildA: string | null;
    buildB: string | null;
  };
  
  // Snapshots
  snapshots: SnapshotInfo[];
}

type ReportType = 
  | 'diff_builds'
  | 'conflict_hotspots'
  | 'override_churn'
  | 'suspicious_overwrites'
  | 'missing_references'
  | 'uncertainty_coverage';

interface ReportData {
  generatedAt: string;
  summary: Record<string, number>;
  items: ReportItem[];
  exportFormats: ('markdown' | 'json' | 'html')[];
}

interface ReportItem {
  id: string;
  severity: 'info' | 'warning' | 'error';
  category: string;
  title: string;
  description: string;
  nodeId?: string;
  unitKey?: string;
  affectedMods: string[];
  recommendation?: string;
}
```

---

## Unit Key Schemes

Unit keys provide stable, domain-aware identifiers for conflict detection and resolution.

### Format

```
<domain>:<type>:<identifier>[:<subpath>]
```

### Per-Domain Schemes

#### 1. On Actions (`common/on_action/`)

```
on_action:on_action:<action_name>
on_action:on_action:<action_name>:effect[<index>]
on_action:on_action:<action_name>:trigger
on_action:on_action:<action_name>:weight_multiplier
```

**Examples:**
- `on_action:on_action:on_yearly_pulse`
- `on_action:on_action:on_yearly_pulse:effect[0]`
- `on_action:on_action:on_birth_child:trigger`

**Merge behavior:** CONTAINER_MERGE (effects append, other keys replace)

**Risk factors:**
- Multiple mods touching same action: +30
- Effect block replacements: +20
- Trigger modifications: +15

---

#### 2. Scripted Effects (`common/scripted_effects/`)

```
scripted_effect:scripted_effect:<effect_name>
```

**Examples:**
- `scripted_effect:scripted_effect:train_commander_effect`
- `scripted_effect:scripted_effect:create_story_cycle_effect`

**Merge behavior:** OVERRIDE (last wins)

**Risk factors:**
- Base game effect override: +25
- Used by many mods: +15

---

#### 3. Scripted Triggers (`common/scripted_triggers/`)

```
scripted_trigger:scripted_trigger:<trigger_name>
```

**Merge behavior:** OVERRIDE (last wins)

---

#### 4. Decisions (`common/decisions/`)

```
decision:decision:<decision_id>
decision:decision:<decision_id>:is_shown
decision:decision:<decision_id>:is_valid
decision:decision:<decision_id>:effect
decision:decision:<decision_id>:ai_check_interval
```

**Examples:**
- `decision:decision:form_roman_empire_decision`
- `decision:decision:form_roman_empire_decision:effect`

**Merge behavior:** ID_MERGE (blocks with same ID merge)

---

#### 5. Events (`events/`)

```
event:namespace:<namespace>
event:event:<event_id>
event:event:<event_id>:trigger
event:event:<event_id>:immediate
event:event:<event_id>:option[<index>]
event:event:<event_id>:option[<index>]:trigger
```

**Examples:**
- `event:namespace:yearly_events`
- `event:event:yearly_events.0001`
- `event:event:yearly_events.0001:option[0]`

**Merge behavior:** ID_MERGE per event_id

**Risk factors:**
- Event chain modifications: +25
- Option changes: +20

---

#### 6. Defines (`common/defines/`)

```
define:define:<namespace>.<key>
```

**Examples:**
- `define:define:NGame.START_DATE`
- `define:define:NCharacter.MAX_PROWESS`
- `define:define:NMilitary.ARMY_MOVEMENT_SPEED`

**Merge behavior:** KEY_OVERRIDE (last value wins)

**Risk factors:**
- Game balance defines: +20
- Core mechanics defines: +25

---

#### 7. Traits (`common/traits/`)

```
trait:trait:<trait_id>
trait:trait:<trait_id>:index
trait:trait:<trait_id>:modifier
trait:trait:<trait_id>:triggered_opinion
```

**Examples:**
- `trait:trait:brave`
- `trait:trait:brave:modifier`

**Merge behavior:** ID_MERGE

---

#### 8. Culture Traditions (`common/culture/traditions/`)

```
tradition:tradition:<tradition_id>
tradition:tradition:<tradition_id>:parameters
tradition:tradition:<tradition_id>:character_modifier
tradition:tradition:<tradition_id>:culture_modifier
```

**Merge behavior:** ID_MERGE

---

#### 9. Character Interactions (`common/character_interactions/`)

```
interaction:interaction:<interaction_id>
interaction:interaction:<interaction_id>:is_shown
interaction:interaction:<interaction_id>:is_valid_showing_failures_only
interaction:interaction:<interaction_id>:on_accept
interaction:interaction:<interaction_id>:ai_targets
```

**Merge behavior:** ID_MERGE

---

#### 10. Localization (`localization/<language>/`)

```
localization:key:<key>
```

**Examples:**
- `localization:key:brave`
- `localization:key:form_roman_empire_decision_tooltip`

**Merge behavior:** KEY_OVERRIDE (last wins, by file load order)

**Risk factors:** Low (usually intentional overrides)

---

#### 11. GUI (`interface/`, `gui/`)

```
gui:type:<type_name>
gui:window:<window_name>
gui:widget:<widget_path>
```

**Merge behavior:** Complex (often full file override)

**Risk factors:**
- Layout changes: +30
- Widget modifications: +25

---

#### 12. Modifiers (`common/modifiers/`)

```
modifier:modifier:<modifier_id>
```

**Merge behavior:** ID_MERGE

---

#### 13. Buildings (`common/buildings/`)

```
building:building:<building_id>
building:building:<building_id>:asset
building:building:<building_id>:type_icon
```

**Merge behavior:** ID_MERGE

---

### Unit Key Extraction Algorithm

```python
def extract_unit_key(domain: str, file_path: str, ast_node: ASTNode) -> str:
    """Extract stable unit key from AST node."""
    
    # Domain-specific extraction
    if domain == "on_action":
        # Top-level key is the on_action name
        return f"on_action:on_action:{ast_node.name}"
    
    elif domain == "scripted_effect":
        return f"scripted_effect:scripted_effect:{ast_node.name}"
    
    elif domain == "decision":
        # Look for 'id' key inside decision block
        if hasattr(ast_node, 'id'):
            return f"decision:decision:{ast_node.id}"
        return f"decision:decision:{ast_node.name}"
    
    elif domain == "event":
        # Event namespace from file, event from 'id' key
        if ast_node.type == "namespace":
            return f"event:namespace:{ast_node.value}"
        return f"event:event:{ast_node.id}"
    
    elif domain == "define":
        # Namespace.key format
        namespace = ast_node.parent.name if ast_node.parent else "NUnknown"
        return f"define:define:{namespace}.{ast_node.name}"
    
    elif domain == "localization":
        return f"localization:key:{ast_node.key}"
    
    elif domain in ("trait", "tradition", "building", "modifier"):
        return f"{domain}:{domain}:{ast_node.name}"
    
    elif domain == "interaction":
        return f"interaction:interaction:{ast_node.name}"
    
    else:
        # Fallback: use file path + node name
        return f"{domain}:unknown:{file_path}:{ast_node.name}"
```

---

## Data Contracts

### Contribution Unit (from parser)

```json
{
  "contrib_id": "sha256:abc123...",
  "content_version_id": "vanilla:1.13.2",
  "file_id": "sha256:def456...",
  "domain": "on_action",
  "unit_key": "on_action:on_action:on_yearly_pulse",
  "node_id": "ast:789xyz",
  "path": "common/on_action/on_actions.txt",
  "line": 42,
  "merge_behavior_hint": "container_merge",
  "syntax_fragment": "on_yearly_pulse = {\n  effect = { ... }\n}",
  "ast_hash": "sha256:ghi789...",
  "symbols_defined": [
    {"type": "on_action", "name": "on_yearly_pulse"}
  ],
  "refs_used": [
    {"type": "scripted_effect", "name": "yearly_pulse_effect"}
  ]
}
```

### Conflict Unit (from conflict engine)

```json
{
  "conflict_unit_id": "sha256:conflict123...",
  "unit_key": "on_action:on_action:on_yearly_pulse",
  "domain": "on_action",
  "candidates": [
    {
      "candidate_id": "sha256:cand1...",
      "source": {
        "kind": "vanilla",
        "name": "Crusader Kings III",
        "content_version_id": "vanilla:1.13.2",
        "file_id": "sha256:file1...",
        "path": "common/on_action/on_actions.txt",
        "line": 100
      },
      "contrib_id": "sha256:contrib1...",
      "syntax": "on_yearly_pulse = { ... }",
      "summary": "Base game yearly pulse with 5 effects"
    },
    {
      "candidate_id": "sha256:cand2...",
      "source": {
        "kind": "mod",
        "name": "Mod A",
        "content_version_id": "mod:12345@v2.0",
        "file_id": "sha256:file2...",
        "path": "common/on_action/on_actions.txt",
        "line": 50
      },
      "contrib_id": "sha256:contrib2...",
      "syntax": "on_yearly_pulse = { ... }",
      "summary": "Adds 2 new effects, modifies trigger"
    }
  ],
  "merge_capability": "guided_merge",
  "risk": "high",
  "risk_score": 75,
  "uncertainty": "low",
  "reasons": [
    "on_action_hotspot",
    "multiple_mods_touch",
    "effect_block_replacement"
  ]
}
```

### Resolution Choice (user decision)

```json
{
  "conflict_unit_id": "sha256:conflict123...",
  "unit_key": "on_action:on_action:on_yearly_pulse",
  "decision": {
    "type": "custom_merge",
    "winner_candidate_id": null,
    "merge_policy": {
      "keep_unique_ids": true,
      "append_missing_list_items": true,
      "prefer_key_values": [
        {"keypath": "trigger", "candidate_id": "sha256:cand1..."}
      ],
      "deduplicate_by": ["effect_name"],
      "preserve_order": "load_order"
    }
  },
  "notes": "Merged both mod effects, kept vanilla trigger",
  "applied_at": "2024-12-17T10:30:00Z",
  "applied_by": "user",
  "validation_status": "valid"
}
```

### Resolution Plan (complete plan file)

```json
{
  "plan_version": "1.0",
  "created_at": "2024-12-17T10:00:00Z",
  "updated_at": "2024-12-17T10:30:00Z",
  
  "build_config": {
    "playset_id": "my_playset",
    "vanilla_version": "1.13.2",
    "parser_version": "0.7.0",
    "mods": [
      {"mod_id": "mod_a", "name": "Mod A", "version": "2.0"},
      {"mod_id": "mod_b", "name": "Mod B", "version": "1.5"}
    ],
    "load_order": ["mod_a", "mod_b"]
  },
  
  "strategy_preset": "conservative",
  
  "choices": [
    {
      "conflict_unit_id": "sha256:conflict123...",
      "unit_key": "on_action:on_action:on_yearly_pulse",
      "decision": { ... }
    }
  ],
  
  "stats": {
    "total_conflicts": 128,
    "resolved": 120,
    "deferred": 5,
    "expected": 3
  }
}
```

---

## Webview Message Protocol

Communication between extension host and webviews.

### Message Format

```typescript
interface WebviewMessage {
  type: string;
  requestId?: string;  // For request-response pattern
  payload: any;
}
```

### Host → Webview Messages

```typescript
// State updates
{ type: 'state:update', payload: { path: 'explorer.tree.selectedPath', value: 'common/on_action' } }
{ type: 'state:replace', payload: ExplorerState }

// Data responses
{ type: 'data:nodeDetail', requestId: 'req123', payload: NodeDetailState }
{ type: 'data:conflictList', requestId: 'req456', payload: ConflictUnitSummary[] }
{ type: 'data:searchResults', requestId: 'req789', payload: SearchResult[] }

// Progress
{ type: 'progress:build', payload: { phase: 'parsing', current: 50, total: 200 } }
{ type: 'progress:scan', payload: { phase: 'grouping', current: 100, total: 128 } }

// Notifications
{ type: 'notify:info', payload: { message: 'Build complete' } }
{ type: 'notify:error', payload: { message: 'Parse error in file X' } }
```

### Webview → Host Messages

```typescript
// Navigation
{ type: 'nav:selectNode', payload: { nodeId: 'abc123' } }
{ type: 'nav:expandPath', payload: { path: 'common/on_action' } }
{ type: 'nav:openSource', payload: { fileId: 'xyz', line: 42 } }

// Actions
{ type: 'action:build', payload: { playsetId: 'ps1', options: {} } }
{ type: 'action:scanConflicts', payload: { playsetId: 'ps1' } }
{ type: 'action:applyDecision', payload: ResolutionChoice }
{ type: 'action:generateReport', payload: { type: 'conflict_hotspots' } }

// Queries
{ type: 'query:nodeDetail', requestId: 'req123', payload: { nodeId: 'abc123' } }
{ type: 'query:search', requestId: 'req456', payload: { scope: 'symbols', query: 'on_yearly' } }
{ type: 'query:conflictList', requestId: 'req789', payload: { filters: {...}, page: 1 } }

// Merge editor
{ type: 'merge:updatePolicy', payload: MergePolicy }
{ type: 'merge:requestAI', payload: { conflictUnitId: 'xyz', outputContract: 'strict' } }
{ type: 'merge:commit', payload: { conflictUnitId: 'xyz', result: '...' } }
```

---

## Implementation Phases

### Phase 1: Foundation (Current + This Spec)
- [x] ck3raven parser + resolver
- [x] SQLite database schema
- [x] MCP tools for Copilot
- [ ] Unit key extraction per domain
- [ ] Contribution unit storage
- [ ] Basic conflict detection

### Phase 2: Explorer
- [ ] VS Code extension scaffold
- [ ] Activity bar + sidebar webview
- [ ] Tree view with domain/type/node
- [ ] Node detail panel (syntax + AST + provenance)
- [ ] Search (symbols, refs, raw)
- [ ] Uncertainty badges

### Phase 3: Compatch Helper
- [ ] Conflict unit grouping
- [ ] Risk scoring
- [ ] Decision card UI
- [ ] Winner selection
- [ ] Basic merge policies
- [ ] Patch file generation

### Phase 4: Advanced Merge
- [ ] Merge editor (side-by-side)
- [ ] Guided merge controls
- [ ] AI-assisted merge
- [ ] Validation pipeline
- [ ] Audit logging

### Phase 5: Reports + Polish
- [ ] Diff view (build A vs B)
- [ ] Report templates
- [ ] Export (Markdown/JSON)
- [ ] Cryo snapshots
- [ ] Performance optimization

---

## Folder Structure

```
<compatch_project>/
├── descriptor.mod
├── common/
├── events/
├── localization/
└── .ck3lens/
    ├── plan/
    │   ├── resolution_plan.json
    │   ├── conflict_units.json
    │   └── build_manifest.json
    ├── audit/
    │   ├── audit_log.jsonl
    │   └── tool_trace.jsonl
    ├── reports/
    │   ├── validation_report.json
    │   └── diff_reports/
    └── cache/  (gitignored)
        ├── ast/
        └── refs/
```

---

## Risk Scoring Formula

```python
def compute_risk_score(conflict_unit: ConflictUnit) -> int:
    score = 0
    
    # Domain weights
    domain_weights = {
        'on_action': 30,
        'event': 25,
        'gui': 30,
        'scripted_effect': 15,
        'scripted_trigger': 15,
        'decision': 10,
        'define': 15,
        'trait': 10,
        'tradition': 10,
        'localization': 5,
    }
    score += domain_weights.get(conflict_unit.domain, 10)
    
    # Candidate count
    n_candidates = len(conflict_unit.candidates)
    if n_candidates > 2:
        score += 10 * (n_candidates - 2)
    
    # Merge semantics
    if conflict_unit.merge_capability == 'winner_only':
        score += 10  # Higher chance of losing content
    elif conflict_unit.uncertainty != 'none':
        score += 20  # Unknown merge behavior
    
    # Hotspot detection
    if 'on_action_hotspot' in conflict_unit.reasons:
        score += 20
    if 'effect_block_replacement' in conflict_unit.reasons:
        score += 15
    if 'rename_pattern_detected' in conflict_unit.reasons:
        score += 20
    
    # Unknown references
    for candidate in conflict_unit.candidates:
        if candidate.unknown_refs_if_chosen:
            score += 5 * len(candidate.unknown_refs_if_chosen)
    
    return min(score, 100)  # Cap at 100
```

---

## Next Steps

1. Implement unit key extraction in ck3raven
2. Add contribution_units table to SQLite schema
3. Build conflict detection query
4. Create VS Code extension scaffold
5. Implement sidebar webview with state management
