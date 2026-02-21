"""
Unit tests for Python Inline Code Scanner (Phase 1.5 Remediation)

Tests that:
1. Safe allowlist patterns are correctly identified
2. Mutation patterns are detected
3. Destructive patterns are classified correctly
4. classify_python_inline integrates extraction + scanning
"""
import pytest
from ck3lens.policy.python_inline_scanner import (
    is_python_inline_safe,
    scan_python_inline,
    classify_python_inline,
    InlineIntentType,
    InlineIntent,
    extract_inline_code,
    normalize_code,
)


class TestNormalizeCode:
    """Tests for code normalization."""
    
    def test_strips_surrounding_quotes(self):
        assert normalize_code('"print(1)"') == "print(1)"
        assert normalize_code("'print(1)'") == "print(1)"
    
    def test_collapses_whitespace(self):
        assert normalize_code("import  sys;   print(sys.version)") == "import sys; print(sys.version)"
    
    def test_mixed(self):
        assert normalize_code('"import  sys;   print(sys.version)"') == "import sys; print(sys.version)"


class TestIsPythonInlineSafe:
    """Tests for the safe allowlist check."""
    
    def test_sys_version(self):
        assert is_python_inline_safe("import sys; print(sys.version)") is True
    
    def test_sys_executable(self):
        assert is_python_inline_safe("import sys; print(sys.executable)") is True
    
    def test_os_getcwd(self):
        assert is_python_inline_safe("import os; print(os.getcwd())") is True
    
    def test_simple_print(self):
        assert is_python_inline_safe('print("hello")') is True
        assert is_python_inline_safe("print('hello')") is True
    
    def test_file_write_not_safe(self):
        assert is_python_inline_safe("open('x.txt', 'w').write('bad')") is False
    
    def test_path_write_text_not_safe(self):
        assert is_python_inline_safe("Path('x.txt').write_text('bad')") is False


class TestScanPythonInline:
    """Tests for full inline code scanning."""
    
    def test_safe_returns_safe_intent(self):
        result = scan_python_inline("import sys; print(sys.version)")
        assert result.intent == InlineIntentType.SAFE
        assert result.matched_allowlist is not None
    
    def test_read_only_no_mutations(self):
        result = scan_python_inline("x = 1 + 2; print(x)")
        assert result.intent == InlineIntentType.READ_ONLY
        assert result.reasons == ()
    
    def test_file_write_detected(self):
        result = scan_python_inline("f = open('x.txt', 'w'); f.write('data')")
        assert result.intent == InlineIntentType.POTENTIALLY_WRITE
        assert len(result.reasons) > 0
        assert any("write" in r.lower() for r in result.reasons)
    
    def test_path_write_text_detected(self):
        result = scan_python_inline("from pathlib import Path; Path('x').write_text('data')")
        assert result.intent == InlineIntentType.POTENTIALLY_WRITE
        assert any("write_text" in r for r in result.reasons)
    
    def test_mkdir_detected(self):
        result = scan_python_inline("from pathlib import Path; Path('mydir').mkdir()")
        assert result.intent == InlineIntentType.POTENTIALLY_WRITE
        assert any("mkdir" in r for r in result.reasons)
    
    def test_os_remove_is_destructive(self):
        result = scan_python_inline("import os; os.remove('file.txt')")
        assert result.intent == InlineIntentType.DESTRUCTIVE
        assert any("remove" in r.lower() or "deletion" in r.lower() for r in result.reasons)
    
    def test_shutil_rmtree_is_destructive(self):
        result = scan_python_inline("import shutil; shutil.rmtree('mydir')")
        assert result.intent == InlineIntentType.DESTRUCTIVE
    
    def test_subprocess_run_detected(self):
        result = scan_python_inline("import subprocess; subprocess.run(['ls'])")
        assert result.intent == InlineIntentType.POTENTIALLY_WRITE
        assert any("subprocess" in r for r in result.reasons)
    
    def test_exec_detected(self):
        result = scan_python_inline("exec('print(1)')")
        assert result.intent == InlineIntentType.POTENTIALLY_WRITE
        assert any("exec" in r for r in result.reasons)


class TestExtractInlineCode:
    """Tests for extracting code from python -c commands."""
    
    def test_double_quoted(self):
        assert extract_inline_code('python -c "print(1)"') == "print(1)"
    
    def test_single_quoted(self):
        assert extract_inline_code("python -c 'print(1)'") == "print(1)"
    
    def test_python3(self):
        assert extract_inline_code('python3 -c "print(1)"') == "print(1)"
    
    def test_not_python_c(self):
        assert extract_inline_code("python script.py") is None
    
    def test_just_python(self):
        assert extract_inline_code("python") is None


class TestClassifyPythonInline:
    """Tests for the classification helper."""
    
    def test_not_python_c_returns_false(self):
        is_python_c, intent = classify_python_inline("ls -la")
        assert is_python_c is False
        assert intent is None
    
    def test_safe_command(self):
        is_python_c, intent = classify_python_inline('python -c "import sys; print(sys.version)"')
        assert is_python_c is True
        assert intent is not None
        assert intent.intent == InlineIntentType.SAFE
    
    def test_write_command(self):
        is_python_c, intent = classify_python_inline("python -c \"open('x.txt', 'w').write('bad')\"")
        assert is_python_c is True
        assert intent is not None
        assert intent.intent == InlineIntentType.POTENTIALLY_WRITE
