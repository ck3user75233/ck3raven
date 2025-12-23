# Paradox Script Parser Landscape

> Research summary of existing parsers for Clausewitz/Paradox script format.

---

## The Clausewitz Format

Paradox Development Studio games (EU4, CK3, HOI4, Stellaris, Victoria, Imperator) use a proprietary text format for game files. It's **undocumented** and has many edge cases.

### Basic Syntax

```
# Comment
key = value
key = "quoted string"
key = 123
key = 1.5
key = yes
key = no
key = 1444.11.11  # date

block = {
    nested_key = value
}

list = { item1 item2 item3 }

# Operators beyond =
age > 16
intrigue >= high_skill_rating
```

### Edge Cases (from pdx.tools blog)

| Edge Case | Example | Notes |
|-----------|---------|-------|
| Duplicate keys | `core=A` then `core=B` | Both valid, creates list |
| Missing operator | `foo{bar=qux}` | Equals `foo={bar=qux}` |
| Empty braces | `discovered_by={}` | Could be array or object |
| Mixed array/object | `{ 169 170 color={1 2 3} }` | Array with embedded object |
| Trailing braces | `a={1} } b=2` | Valid in some games |
| Unmarked lists | `pattern = list "items"` | CK3/Imperator specific |
| Color syntax | `rgb { 100 200 150 }` | External tag on object |
| Parameter syntax | `[[var] code ]` | EU4 Dharma+ |
| Interpolation | `@[1-leo_x]` | Variable expressions |

---

## Parser Comparison

### 1. jomini (Rust) - Performance King

**Repository**: https://github.com/rakaly/jomini

**Approach**: Tape-based parsing (like simdjson)
- Tokenize into a "tape" of events
- Caller decides what to do with tokens
- Can deserialize directly to structs via derive macros

**Key Features**:
- ✅ 1+ GB/s parsing speed
- ✅ Handles binary AND text formats
- ✅ Zero-copy where possible
- ✅ Serde-like derive macros
- ✅ Extensively fuzzed

**Architecture**:
```rust
// Low-level: tape
let tape = TextTape::from_slice(data)?;
let reader = tape.windows1252_reader();
for (key, op, value) in reader.fields() { ... }

// High-level: derive
#[derive(JominiDeserialize)]
struct Model {
    human: bool,
    #[jomini(duplicated)]
    cores: Vec<String>,
}
let model: Model = from_slice(data)?;
```

**Lessons for ck3raven**:
- Don't force full AST - provide multiple levels of abstraction
- Tape parsing is memory-efficient for large files
- Derive macros make extraction declarative

---

### 2. CWTools (F#) - Validation Champion

**Repository**: https://github.com/cwtools/cwtools

**Approach**: Full AST + schema-driven validation
- Parse into typed AST
- Apply game-specific schemas for validation
- Powers the cwtools VS Code extension

**Key Features**:
- ✅ Full AST with source locations
- ✅ Schema-based validation
- ✅ Error recovery (continues after errors)
- ✅ Supports all Paradox games
- ✅ Round-trip capable (preserve comments)

**Architecture**:
```fsharp
// Parse
let parsed = CKParser.parseEventFile("./event.txt")
let eventFile = parsed.GetResult()

// Process into domain model
let processed = CK2Process.processEventFile(eventFile)

// Modify
myEvent.AllChildren.Add(Leaf.Create("is_triggered_only", Value.NewBool(true)))

// Output
CKPrinter.printKeyValueList(processed.ToRaw, 0)
```

**Lessons for ck3raven**:
- Schema-driven validation catches modding errors
- Separate parsing from game-specific processing
- AST needs source locations for diagnostics
- Comment preservation enables round-tripping

---

### 3. pyradox (Python) - Simple Python Parser

**Repository**: https://github.com/ajul/pyradox

**Approach**: Regex tokenizer + state machine parser
- Tokenize with regex patterns
- Parse with explicit state machine
- Output is `Tree` class (dict + ElementTree hybrid)

**Key Features**:
- ✅ Pure Python
- ✅ Handles color syntax specially
- ✅ Comment preservation
- ✅ Directory/merge parsing utilities

**Architecture**:
```python
# Token patterns
token_types = [
    ('whitespace', r'\s+'),
    ('operator', r'<=?|>=?|='),
    ('begin', r'\{'),
    ('end', r'\}'),
    ('comment', r'#.*'),
    ...
]

# Parse
tree = txt.parse_file("common/traits/00_traits.txt")

# Access
for key, value in tree.items():
    print(key, value)
```

