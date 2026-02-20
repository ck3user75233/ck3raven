# Syntax Validator Feature Research

This document compares CK3Raven's validation capabilities against industry-leading syntax validators and linters.

## Best-in-Class Validators Analyzed

- **ESLint** - JavaScript/TypeScript linter
- **Pylint** - Python static analysis
- **Semgrep** - Multi-language pattern matching
- **LSP (Language Server Protocol)** - Editor integration standard

---

## Feature Comparison Matrix

### 1. Core Parsing & Diagnostics

| Feature | ESLint | Pylint | Semgrep | CK3Raven | Gap |
|---------|--------|--------|---------|----------|-----|
| Parse to AST | ✅ | ✅ | ✅ | ✅ | Complete |
| Syntax error detection | ✅ | ✅ | ✅ | ✅ | Complete |
| Line/column positions | ✅ | ✅ | ✅ | ✅ | Complete |
| Error severity levels | ✅ | ✅ | ✅ | ✅ | Complete via ParseDiagnostic |
| Multiple error recovery | ✅ | ✅ | N/A | ✅ | Complete via RecoveringParser |
| BOM handling | ✅ | ✅ | ✅ | ✅ | Fixed via utf-8-sig |

### 2. Semantic Analysis

| Feature | ESLint | Pylint | Semgrep | CK3Raven | Gap |
|---------|--------|--------|---------|----------|-----|
| Reference validation | ✅ | ✅ | ✅ | ✅ | Complete via `semantic.py` |
| Type checking | ✅ | ✅ | ✅ | ⚠️ | Scope type tracking started |
| Scope analysis | ✅ | ✅ | ✅ | ✅ | ScopeContext implemented |
| Unused code detection | ✅ | ✅ | ✅ | ❌ | Dead code detection |
| Undefined reference warnings | ✅ | ✅ | ✅ | ✅ | Complete with suggestions |

### 3. Code Actions & Fixes

| Feature | ESLint | Pylint | Semgrep | CK3Raven | Gap |
|---------|--------|--------|---------|----------|-----|
| Auto-fix (safe) | ✅ | N/A | ✅ | ❌ | **Major gap** |
| Suggestions (unsafe) | ✅ | ✅ | ✅ | ❌ | Quick-fix suggestions |
| Refactoring support | ✅ | ✅ | ✅ | ❌ | Rename, extract |

### 4. LSP Integration

| Feature | ESLint | Pylint | Semgrep | CK3Raven | Gap |
|---------|--------|--------|---------|----------|-----|
| `textDocument/diagnostic` | ✅ | ✅ | N/A | ⚠️ | MCP tools ready, need LSP server |
| `textDocument/codeAction` | ✅ | ✅ | N/A | ❌ | Quick fixes in editor |
| `textDocument/hover` | ✅ | ✅ | N/A | ✅ | Complete via MCP tool |
| `textDocument/definition` | ✅ | ✅ | N/A | ✅ | Complete via MCP tool |
| `textDocument/references` | ✅ | ✅ | N/A | ❌ | Find all usages |
| `textDocument/completion` | ✅ | ✅ | N/A | ✅ | Complete via MCP tool |
| `textDocument/semanticTokens` | ✅ | ✅ | N/A | ❌ | Smart highlighting |
| `textDocument/formatting` | ✅ | ✅ | N/A | ❌ | Code formatting |

### 5. Rules & Configuration

| Feature | ESLint | Pylint | Semgrep | CK3Raven | Gap |
|---------|--------|--------|---------|----------|-----|
| Rule severity config | ✅ | ✅ | ✅ | ❌ | Need .ck3lintrc |
| Custom rules | ✅ | ✅ | ✅ | ❌ | Rule plugin system |
| Rule disable comments | ✅ | ✅ | ✅ | ❌ | `# ck3lint-disable` |
| Shareable configs | ✅ | ✅ | ✅ | ❌ | Preset rule packs |

### 6. CK3-Specific Features (Unique)

