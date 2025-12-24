# CK3 Raven Visualization Feature Design

> **Status:** Design Phase  
> **Last Updated:** December 24, 2025

---

## Overview

A visual interface for exploring the indexed playset, allowing users to:
1. **Navigate** the directory tree of all files in the active playset (vanilla + mods)
2. **View** raw file content alongside parsed/extracted data
3. **Compare** what different mods contribute to the same file path

---

## User Stories

### US-1: Browse Playset Structure
> As a modder, I want to browse the directory tree of my playset so I can understand what files exist and which mods contribute them.

**Acceptance Criteria:**
- Tree view showing folder structure (common/, events/, localization/, etc.)
- Each file shows which source(s) define it (vanilla, mod names)
- Folders can be expanded/collapsed
- File count per folder visible

### US-2: View File with Parsed Data
> As a modder, I want to click a file and see its raw content alongside the parsed AST/symbols/refs so I can understand how ck3raven interprets it.

**Acceptance Criteria:**
- Split panel: raw content on left, parsed data on right
- Right panel tabs: AST, Symbols, Refs, Localization (if applicable)
- Line number correlation between raw and AST
- Syntax highlighting for raw content

### US-3: Compare Mod Contributions  
> As a modder, I want to see when multiple mods define the same file path so I can understand conflicts.

**Acceptance Criteria:**
- Files with multiple sources highlighted in tree
- Click to show all versions with mod names
- Visual diff between versions

---

## Technical Architecture

### Option A: VS Code Webview Extension
**Pros:**
- Native VS Code integration
- Can use existing VS Code UI patterns
- WebView API for custom rendering

**Cons:**
- Requires Extension development
- More complex deployment

### Option B: MCP Tool + Terminal UI
**Pros:**
- Works without extension
- Uses existing MCP infrastructure

**Cons:**
- Limited interactivity
- No true visual tree

### Option C: Local Web Server + Browser
**Pros:**
- Full web capabilities
- Easy to develop/debug
- Can be opened via `open_simple_browser`

**Cons:**
- Separate from VS Code (though can use Simple Browser)
- Need to run server

### Recommended: Option A (VS Code Extension) with Option C as MVP

Start with a local web server that can be opened in VS Code's Simple Browser, then migrate to a proper extension later.

---

## MVP Implementation Plan

### Phase 1: Data API (MCP Tools)
Add MCP tools to expose the needed data:

```python
# Already exists or needs adding:
ck3_get_top_level_folders()     # ✅ Exists
ck3_list_files(folder)          # Need: list files in folder
ck3_get_file_content(file_id)   # Need: get raw content
ck3_get_file_ast(file_id)       # Need: get AST for file
ck3_get_file_symbols(file_id)   # Need: symbols defined in file
ck3_get_file_refs(file_id)      # Need: refs used in file
```

### Phase 2: Web Server
Simple Flask/FastAPI server that:
1. Serves a React/Vue SPA for the tree view
2. Calls ck3raven database directly for data
3. WebSocket for live updates (optional)

```
tools/visualizer/
├── server.py           # FastAPI server
├── static/
│   ├── index.html      # SPA entry
│   ├── app.js          # Tree + panel logic
│   └── styles.css
└── requirements.txt
```

### Phase 3: VS Code Integration
- Command to launch visualizer: `CK3 Raven: Open Visualizer`
- Opens in Simple Browser panel
- Later: migrate to proper WebView

---

## Data Model

### File Tree Node
```typescript
interface TreeNode {
  name: string;           // "common" or "00_traits.txt"
  path: string;           // "common/traits/00_traits.txt"
  type: "folder" | "file";
  children?: TreeNode[];
  sources?: Source[];     // Which mods define this
  hasConflict?: boolean;  // Multiple sources
}

interface Source {
  name: string;           // "vanilla" or "MyMod"
  kind: "vanilla" | "mod";
  file_id: number;
  content_version_id: number;
}
```

### File Detail
```typescript
interface FileDetail {
  file_id: number;
  relpath: string;
  source: Source;
  content: string;        // Raw text
  ast?: ASTNode;          // Parsed AST
  symbols?: Symbol[];     // Extracted symbols
  refs?: Ref[];           // Extracted refs
  localization?: LocEntry[]; // If yml file
}
```

---

## UI Mockup

```
┌─────────────────────────────────────────────────────────────────────┐
│ CK3 Raven Explorer                                    [Active: MSC] │
├──────────────────────┬──────────────────────────────────────────────┤
│ 📁 common            │ Raw Content          │ Parsed Data          │
│   📁 traits          │                      │ [AST] [Symbols] [Refs]│
│     📄 00_traits.txt │ trait = {            │ ┌─ BlockNode: trait  │
│   📁 on_action       │   name = "brave"     │ │  name: "brave"     │
│ 📁 events            │   opposites = {      │ │  ├─ opposites      │
│   📄 birth_events.txt│     craven           │ │  │  └─ craven      │
│ 📁 localization      │   }                  │ │  ├─ monthly_pres...│
│ 📁 gfx               │   monthly_prestige = │ └─ ...               │
│                      │ }                    │                      │
└──────────────────────┴──────────────────────┴──────────────────────┘
```

---

## MCP Tools to Add

### ck3_list_folder
```python
def ck3_list_folder(folder: str, include_subfolders: bool = True) -> dict:
    """
    List files and subfolders in a playset folder.
    
    Args:
        folder: Folder path like "common/traits" or ""
        include_subfolders: Whether to recurse
    
    Returns:
        {
            "folder": str,
            "children": [
                {"name": str, "type": "folder"|"file", "sources": [...]}
            ]
        }
    """
```

### ck3_get_file_detail
```python
def ck3_get_file_detail(file_id: int) -> dict:
    """
    Get complete detail for a file: content, AST, symbols, refs.
    
    Returns:
        {
            "file_id": int,
            "relpath": str,
            "source": {"name": str, "kind": str},
            "content": str,
            "ast": {...},
            "symbols": [...],
            "refs": [...]
        }
    """
```

---

## Implementation Timeline

| Week | Milestone |
|------|-----------|
| 1 | Add MCP tools: ck3_list_folder, ck3_get_file_detail |
| 2 | Create basic FastAPI server with static HTML |
| 3 | Add React tree component with expand/collapse |
| 4 | Add split panel with raw content view |
| 5 | Add AST/Symbols/Refs tabs |
| 6 | Polish, testing, VS Code command integration |

---

## Open Questions

1. **Should we use TypeScript React or vanilla JS?**
   - React gives better tree handling but adds build complexity
   - Vanilla JS simpler but harder to maintain

2. **How to handle very large files?**
   - Virtualized scrolling for content
   - Lazy load AST nodes

3. **Should the server be a separate process or integrated?**
   - Separate: cleaner architecture
   - Integrated: easier to start/stop

4. **Caching strategy?**
   - Cache file content in browser
   - Invalidate on database rebuild

---

## Related Files

- `tools/ck3lens_mcp/server.py` - Existing MCP server
- `src/ck3raven/db/` - Database layer
- `.github/COPILOT_RAVEN_DEV.md` - Mode instructions