**State Machine**:
```python
class TreeParseState:
    def __init__(self, ...):
        self.next = self.process_key  # Start state
    
    def parse(self):
        while self.next is not None:
            self.next()  # State transition
    
    def process_key(self):
        # Read key, transition to process_operator
    
    def process_operator(self):
        # Read operator, transition to process_value
    
    def process_value(self):
        # Read value (may recurse), transition to process_key
```

**Lessons for ck3raven**:
- State machine is explicit and debuggable
- Lookahead needed to distinguish tree vs group
- Color syntax needs special handling
- Warnings (not errors) for recoverable issues

---

### 4. jomini.js (JavaScript/WASM)

**Repository**: https://github.com/nickbabcock/jomini.js

**Approach**: WASM wrapper around Rust jomini
- Brings jomini's speed to JS/browser
- Good for web-based tools

**Lessons**: Can embed Rust parsers in other environments via WASM.

---

## Parsing Strategies

### Strategy A: Full AST (CWTools, current ck3raven)

```
Source → Lexer → Parser → AST → Process
```

**Pros**:
- Full structure preserved
- Can modify and write back
- Supports complex queries

**Cons**:
- Memory intensive
- Slower for simple extraction
- Overkill for lookup tables

### Strategy B: Tape/Event Parsing (jomini)

```
Source → Tape → Reader → Extract what you need
```

**Pros**:
- Very fast
- Memory efficient
- Flexible - caller decides depth

**Cons**:
- Harder to implement
- Less intuitive API

### Strategy C: Direct Deserialization (jomini derive)

```
Source → Deserializer → Target Struct
```

**Pros**:
- Most efficient for known structures
- No intermediate representation
- Type-safe

**Cons**:
- Requires knowing structure ahead of time
- Less flexible for exploration

### Strategy D: Hybrid (Proposed for ck3raven)

```
Source → Lexer → Router → { Full AST | Lookup Extractor | Skip }
```

**Pros**:
- Right tool for each job
- Efficient for lookup data
- Full power for scripts

**Cons**:
- More complex codebase
- Multiple paths to maintain

---

## Recommended Approach for ck3raven

### 1. Keep the Lexer

The existing lexer is good. Tokenization is the same regardless of output format.

### 2. Add Extraction Modes

```python
# Mode 1: Full AST (current)
ast = parse_source(content, filename)

# Mode 2: Lookup extraction (new)
lookups = extract_lookups(content, filename, schema={
    'key': 'id',
    'fields': ['name', 'culture', 'religion']
})

# Mode 3: Stream (future, jomini-style)
for event in parse_stream(content):
    if event.type == 'key' and event.value == 'trait':
        ...
```

### 3. Per-Folder Routing

```python
FOLDER_CONFIG = {
    'events/': {'mode': 'full_ast', 'extract': ['events']},
    'common/traits/': {'mode': 'full_ast', 'extract': ['traits']},
    'common/dynasties/': {'mode': 'lookup', 'schema': dynasty_schema},
    'history/provinces/': {'mode': 'lookup', 'schema': province_schema},
    'localization/': {'mode': 'localization'},  # Different parser entirely
}
```

### 4. Study jomini for Patterns

Even if we stay in Python, jomini's patterns are valuable:
- Tape structure for memory efficiency
- Derive-style declarative extraction
- Multi-level API (low/mid/high)

---

## Resources

- **Clausewitz syntax tour**: https://pdx.tools/blog/a-tour-of-pds-clausewitz-syntax
- **CWTools wiki**: https://github.com/cwtools/cwtools/wiki
- **CWTools source**: https://github.com/cwtools/cwtools (F# - requires .NET)
- **jomini docs**: https://docs.rs/jomini
- **jomini source**: https://github.com/rakaly/jomini (Rust)
- **awesome-paradox**: https://github.com/hmlendea/awesome-paradox

---

## Deep Dive: CWTools

CWTools is the most feature-complete Paradox modding toolchain. It powers the **cwtools VS Code extension** used by serious modders.

### Why Study CWTools?

1. **Schema-driven validation** - CWTools uses `.cwt` schema files that define what's valid in each context
2. **Error recovery** - Continues parsing after errors, collects all diagnostics
3. **Game-specific processing** - Separate layer transforms AST into game domain models
4. **VS Code integration** - Provides autocomplete, hover, diagnostics

