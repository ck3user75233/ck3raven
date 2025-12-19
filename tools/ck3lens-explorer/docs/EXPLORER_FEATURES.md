# CK3 Lens Explorer - Feature Roadmap

## Overview

The CK3 Lens Explorer provides a unified UI for navigating, viewing, creating, and editing CK3 mod files, all powered by the ck3raven database. The explorer is **playset-aware** - everything shown is in the context of a specific playset (vanilla + mods in load order).

---

## Core Modules

### 1. Explorer View ✅ Scaffolded | 🔄 Database Integration In Progress

The primary navigation view for browsing files in the current playset.

#### 1.1 Database-Driven Tree
| Feature | Status | Description |
|---------|--------|-------------|
| Playset selector | 🔲 | Quick-pick to choose active playset |
| Mod tree hierarchy | 🔲 | Show mods in load order (0=vanilla, 1=first mod, etc.) |
| Folder tree | 🔲 | Group files by folder path (`common/culture/`, `events/`, etc.) |
| File nodes | 🔲 | Show individual files with source mod badge |
| Load order indicator | 🔲 | Visual indicator of which mod "wins" for each file |

#### 1.2 Filtering & Search
| Feature | Status | Description |
|---------|--------|-------------|
| Folder filter | 🔲 | Show only files in specific folders (e.g., `on_action`, `localization`) |
| Symbol search | 🔲 | Filter files containing specific symbols (traits, events, etc.) |
| Text search | 🔲 | Filter files containing text strings |
| Fuzzy matching | 🔲 | Near-match text search (leveraging FTS5) |
| Regex search | 🔲 | Advanced pattern matching |
| Multi-filter combine | 🔲 | AND/OR combinations of filters |
| Save filter presets | 🔲 | Store frequently used filter combinations |

#### 1.3 View Modes
| Feature | Status | Description |
|---------|--------|-------------|
| By load order | 🔲 | Show mods in order (default) |
| Alphabetical | 🔲 | Sort files/folders A-Z |
| By content type | 🔲 | Group by parser content type (events, decisions, cultures, etc.) |
| Conflicts only | 🔲 | Show only files/symbols with conflicts |

#### 1.4 Provenance Display
| Feature | Status | Description |
|---------|--------|-------------|
| Source badge | 🔲 | Badge showing source mod for each file |
| Override indicator | 🔲 | Visual indicator when file overrides another |
| Conflict count | 🔲 | Show number of conflicts for each file |

---

### 2. AST Viewer Panel ✅ Complete

Webview panel for viewing file content with syntax highlighting and AST toggle.

| Feature | Status | Description |
|---------|--------|-------------|
| Syntax view | ✅ | Raw file content with highlighting |
| AST view | ✅ | JSON tree of parsed AST |
| View toggle | ✅ | Switch between Syntax ⇄ AST |
| Line navigation | ✅ | Click AST node → jump to source line |
| Copy AST | ✅ | Copy AST JSON to clipboard |
| Reveal in Explorer | ✅ | Open file location in VS Code explorer |
| Open in Editor | ✅ | Open file in standard text editor |
| Parse error display | ✅ | Show errors with clickable line numbers |

#### Future Enhancements
| Feature | Status | Description |
|---------|--------|-------------|
| Provenance timeline | 🔲 | Show which mod contributed each definition |
| Symbol highlighting | 🔲 | Highlight symbol definitions/references |
| Cross-reference links | 🔲 | Click symbols to navigate to definitions |
| Diff view | 🔲 | Compare with other versions of same file |

---

### 3. Studio Panel (Create/Edit) ✅ Complete

**Name: "CK3 Studio"** - The creation and editing workspace, accessible via `Ctrl+Alt+N` or command palette.

#### 3.1 File Operations
| Feature | Status | Description |
|---------|--------|-------------|
| Create new file | ✅ | Create file in live mod directory |
| Edit existing file | ✅ | Opens in VS Code editor after creation |
| Save with validation | ✅ | Validates syntax before writing |
| File templates | ✅ | 11 templates (event, decision, trait, culture, tradition, religion, on_action, scripted_effect, scripted_trigger, character_interaction, empty) |
| Copy from vanilla | ✅ | Clone vanilla file to mod for override |

#### 3.2 Real-Time Validation
| Feature | Status | Description |
|---------|--------|-------------|
| Syntax validation | ✅ | Parse errors shown as you type (500ms debounce) |
| Symbol recognition | 🔲 | Highlight defined symbols |
| Reference validation | 🔲 | Warn on undefined symbol references |
| Scope validation | 🔲 | Check trigger/effect scope correctness |
| Localization check | 🔲 | Warn on missing localization keys |

#### 3.3 Intelligent Assistance
| Feature | Status | Description |
|---------|--------|-------------|
| Autocomplete | 🔲 | Complete trigger/effect names |
| Hover documentation | 🔲 | Show docs on hover |
| Parameter hints | 🔲 | Show expected parameters for blocks |
| Snippet insertion | 🔲 | Insert common patterns |
| Quick fixes | 🔲 | Auto-fix common errors |