| Feature | Status | Notes |
|---------|--------|-------|
| Trigger/effect validation | ⚠️ | Have known triggers/effects in schema |
| Scope chain validation | ❌ | Need scope_type tracking per context |
| Event namespace collision | ❌ | Detect duplicate event IDs |
| Localization key validation | ❌ | Check loc keys exist |
| Conflict detection | ✅ | Unit-level conflicts working |
| Cascading error detection | ✅ | Patterns identified |
| Mod load order awareness | ✅ | Playset system |
| Override detection | ✅ | Know when mod overrides vanilla |

---

## Current CK3Raven Strengths

### What We Have

1. **Custom Parser with Full AST**
   - Complete CK3 script parser
   - AST node types: Block, Assignment, Value, Root
   - Line/column tracking

2. **Symbol Database**
   - 100K+ symbols indexed
   - Mod/vanilla separation
   - Symbol types: trait, decision, event, trigger, effect, etc.

3. **Conflict Detection**
   - Unit-level conflict scanning
   - Risk scoring
   - Resolution tracking

4. **Error Analysis**
   - Error.log parsing
   - Priority categorization
   - Cascading error patterns
   - Mod attribution

5. **Validation Infrastructure**
   - `parse_content()` - Parse and return AST or errors
   - `lint_file()` - Bridge server linting stub

### What We Can Build (Have Foundations)

1. **Reference Validation**
   - Have: Symbol database with all definitions
   - Need: Cross-reference check in parsed AST

2. **Trigger/Effect Validation**
   - Have: Known triggers/effects indexed
   - Need: Context-aware validation (scope types)

3. **Auto-complete**
   - Have: Symbol search with adjacency
   - Need: LSP completion provider

4. **Hover Documentation**
   - Have: Symbol metadata (source, line, mod)
   - Need: LSP hover provider

---

## Recommended Development Roadmap

### Phase 1: Complete Core Validation (Priority: HIGH) ✅ IMPLEMENTED

1. **Reference Validation** ✅
   ```
   - Cross-check all identifiers against symbol DB
   - Report undefined triggers/effects/events/traits
   - Suggest similar symbols for typos (Levenshtein distance)
   ```
   Implemented in: `ck3lens/semantic.py` → `SemanticAnalyzer.validate_references()`

2. **Scope Type Validation** ✅
   ```
   - Track scope context (character, title, etc.)
   - Validate triggers/effects are valid for scope
   - Report scope mismatches
   ```
   Implemented: `ScopeContext` class with scope changers, trigger/effect context

3. **Autocomplete** ✅
   ```
   - Complete symbol names after reference keys
   - Context-aware suggestions (traits after has_trait=)
   - Scope changers and keywords completion
   ```
   Implemented: `ck3lens/semantic.py` → `SemanticAnalyzer.get_completions()`
   MCP Tool: `ck3_get_completions(content, line, column)`

4. **Hover Documentation** ✅
   ```
   - Show symbol type and source mod
   - Definition file and line number
   - Markdown-formatted output
   ```
   Implemented: `ck3lens/semantic.py` → `SemanticAnalyzer.get_hover()`
   MCP Tool: `ck3_get_hover(content, line, column)`

5. **Go to Definition** ✅
   ```
   - Return definition file path and line
   - Handle vanilla and mod symbols
   ```
   Implemented: `ck3lens/semantic.py` → `SemanticAnalyzer.get_definition()`
   MCP Tool: `ck3_get_definition(content, line, column)`

6. **Parser Error Recovery** ✅
   ```
   - Continue parsing after first error
   - Collect all errors in single pass
   - Return partial AST even with errors
   ```
   Implemented: `ck3raven/parser/parser.py` → `RecoveringParser` class
   - `parse_source_recovering()` - Returns `ParseResult` with AST + all diagnostics
   - Recovery strategies: skip to next line, skip to matching brace
   - Maximum 100 errors before stopping

