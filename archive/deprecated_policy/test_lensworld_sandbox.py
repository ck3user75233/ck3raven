"""
Test suite for LensWorld Sandbox

This script tests the sandbox by directly calling run_script_sandboxed()
with various test scripts to verify:
1. Reads inside LensWorld (should work)
2. Reads outside LensWorld (should fail with FileNotFoundError)
3. Writes inside LensWorld (should work)
4. Writes outside LensWorld (should fail with FileNotFoundError)
"""
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Add ck3lens to path
test_root = Path(__file__).parent
ck3lens_mcp_path = test_root.parent.parent / "tools" / "ck3lens_mcp"
sys.path.insert(0, str(ck3lens_mcp_path))

from ck3lens.policy.lensworld_sandbox import run_script_sandboxed, LensWorldSandbox


def create_test_environment():
    """Create temporary directories for testing."""
    # Create temp WIP directory
    wip_path = Path(tempfile.mkdtemp(prefix="wip_test_"))
    
    # Create temp local mod directory
    local_mod_path = Path(tempfile.mkdtemp(prefix="local_mod_test_"))
    
    # Create temp utility path
    utility_path = Path(tempfile.mkdtemp(prefix="utility_test_"))
    
    # Create a file in each directory for testing reads
    (wip_path / "wip_file.txt").write_text("WIP content")
    (local_mod_path / "mod_file.txt").write_text("Mod content")
    (utility_path / "utility_file.txt").write_text("Utility content")
    
    return wip_path, local_mod_path, utility_path


def cleanup_test_environment(wip_path, local_mod_path, utility_path):
    """Clean up test directories."""
    shutil.rmtree(wip_path, ignore_errors=True)
    shutil.rmtree(local_mod_path, ignore_errors=True)
    shutil.rmtree(utility_path, ignore_errors=True)


def test_read_inside_wip(wip_path, local_mod_path, utility_path):
    """Test: Reading a file inside WIP should succeed."""
    script_content = '''
from pathlib import Path
wip_file = Path(__file__).parent / "wip_file.txt"
content = wip_file.read_text()
print(f"WIP read success: {content}")
'''
    script_path = wip_path / "test_read_wip.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),
    )
    
    print(f"TEST: Read inside WIP")
    print(f"  Success: {result['success']}")
    print(f"  Output: {result['output'].strip()}")
    print(f"  Audit: {result['audit']}")
    print()
    
    assert result["success"], f"Should succeed: {result['error']}"
    assert "WIP read success" in result["output"]


def test_read_inside_local_mod(wip_path, local_mod_path, utility_path):
    """Test: Reading a file inside local mod should succeed."""
    script_content = f'''
from pathlib import Path
mod_file = Path(r"{local_mod_path / 'mod_file.txt'}")
content = mod_file.read_text()
print(f"Mod read success: {{content}}")
'''
    script_path = wip_path / "test_read_mod.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),
    )
    
    print(f"TEST: Read inside local mod")
    print(f"  Success: {result['success']}")
    print(f"  Output: {result['output'].strip()}")
    print(f"  Audit: {result['audit']}")
    print()
    
    assert result["success"], f"Should succeed: {result['error']}"
    assert "Mod read success" in result["output"]


def test_read_outside_lensworld(wip_path, local_mod_path, utility_path):
    """Test: Reading a file outside LensWorld should fail."""
    # Create a file outside the sandbox
    outside_path = Path(tempfile.mkdtemp(prefix="outside_test_"))
    (outside_path / "secret.txt").write_text("Secret content")
    
    script_content = f'''
from pathlib import Path
secret_file = Path(r"{outside_path / 'secret.txt'}")
content = secret_file.read_text()
print(f"SHOULD NOT SEE THIS: {{content}}")
'''
    script_path = wip_path / "test_read_outside.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),
    )
    
    print(f"TEST: Read outside LensWorld")
    print(f"  Success: {result['success']} (should be False)")
    print(f"  Error: {result.get('error', 'None')}")
    print(f"  Audit: {result['audit']}")
    print()
    
    # Cleanup
    shutil.rmtree(outside_path, ignore_errors=True)
    
    assert not result["success"], "Should fail - reading outside LensWorld"
    assert "LensWorld" in result.get("error", "") or result["audit"].get("blocked_reads", 0) > 0


def test_write_inside_wip(wip_path, local_mod_path, utility_path):
    """Test: Writing a file inside WIP should succeed."""
    script_content = '''
from pathlib import Path
output_file = Path(__file__).parent / "output.txt"
output_file.write_text("Written from sandbox")
print(f"WIP write success: {output_file.exists()}")
'''
    script_path = wip_path / "test_write_wip.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),  # WIP is always allowed
    )
    
    print(f"TEST: Write inside WIP")
    print(f"  Success: {result['success']}")
    print(f"  Output: {result['output'].strip()}")
    print(f"  Audit: {result['audit']}")
    print()
    
    assert result["success"], f"Should succeed: {result['error']}"
    assert (wip_path / "output.txt").exists(), "File should have been written"


