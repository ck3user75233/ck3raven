# CK3 Lens Testing Instructions

After reloading VS Code, follow these steps to verify CK3 Lens is working.

---

## Step 1: Reload VS Code

Press `Ctrl+Shift+P` → "Developer: Reload Window"

---

## Step 2: Run Python Tests (Terminal)

Open a terminal and run:

```powershell
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven\tools\ck3lens_mcp"
& "C:/Users/Nathan/Documents/AI Workspace/.venv/Scripts/python.exe" tests/test_mcp_tools.py
```

Expected output:
- ✅ All imports pass
- ✅ 20 MCP tools registered
- ✅ Session initializes
- ⏭️ Database may be skipped (needs indexer)
- ✅ Live mods found
- ✅ Validation works

---

## Step 3: Test via Copilot Chat

After VS Code reloads, open Copilot Chat and test these prompts:

### Test 1: Session Initialization
```
Initialize the CK3 Lens session and show me what mods are available
```

Expected: Shows mod_root path and list of live mods

### Test 2: List Live Mods
```
List the live mods that CK3 Lens can write to
```

Expected: Shows MSC, MSCRE, LRE, MRP, PVP2 (whichever exist on disk)

### Test 3: Parse CK3 Script
```
Use CK3 Lens to parse this script and check for errors:

my_trait = {
    index = 999
    name = test_trait
}
```

Expected: Returns AST or parse result

### Test 4: List Files in Live Mod
```
List the files in the common folder of Mini Super Compatch
```

Expected: Shows file list from MSC/common/

### Test 5: Read Live File
```
Read the descriptor.mod file from Mini Super Compatch
```

Expected: Shows file contents

### Test 6: Git Status
```
Show the git status for Mini Super Compatch
```

Expected: Shows git status or "not a git repo" if not initialized

---

## Step 4: Verify MCP Server is Running

In VS Code:
1. Press `Ctrl+Shift+P`
2. Run: "MCP: List Servers"
3. Look for `ck3lens` in the list

If not showing:
- Check `.vscode/mcp.json` exists
- Verify Python path is correct
- Try reloading again

---

## Quick Terminal Validation Commands

```powershell
# Check MCP tools are registered
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven\tools\ck3lens_mcp"
& "C:/Users/Nathan/Documents/AI Workspace/.venv/Scripts/python.exe" -c "from server import mcp; print(f'{len(mcp._tool_manager._tools)} tools registered')"

# Test session creation
& "C:/Users/Nathan/Documents/AI Workspace/.venv/Scripts/python.exe" -c "from ck3lens.workspace import Session; s = Session(); print(f'mod_root: {s.mod_root}'); print(f'live_mods: {[m.name for m in s.live_mods]}')"

# Test validation
& "C:/Users/Nathan/Documents/AI Workspace/.venv/Scripts/python.exe" -c "from ck3lens.validate import parse_content; r = parse_content('x = { y = 1 }'); print('Parse:', 'OK' if r['success'] else r['errors'])"
```

---

## Troubleshooting

### "ck3lens server not found"
- Reload VS Code
- Check `.vscode/mcp.json` has correct Python path

### "Module not found"
```powershell
pip install -e "C:\Users\Nathan\Documents\AI Workspace\ck3raven\tools\ck3lens_mcp"
```

### "Database not found"
This is expected until the ck3raven indexer is run. The tools that require the database will return "db_path: None" but other tools (live mods, validation, git) will still work.

---

## What's Working Without Database

Even without the ck3raven database indexed, these tools work:

| Tool | Status |
|------|--------|
| `ck3_init_session` | ✅ Works |
| `ck3_list_live_mods` | ✅ Works |
| `ck3_read_live_file` | ✅ Works |
| `ck3_write_file` | ✅ Works |
| `ck3_edit_file` | ✅ Works |
| `ck3_delete_file` | ✅ Works |
| `ck3_list_live_files` | ✅ Works |
| `ck3_parse_content` | ✅ Works |
| `ck3_validate_patchdraft` | ✅ Works |
| `ck3_git_*` | ✅ Works |
| `ck3_search_symbols` | ⚠️ Needs DB |
| `ck3_confirm_not_exists` | ⚠️ Needs DB |
| `ck3_get_file` | ⚠️ Needs DB |
| `ck3_get_conflicts` | ⚠️ Needs DB |

---

## Next: Building the Database

To enable all search/query tools, run the ck3raven indexer:

```powershell
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven"
& ".venv/Scripts/python.exe" -m ck3raven.cli index --help
```

This will parse all active mods and build the SQLite database.