### CWTools Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CWTools Pipeline                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Source File (.txt)                                                  │
│       ↓                                                              │
│  CKParser.parseFile()  → Raw AST (Statement[])                       │
│       ↓                                                              │
│  CK2Process / STLProcess  → Domain Model (Event, Trait, etc.)        │
│       ↓                                                              │
│  Schema Validation  → Diagnostics                                    │
│       ↓                                                              │
│  Output: Modified files, error reports                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### CWTools Schema Files (.cwt)

CWTools uses declarative schemas to validate game files:

```
# From triggers.cwt
trigger = {
    is_ai = bool
    age >= int
    has_trait = <trait>
    any_child = { ... }
}
```

This means:
- `is_ai` must be a boolean
- `age` comparison takes an int
- `has_trait` references a trait (validated against known traits)
- `any_child` is a scope that contains more triggers

**Applicability to ck3raven**: We could adopt schema-driven validation to catch undefined symbols, wrong argument types, etc.

### CWTools Limitations

- **F# codebase** - Not directly usable in Python
- **Complex build** - Requires .NET SDK
- **Schema maintenance** - Schemas need updates with each game patch

### What We Can Learn

1. **Error recovery pattern** - Don't stop at first error
2. **Schema design** - How to express "X must reference a valid trait"
3. **Scope tracking** - How scopes (ROOT, FROM, PREV) are validated
4. **Localization integration** - How loc keys are validated

---

## Deep Dive: jomini (Rust)

jomini is the fastest Paradox file parser. It powers **pdx.tools** (EU4/CK3 online analyzer).

### Why Study jomini?

1. **Performance** - 1+ GB/s parsing speed
2. **Correctness** - Extensively fuzzed, handles all edge cases
3. **Flexibility** - Multiple abstraction levels (tape, mid-level, deserialize)
4. **Binary support** - Handles binary save files too

### jomini Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        jomini Layers                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Layer 1: TextTape / BinaryTape                                      │
│    - Low-level token stream                                          │
│    - Zero-copy parsing                                               │
│    - Memory efficient (tape is flat array)                           │
│                                                                      │
│  Layer 2: Reader API                                                 │
│    - Iterate over fields: (key, operator, value)                     │
│    - Navigate nested structures                                      │
│    - Read values as specific types                                   │
│                                                                      │
│  Layer 3: JominiDeserialize                                          │
│    - Derive macro for structs                                        │
│    - Automatic deserialization                                       │
│    - Handles duplicates, optionals, aliases                          │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Tape Parsing Explained

Instead of building a tree, jomini writes tokens to a flat "tape":

```
Input: "a = { b = 1 }"

Tape: [OBJECT_START, KEY("a"), OBJECT_START, KEY("b"), VALUE(1), OBJECT_END, OBJECT_END]
```

Benefits:
- **Cache-friendly** - sequential memory access
- **Low allocation** - one buffer, not many nodes
- **Selective parsing** - skip sections you don't need

### JominiDeserialize Derive Macro

```rust
#[derive(JominiDeserialize)]
struct Province {
    culture: String,
    religion: String,
    #[jomini(duplicated)]
    buildings: Vec<String>,
    #[jomini(default)]
    population: u32,
}
```

This is similar to what we'd want for lookup extraction - declare the schema, let the extractor pull data.

### Applicability to ck3raven

**Direct use**: Could use jomini via PyO3 (Python bindings for Rust) or WASM
- Pros: Battle-tested, fast
- Cons: Rust dependency, build complexity

**Pattern adoption**: Implement jomini-like patterns in Python
- Tape-style parsing for large files
- Declarative extraction (Python dataclasses instead of derive)
- Multi-level API

### Recommended Investigation

1. Read jomini's `src/text/tape.rs` - understand tape structure
2. Read jomini's `src/text/de.rs` - understand deserialization
3. Consider: Could we call jomini from Python via PyO3?
4. Consider: Could we use jomini.js in validation tooling?

---

## Next Steps

1. **Audit current parser** - Compare against pdx.tools edge cases
2. **Prototype lookup extractor** - Test on province files  
3. **Benchmark** - How long does current parser take on full vanilla?
4. **CWTools schema study** - Can we adopt their .cwt format?
5. **jomini integration options** - PyO3, WASM, or pattern adoption?