def test_write_inside_declared_mod(wip_path, local_mod_path, utility_path):
    """Test: Writing to a declared mod path should succeed."""
    output_file = local_mod_path / "new_file.txt"
    
    script_content = f'''
from pathlib import Path
output_file = Path(r"{output_file}")
output_file.write_text("Written to mod")
print(f"Mod write success: {{output_file.exists()}}")
'''
    script_path = wip_path / "test_write_mod.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths={output_file},  # Declared write path
    )
    
    print(f"TEST: Write inside declared mod path")
    print(f"  Success: {result['success']}")
    print(f"  Output: {result['output'].strip()}")
    print(f"  Audit: {result['audit']}")
    print()
    
    assert result["success"], f"Should succeed: {result['error']}"
    assert output_file.exists(), "File should have been written"


def test_write_outside_lensworld(wip_path, local_mod_path, utility_path):
    """Test: Writing a file outside LensWorld should fail."""
    outside_path = Path(tempfile.mkdtemp(prefix="outside_test_"))
    output_file = outside_path / "hacked.txt"
    
    script_content = f'''
from pathlib import Path
output_file = Path(r"{output_file}")
output_file.write_text("HACKED")
print("SHOULD NOT SEE THIS")
'''
    script_path = wip_path / "test_write_outside.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),  # Not declared!
    )
    
    print(f"TEST: Write outside LensWorld")
    print(f"  Success: {result['success']} (should be False)")
    print(f"  Error: {result.get('error', 'None')}")
    print(f"  Audit: {result['audit']}")
    print()
    
    # Cleanup
    shutil.rmtree(outside_path, ignore_errors=True)
    
    assert not result["success"], "Should fail - writing outside LensWorld"
    assert not output_file.exists(), "File should NOT have been written"


def test_exists_check_outside_lensworld(wip_path, local_mod_path, utility_path):
    """Test: Checking if a file outside LensWorld exists should return False."""
    # Create a file outside the sandbox
    outside_path = Path(tempfile.mkdtemp(prefix="outside_test_"))
    (outside_path / "hidden.txt").write_text("Hidden content")
    
    script_content = f'''
from pathlib import Path
import os

# Test both pathlib and os.path
path_exists_pathlib = Path(r"{outside_path / 'hidden.txt'}").exists()
path_exists_os = os.path.exists(r"{outside_path / 'hidden.txt'}")

print(f"pathlib.exists: {{path_exists_pathlib}}")  # Should be False
print(f"os.path.exists: {{path_exists_os}}")       # Should be False
'''
    script_path = wip_path / "test_exists_outside.py"
    script_path.write_text(script_content)
    
    result = run_script_sandboxed(
        script_path=script_path,
        wip_path=wip_path,
        local_mod_roots={local_mod_path},
        utility_paths={utility_path},
        declared_write_paths=set(),
    )
    
    print(f"TEST: Exists check outside LensWorld")
    print(f"  Success: {result['success']}")
    print(f"  Output: {result['output'].strip()}")
    print(f"  Audit: {result['audit']}")
    print()
    
    # Cleanup
    shutil.rmtree(outside_path, ignore_errors=True)
    
    assert result["success"], f"Script should run: {result['error']}"
    assert "pathlib.exists: False" in result["output"]
    assert "os.path.exists: False" in result["output"]


def main():
    """Run all tests."""
    print("=" * 60)
    print("LensWorld Sandbox Tests")
    print("=" * 60)
    print()
    
    wip_path, local_mod_path, utility_path = create_test_environment()
    
    try:
        # Test reads
        test_read_inside_wip(wip_path, local_mod_path, utility_path)
        test_read_inside_local_mod(wip_path, local_mod_path, utility_path)
        test_read_outside_lensworld(wip_path, local_mod_path, utility_path)
        
        # Test writes
        test_write_inside_wip(wip_path, local_mod_path, utility_path)
        test_write_inside_declared_mod(wip_path, local_mod_path, utility_path)
        test_write_outside_lensworld(wip_path, local_mod_path, utility_path)
        
        # Test visibility
        test_exists_check_outside_lensworld(wip_path, local_mod_path, utility_path)
        
        print("=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"TEST FAILED: {e}")
        raise
    finally:
        cleanup_test_environment(wip_path, local_mod_path, utility_path)


if __name__ == "__main__":
    main()
