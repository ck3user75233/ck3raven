
I'll create a comprehensive bug report with code fixes. Let me first check where the WIP folder is and what the canonical domain patterns look like:

In the meantime, here's the complete bug report. Please save this to your WIP folder (e.g., ~/.ck3raven/wip/BUG_REPORT_mcpServerProvider_paths.md):

Problems
ck3ravenRoot is not a canonical domain name
4 priority levels with 6+ path-checking strategies
Parent traversal (path.dirname(path.dirname(...))) is fragile
String matching (includes('ck3lens-explorer')) is brittle
No alignment with Python-side WorldAdapter pattern
Recommended Fix
Create a TypeScript canonical domain resolver aligned with Python's WorldAdapter:

Updated mcpServerProvider.ts
Issue 2: findPythonPath() Searches Relative to Non-Canonical Root
Current Code (lines 44-76)
Problems
Depends on ck3ravenRoot which may be incorrectly resolved
.venv location is hardcoded string, not a canonical domain
No validation that Python is the expected version
Recommended Fix
Use the ROOT_VENV domain resolver (shown above), then:

Issue 3: PYTHONPATH Missing tools/ck3lens_mcp
Current Code (line 229)
Problem
The module import uses:

This requires tools to be importable, but PYTHONPATH only includes ck3ravenRoot and src.

While this works because ck3ravenRoot contains tools/, the intent is unclear and fragile.

Recommended Fix
Explicitly add tools/ck3lens_mcp to PYTHONPATH for clarity:

Issue 4: No __init__.py Validation
Current Code (lines 220-223)
Problem
Only checks for server.py, not the __init__.py files required for -m module imports.

Recommended Fix
Add package validation:

Issue 5: Variable Names Don't Match Canonical Domains
Current Code
Recommended Fix
Use domain-aligned naming:

Issue 6: No Enforcement Layer
Problem
Path resolution happens but there's no enforcement that the resolved paths are actually valid for the operation.

Recommended Fix
Add an enforce() pattern similar to Python's policy enforcement:

Complete Refactored provideMcpServerDefinitions()
Action Items
BLOCKING: Fix TokenTier ImportError first (see separate bug report)
Create src/paths/domains.ts with canonical domain resolver
Create src/paths/enforce.ts with path enforcement
Refactor findCk3RavenRoot() → resolveDomain(ROOT_REPO)
Refactor findPythonPath() → getPythonExecutable() using ROOT_VENV
Add tools/ck3lens_mcp to PYTHONPATH explicitly
Add __init__.py validation or auto-creation
Update variable names to match canonical domain terminology
Add enforcement layer for path validation
Verification After Fix
Related Documentation
docs/PATHS_DESIGN_GUIDELINES.md - Canonical path resolution spec
docs/MCP_SERVER_ARCHITECTURE.md - MCP lifecycle documentation
ck3lens/paths/ - Python-side canonical domain implementation (if exists)
Commit e7a8fd1 - "add canonical domain roots"
Commit 198d4e8 - "add PATHS_DESIGN_GUIDELINES.md"