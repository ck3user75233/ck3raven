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
- ✅ Database connected (80,968 files indexed)
- ✅ Live mods found
- ✅ Validation works

---

## Step 3: Test via Copilot Chat

After VS Code reloads, open Copilot Chat and test these prompts:

### Test 1: Session Initialization
```
Initialize the CK3 Lens session and show me what mods are available
```

Expected: Shows mod_root path and list of local mods

### Test 2: List Local Mods
```
List the local mods that CK3 Lens can write to
```

Expected: Shows mods configured in your playset's `local_mods` section

### Test 3: Parse CK3 Script
```
Use CK3 Lens to parse this script and check for errors:

my_trait = {
    index = 999
    name = test_trait
}
```

Expected: Returns AST or parse result

### Test 4: List Files in Local Mod
```
List the files in the common folder of [your mod name]
```

Expected: Shows file list from [mod]/common/

### Test 5: Read Local File
```
Read the descriptor.mod file from [your mod name]
```

Expected: Shows file contents

### Test 6: Git Status
```
Show the git status for [your mod name]
```

Expected: Shows git status or "not a git repo" if not initialized

---

## Step 4: Verify MCP Server is Running

In VS Code:
1. Press `Ctrl+Shift+P`
2. Run: "MCP: List Servers"
3. Look for `ck3lens` in the list

If not showing:
- Check CK3 Lens Explorer extension is installed and active
- Verify `chat.mcp.discovery.enabled: true` in VS Code settings
- Try reloading the VS Code window

> ⚠️ **DO NOT create `.vscode/mcp.json`** - the extension registers the server dynamically.

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
- Check CK3 Lens Explorer extension is installed
- Verify `chat.mcp.discovery.enabled: true` in settings
- **DO NOT create mcp.json** - this causes duplicate servers

### "Module not found"
```powershell
pip install -e "C:\Users\Nathan\Documents\AI Workspace\ck3raven\tools\ck3lens_mcp"
```

### "Database not found"
The database should be at `~/.ck3raven/ck3raven.db`. If missing, run:
```powershell
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven"
python scripts/build_database.py
```
This indexes vanilla CK3 (46,701 files) and all active mods from your playset.

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
| `ck3_qr_conflicts` | ⚠️ Needs DB |

---

## Database Status ✅

The database has been built with:
- **106 content versions** (vanilla + 105 mods)
- **80,968 files indexed**
- **27.9 GB** of content
- Located at: `~/.ck3raven/ck3raven.db`

To rebuild the database:
```powershell
cd "C:\Users\Nathan\Documents\AI Workspace\ck3raven"
python scripts/build_database.py
```
