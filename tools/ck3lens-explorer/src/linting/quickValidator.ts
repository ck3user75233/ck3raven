/**
 * Quick Validator - Fast TypeScript-based syntax validation
 * 
 * Provides immediate feedback while waiting for the full Python parser.
 * Checks:
 * - Balanced braces
 * - Unterminated strings
 * - Basic structure issues
 * - Common typos
 */

export interface QuickDiagnostic {
    line: number;
    column: number;
    endLine?: number;
    endColumn?: number;
    message: string;
    severity: 'error' | 'warning' | 'info' | 'hint';
    code: string;
}

export interface QuickValidationResult {
    valid: boolean;
    diagnostics: QuickDiagnostic[];
    bracesBalanced: boolean;
    stringsTerminated: boolean;
}

/**
 * Perform quick syntax validation on CK3 script content.
 * This runs entirely in TypeScript for immediate feedback.
 */
export function quickValidate(content: string): QuickValidationResult {
    const diagnostics: QuickDiagnostic[] = [];
    const lines = content.split('\n');
    
    let openBraces = 0;
    let closeBraces = 0;
    let inString = false;
    let stringStartLine = 0;
    let stringStartCol = 0;
    let inComment = false;
    
    // Track brace positions for mismatch detection
    const braceStack: Array<{ line: number; col: number }> = [];
    
    for (let lineNum = 0; lineNum < lines.length; lineNum++) {
        const line = lines[lineNum];
        inComment = false;
        
        for (let col = 0; col < line.length; col++) {
            const char = line[col];
            const prevChar = col > 0 ? line[col - 1] : '';
            
            // Handle comments
            if (!inString && char === '#') {
                inComment = true;
                break; // Rest of line is comment
            }
            
            // Handle strings
            if (char === '"' && prevChar !== '\\') {
                if (!inString) {
                    inString = true;
                    stringStartLine = lineNum + 1;
                    stringStartCol = col + 1;
                } else {
                    inString = false;
                }
                continue;
            }
            
            // Skip characters inside strings
            if (inString) {
                continue;
            }
            
            // Count braces
            if (char === '{') {
                openBraces++;
                braceStack.push({ line: lineNum + 1, col: col + 1 });
            } else if (char === '}') {
                closeBraces++;
                if (braceStack.length > 0) {
                    braceStack.pop();
                } else {
                    // Unmatched closing brace
                    diagnostics.push({
                        line: lineNum + 1,
                        column: col + 1,
                        message: 'Unmatched closing brace }',
                        severity: 'error',
                        code: 'QV001'
                    });
                }
            }
        }
        
        // Check for unterminated string at end of line (unless escaped)
        if (inString && !line.endsWith('\\')) {
            // Multi-line strings are actually allowed in PDX format
            // but usually indicate an error, so we'll warn
            // Actually, let's check if it spans too many lines
        }
        
        // Check for common issues in the line
        checkLineIssues(line, lineNum + 1, diagnostics);
    }
    
    // Check for unterminated string at end of file
    if (inString) {
        diagnostics.push({
            line: stringStartLine,
            column: stringStartCol,
            message: 'Unterminated string - missing closing quote',
            severity: 'error',
            code: 'QV002'
        });
    }
    
    // Check for unbalanced braces
    if (braceStack.length > 0) {
        for (const brace of braceStack) {
            diagnostics.push({
                line: brace.line,
                column: brace.col,
                message: `Unclosed brace - missing } (${braceStack.length} unclosed)`,
                severity: 'error',
                code: 'QV003'
            });
        }
    }
    
    const bracesBalanced = openBraces === closeBraces;
    const stringsTerminated = !inString;
    
    return {
        valid: diagnostics.filter(d => d.severity === 'error').length === 0,
        diagnostics,
        bracesBalanced,
        stringsTerminated
    };
}

/**
 * Check for common issues in a single line
 */