**New MCP Tools Added:**
- `ck3_validate_references` - Full semantic validation
- `ck3_get_completions` - Autocomplete at cursor
- `ck3_get_hover` - Documentation at cursor
- `ck3_get_definition` - Jump to definition

### Phase 2: LSP Server (Priority: HIGH)

1. **Upgrade Bridge Server to Full LSP**
   ```
   - Use python-lsp-server or pygls
   - Implement core LSP methods
   - Real-time diagnostics on save
   ```

2. **Diagnostics (`textDocument/publishDiagnostics`)**
   ```
   - Push errors/warnings to editor
   - Severity levels (error, warning, info, hint)
   - Related information links
   ```

3. **Hover (`textDocument/hover`)**
   ```
   - Show symbol documentation
   - Source file and line
   - Mod attribution
   ```

4. **Go to Definition (`textDocument/definition`)**
   ```
   - Jump to symbol source
   - Handle vanilla and mod files
   ```

5. **Completion (`textDocument/completion`)**
   ```
   - Autocomplete triggers/effects
   - Complete event IDs, trait names
   - Context-aware suggestions
   ```

### Phase 3: Code Actions (Priority: MEDIUM)

1. **Quick Fixes**
   ```
   - Fix typos with suggestions
   - Add missing blocks
   - Fix scope mismatches
   ```

2. **Refactoring**
   ```
   - Rename symbol across files
   - Extract to scripted_trigger/effect
   - Inline scripted_trigger/effect
   ```

3. **Code Formatting**
   ```
   - Consistent indentation
   - Block spacing
   - Comment alignment
   ```

### Phase 4: Rule Engine (Priority: LOW)

1. **Custom Rules**
   ```
   - Pattern-based rules (like Semgrep)
   - AST query language
   - Rule metadata (severity, fix, docs)
   ```

2. **Configuration File**
   ```
   # .ck3lintrc
   rules:
     undefined-reference: error
     unused-variable: warning
     scope-mismatch: error
   ```

3. **Disable Comments**
   ```
   # ck3lint-disable-next-line undefined-reference
   some_undefined_thing = yes
   ```

---

## LSP Implementation Notes

### Recommended Stack

```
pygls (Python Language Server Library)
├── LSP protocol handling
├── JSON-RPC server
└── Document synchronization

ck3raven parser + database
├── AST generation
├── Symbol resolution
└── Validation rules
```

### Key LSP Capabilities to Implement

```json
{
  "capabilities": {
    "textDocumentSync": "incremental",
    "completionProvider": {
      "triggerCharacters": ["=", " ", "."]
    },
    "hoverProvider": true,
    "definitionProvider": true,
    "referencesProvider": true,
    "documentSymbolProvider": true,
    "diagnosticProvider": {
      "interFileDependencies": true,
      "workspaceDiagnostics": false
    },
    "codeActionProvider": {
      "codeActionKinds": ["quickfix", "refactor"]
    }
  }
}
```

---

## Priority Features by Impact

### Highest Impact (Implement First)

1. **Reference validation** - Catch undefined symbols
2. **LSP diagnostics** - Real-time feedback in editor
3. **Autocomplete** - Productivity boost

### Medium Impact

4. **Hover documentation** - Symbol info on demand
5. **Go to definition** - Navigation
6. **Quick fixes** - Auto-repair common issues

### Lower Impact (Nice to Have)

7. **Custom rules** - Team coding standards
8. **Formatting** - Style consistency
9. **Semantic highlighting** - Prettier code

---

## Appendix: ESLint Rule Categories (Reference)

ESLint organizes rules into categories that we can adapt:

1. **Possible Problems** - Code that may cause bugs
   - CK3: Undefined references, scope mismatches

2. **Suggestions** - Better code patterns
   - CK3: Use scripted_trigger instead of repeated conditions

3. **Layout & Formatting** - Style consistency
   - CK3: Indentation, block spacing

We should define similar categories for CK3 rules.

---

*Generated: December 2024*
*CK3Raven Syntax Validator Research*
