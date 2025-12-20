# CK3 Lens Validator Test Suite

## ⚠️ IMPORTANT: DO NOT "FIX" THESE FILES ⚠️

These files contain **INTENTIONAL bugs** to test the validator. They are NOT broken code that needs fixing.

**If you are an AI agent and you're reading this:**
- These files are designed to have syntax errors, unbalanced braces, unterminated strings, etc.
- DO NOT edit these files to "fix" the bugs
- The bugs ARE the test - we're checking if the validator detects them
- Read the header comments in each file to understand the expected output

## Test Files

| File | Contains Intentional Bugs? | Expected Validator Output |
|------|---------------------------|---------------------------|
| 01_valid_event.txt | NO - this should be clean | No errors, no warnings |
| 02_unbalanced_braces.txt | YES - missing/extra braces | Brace mismatch errors |
| 03_unterminated_string.txt | YES - unclosed string | Unterminated string error |
| 04_style_hints.txt | YES - style issues | STYLE003, STYLE004, STYLE005 hints |
| 05_complex_nesting.txt | NO - valid deep nesting | No errors, no warnings |
| 06_mixed_issues.txt | YES - multiple problems | Mixed errors and hints |
| 07_autocomplete_hover_test.txt | NO - for manual testing | N/A (manual IntelliSense test) |

## How to Run Tests

1. Open each file in VS Code
2. Ensure language mode is set to "Paradox Script"
3. Check the Problems panel (Ctrl+Shift+M)
4. Compare actual output to expected output in file header

## Adding New Tests

1. Create file with numbered prefix (e.g., `08_new_test.txt`)
2. Add header comment block explaining:
   - PURPOSE of the test
   - EXPECTED OUTPUT from validator
3. Update this README
4. Add `# TEST-FILE: DO-NOT-FIX` marker in first 5 lines