function checkLineIssues(line: string, lineNum: number, diagnostics: QuickDiagnostic[]): void {
    const trimmed = line.trim();
    
    // Skip empty lines and comments
    if (!trimmed || trimmed.startsWith('#')) {
        return;
    }
    
    // Check for = without spaces (not an error, but might indicate issues)
    // Actually, CK3 allows no spaces around =, so skip this
    
    // Check for common CK3 typos
    const commonTypos: Array<{ pattern: RegExp; correct: string; message: string }> = [
        { pattern: /\bif\s*=\s*\{/, correct: 'if = {', message: 'Did you mean to use a trigger condition?' },
        { pattern: /\belse\s*=\s*\{/, correct: 'else = {', message: 'else blocks use different syntax' },
        { pattern: /\byes\s*=/, correct: 'yes', message: '"yes" is a value, not a key' },
        { pattern: /\bno\s*=/, correct: 'no', message: '"no" is a value, not a key' },
    ];
    
    for (const typo of commonTypos) {
        if (typo.pattern.test(trimmed)) {
            // Find column position
            const match = trimmed.match(typo.pattern);
            if (match) {
                diagnostics.push({
                    line: lineNum,
                    column: line.indexOf(match[0]) + 1,
                    message: typo.message,
                    severity: 'hint',
                    code: 'QV100'
                });
            }
        }
    }
    
    // Check for common structural issues
    
    // Double equals
    if (/[^=!<>]==(?!=)/.test(trimmed)) {
        const match = trimmed.match(/[^=!<>]==(?!=)/);
        if (match) {
            diagnostics.push({
                line: lineNum,
                column: line.indexOf(match[0]) + 2,
                message: 'Use single = for assignment (== is comparison)',
                severity: 'hint',
                code: 'QV101'
            });
        }
    }
    
    // Missing = between key and {
    // Pattern: identifier immediately followed by { without =
    const missingEquals = /^(\s*)(\w+)\s*\{/.exec(trimmed);
    if (missingEquals) {
        // This could be intentional in some contexts, so just hint
        const key = missingEquals[2];
        // Skip known keywords that don't need =
        const noEqualsNeeded = ['if', 'else', 'else_if', 'while', 'switch', 'random', 'random_list'];
        if (!noEqualsNeeded.includes(key.toLowerCase())) {
            diagnostics.push({
                line: lineNum,
                column: line.indexOf(key) + 1,
                message: `Consider: ${key} = { ... } (missing = before {?)`,
                severity: 'hint',
                code: 'QV102'
            });
        }
    }
    
    // Very long lines
    if (line.length > 300) {
        diagnostics.push({
            line: lineNum,
            column: 300,
            message: `Line is very long (${line.length} characters)`,
            severity: 'info',
            code: 'QV200'
        });
    }
}

/**
 * Get the matching brace position for a given position
 */
export function findMatchingBrace(
    content: string, 
    line: number, 
    column: number
): { line: number; column: number } | null {
    const lines = content.split('\n');
    const targetLine = lines[line - 1];
    if (!targetLine) return null;
    
    const char = targetLine[column - 1];
    if (char !== '{' && char !== '}') return null;
    
    const isOpening = char === '{';
    let depth = 0;
    let inString = false;
    
    if (isOpening) {
        // Search forward
        for (let l = line - 1; l < lines.length; l++) {
            const startCol = l === line - 1 ? column : 0;
            for (let c = startCol; c < lines[l].length; c++) {
                const ch = lines[l][c];
                const prevCh = c > 0 ? lines[l][c - 1] : '';
                
                if (ch === '"' && prevCh !== '\\') {
                    inString = !inString;
                    continue;
                }
                if (inString) continue;
                if (lines[l].slice(c).startsWith('#')) break;
                
                if (ch === '{') depth++;
                else if (ch === '}') {
                    depth--;
                    if (depth === 0) {
                        return { line: l + 1, column: c + 1 };
                    }
                }
            }
        }
    } else {
        // Search backward
        for (let l = line - 1; l >= 0; l--) {
            const endCol = l === line - 1 ? column - 2 : lines[l].length - 1;
            for (let c = endCol; c >= 0; c--) {
                const ch = lines[l][c];
                // Simplified backward search (less accurate with strings)
                if (ch === '}') depth++;
                else if (ch === '{') {
                    depth--;
                    if (depth === 0) {
                        return { line: l + 1, column: c + 1 };
                    }
                }
            }
        }
    }
    
    return null;
}

/**
 * Count nesting depth at a given position
 */
export function getNestingDepth(content: string, line: number, column: number): number {
    const lines = content.split('\n');
    let depth = 0;
    let inString = false;
    
    for (let l = 0; l < line; l++) {
        const endCol = l === line - 1 ? column - 1 : lines[l].length;
        for (let c = 0; c < endCol && c < lines[l].length; c++) {
            const ch = lines[l][c];
            const prevCh = c > 0 ? lines[l][c - 1] : '';
            
            if (ch === '"' && prevCh !== '\\') {
                inString = !inString;
                continue;
            }
            if (inString) continue;
            if (lines[l].slice(c).startsWith('#')) break;
            
            if (ch === '{') depth++;
            else if (ch === '}') depth--;
        }
    }
    
    return depth;
}