#### 3.4 Live Mod Management
| Feature | Status | Description |
|---------|--------|-------------|
| Mod whitelist | ✅ | Only edit whitelisted mods |
| Git integration | ✅ | Status, commit, push/pull via MCP |
| Change tracking | 🔲 | Show unsaved changes |
| Revert to database | 🔲 | Restore file from DB version |

---

### 4. Compatch Module 🔲 Not Started

Advanced conflict resolution with AI assistance. **Builds on Studio features.**

#### 4.1 Conflict Detection
| Feature | Status | Description |
|---------|--------|-------------|
| File-level conflicts | ✅ | Same relpath in multiple mods (DB query ready) |
| ID-level conflicts | ✅ | Same symbol in multiple mods (unit extraction ready) |
| Risk scoring | ✅ | Severity classification (MCP tool ready) |
| Conflict grouping | 🔲 | Group related conflicts for batch resolution |

#### 4.2 Resolution UI
| Feature | Status | Description |
|---------|--------|-------------|
| Decision cards | 🔲 | Visual cards for each conflict |
| Winner selection | 🔲 | Pick which mod wins |
| Merge preview | 🔲 | Preview merged result before applying |
| Merge editor | 🔲 | Side-by-side merge with editable output |
| AI-assisted merge | 🔲 | Agent generates merge proposal |

#### 4.3 Batch Operations
| Feature | Status | Description |
|---------|--------|-------------|
| Bulk winner selection | 🔲 | "Keep all from ModX" for entire folder |
| Merge policy override | 🔲 | Override default merge policy per file |
| Conflict workflow | 🔲 | Guided step-by-step resolution |
| Autopilot mode | 🔲 | AI resolves with minimal guidance |

#### 4.4 Patch Generation
| Feature | Status | Description |
|---------|--------|-------------|
| Patch file generation | 🔲 | Create compatch mod files |
| Audit log | 🔲 | Document all resolution decisions |
| Validation pipeline | 🔲 | Validate generated patch against vanilla+mods |
| Descriptor generation | 🔲 | Auto-generate descriptor.mod |

---

### 5. Reports View 🔲 Not Started

Summary and analytics views.

| Feature | Status | Description |
|---------|--------|-------------|
| Conflict summary | 🔲 | Overview of all conflicts by severity |
| Coverage report | 🔲 | What % of files are conflicted |
| Mod dependency graph | 🔲 | Visualize mod relationships |
| Resolution progress | 🔲 | Track compatch completion |
| Export report | 🔲 | Export to markdown/HTML |

---

### 6. Floating Widget ✅ Complete

Status bar and control overlay.

| Feature | Status | Description |
|---------|--------|-------------|
| Status bar item | ✅ | Always-visible lens/mode/agent status |
| Widget panel | ✅ | Full control panel |
| Mode switching | ✅ | ck3lens / ck3raven-dev / ck3creator |
| Agent engagement | ✅ | Toggle AI agent on/off |
| MCP status | ✅ | Connection status with reconnect |
| Keybindings | ✅ | Ctrl+Alt+L/M/A/W |

---

## Data Model

All features are powered by the ck3raven database:

### Provenance Chain
```
Playset
  └── PlaysetMod (load_order)
        └── ModPackage
              └── ContentVersion
                    └── ModFile (relpath, content_hash)
                          └── FileContent (content_text / ast_json)
                                └── Symbols/References
```

Every piece of content is traceable back to:
1. **Which playset** is active
2. **Which mod** contributed it
3. **What load order position** that mod is in
4. **Original file path** on disk
5. **Content hash** for deduplication

### Key Tables
- `playsets` - Named playset configurations
- `playset_mods` - Mod membership with load_order
- `mod_packages` - Mod metadata
- `content_versions` - Snapshot of mod state
- `mod_files` - File records with relpath + content_hash
- `file_contents` - Deduplicated content storage
- `symbols` / `symbol_refs` - Extracted definitions and references

---

## Implementation Priority

### Phase 1: Foundation (Current)
1. ✅ AST Viewer Panel
2. ✅ Floating Widget
3. 🔄 Database-driven Explorer tree
4. 🔲 Basic file filtering

### Phase 2: Studio (Next)
1. 🔲 Create/edit file in live mod
2. 🔲 Real-time syntax validation
3. 🔲 Symbol recognition + hover docs
4. 🔲 Autocomplete

### Phase 3: Enhanced Explorer
1. 🔲 Advanced filtering (symbol, text, regex)
2. 🔲 Provenance display
3. 🔲 Conflict indicators

### Phase 4: Compatch
1. 🔲 Conflict detection UI
2. 🔲 Decision cards + resolution
3. 🔲 AI-assisted merge
4. 🔲 Patch generation

---

## Agent Integration

Both `ck3lens` and `ck3lens-live` agents can leverage Studio features via MCP:

| MCP Tool | Studio Feature |
|----------|----------------|
| `validate_script` | Real-time syntax validation |
| `search_symbols` | Symbol recognition |
| `write_live_file` | Create/edit in live mod |
| `get_file_content` | View file content |
| `get_ast` | Parse and inspect AST |
| `unit_conflicts_*` | Conflict detection |

The widget tracks agent engagement status and all Studio operations are logged for auditability.
