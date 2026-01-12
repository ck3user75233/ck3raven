"""
Lightweight Tokenizer for LOOKUPS Route Files

This tokenizer extracts tokens from CK3 script files WITHOUT building a full AST.
It's designed for files in the LOOKUPS route (dynasties, characters, provinces, etc.)
where we only need to extract key-value data, not understand scripted logic.

ARCHITECTURE:
- SCRIPT route → Full parser → AST → Symbol extraction  
- LOOKUPS route → THIS tokenizer → Specialized extractors → Lookup tables

The tokenizer yields (token_type, value, line, column) tuples that extractors
can consume iteratively without holding the entire file structure in memory.

Token Types:
    LBRACE      {
    RBRACE      }
    EQUALS      =
    LT          <
    GT          >
    LE          <=
    GE          >=
    NE          !=
    STRING      "quoted string"
    NUMBER      123 or 123.456 or -5
    DATE        867.1.1
    BARE        unquoted_identifier
    COMMENT     # comment text (optional, can be skipped)
    EOF         end of file

Usage:
    from builder.extractors.lookups.tokenizer import tokenize, TokenType
    
    for token in tokenize(content):
        if token.type == TokenType.BARE and token.value.isdigit():
            dynasty_id = int(token.value)
        elif token.type == TokenType.LBRACE:
            ...
"""

import re
from enum import Enum, auto
from dataclasses import dataclass
from typing import Iterator, Optional


class TokenType(Enum):
    """Token types produced by the lightweight tokenizer."""
    LBRACE = auto()    # {
    RBRACE = auto()    # }
    EQUALS = auto()    # =
    LT = auto()        # <
    GT = auto()        # >
    LE = auto()        # <=
    GE = auto()        # >=
    NE = auto()        # !=
    STRING = auto()    # "quoted string"
    NUMBER = auto()    # 123 or 123.456
    DATE = auto()      # 867.1.1 (year.month.day)
    BARE = auto()      # unquoted identifier
    COMMENT = auto()   # # comment
    EOF = auto()       # end of file


@dataclass(frozen=True, slots=True)
class Token:
    """A token from the source text."""
    type: TokenType
    value: str
    line: int
    column: int


# Patterns for tokenization
_WHITESPACE_RE = re.compile(r'[ \t]+')
_NEWLINE_RE = re.compile(r'\r?\n')
_COMMENT_RE = re.compile(r'#[^\r\n]*')
_STRING_RE = re.compile(r'"([^"\\]|\\.)*"')
_NUMBER_RE = re.compile(r'-?\d+(\.\d+)?')
_DATE_RE = re.compile(r'\d+\.\d+\.\d+')
_BARE_RE = re.compile(r'[a-zA-Z_@][a-zA-Z0-9_:@\-\.]*|[a-zA-Z_]')
_OPERATOR_RE = re.compile(r'<=|>=|!=|[=<>{}]')


def tokenize(
    source: str,
    *,
    skip_comments: bool = True,
    filename: str = "<unknown>",
) -> Iterator[Token]:
    """
    Tokenize CK3 script content into a stream of tokens.
    
    This is a lightweight alternative to the full parser that doesn't
    build an AST. It's suitable for LOOKUPS route files where we only
    need to extract key-value data.
    
    Args:
        source: The source text to tokenize
        skip_comments: If True, don't yield COMMENT tokens
        filename: For error messages
        
    Yields:
        Token objects with type, value, line, and column
    """
    pos = 0
    line = 1
    line_start = 0
    length = len(source)
    
    while pos < length:
        # Track column
        col = pos - line_start
        
        # Skip whitespace (not newlines)
        m = _WHITESPACE_RE.match(source, pos)
        if m:
            pos = m.end()
            continue
        
        # Handle newlines
        m = _NEWLINE_RE.match(source, pos)
        if m:
            pos = m.end()
            line += 1
            line_start = pos
            continue
        
        # Comments
        m = _COMMENT_RE.match(source, pos)
        if m:
            if not skip_comments:
                yield Token(TokenType.COMMENT, m.group(), line, col)
            pos = m.end()
            continue
        
        # String literals
        m = _STRING_RE.match(source, pos)
        if m:
            # Strip quotes for the value
            raw = m.group()
            value = raw[1:-1]  # Remove surrounding quotes
            yield Token(TokenType.STRING, value, line, col)
            pos = m.end()
            continue
        
        # Date literals (must check before number - dates contain dots)
        m = _DATE_RE.match(source, pos)
        if m:
            yield Token(TokenType.DATE, m.group(), line, col)
            pos = m.end()
            continue
        
        # Numbers
        m = _NUMBER_RE.match(source, pos)
        if m:
            yield Token(TokenType.NUMBER, m.group(), line, col)
            pos = m.end()
            continue
        
        # Operators (check multi-char first)
        m = _OPERATOR_RE.match(source, pos)
        if m:
            op = m.group()
            if op == '{':
                yield Token(TokenType.LBRACE, op, line, col)
            elif op == '}':
                yield Token(TokenType.RBRACE, op, line, col)
            elif op == '=':
                yield Token(TokenType.EQUALS, op, line, col)
            elif op == '<':
                yield Token(TokenType.LT, op, line, col)
            elif op == '>':
                yield Token(TokenType.GT, op, line, col)
            elif op == '<=':
                yield Token(TokenType.LE, op, line, col)
            elif op == '>=':
                yield Token(TokenType.GE, op, line, col)
            elif op == '!=':
                yield Token(TokenType.NE, op, line, col)
            pos = m.end()
            continue
        
        # Bare identifiers (must be last - catches most remaining valid tokens)
        m = _BARE_RE.match(source, pos)
        if m:
            yield Token(TokenType.BARE, m.group(), line, col)
            pos = m.end()
            continue
        
        # Unknown character - skip it
        pos += 1
    
    # End of file
    yield Token(TokenType.EOF, '', line, pos - line_start)


class BlockParser:
    """
    Helper to parse top-level blocks from a token stream.
    
    This is useful for files with structure like:
        123 = { key = value ... }
        456 = { key = value ... }
    
    Usage:
        parser = BlockParser(tokenize(content))
        for block_id, block_content in parser.iter_top_level_blocks():
            # block_id is the identifier before =
            # block_content is a dict of key-value pairs
    """
    
    def __init__(self, tokens: Iterator[Token]):
        self._tokens = tokens
        self._current: Optional[Token] = None
        self._advance()
    
    def _advance(self) -> Optional[Token]:
        """Move to next token."""
        try:
            self._current = next(self._tokens)
        except StopIteration:
            self._current = Token(TokenType.EOF, '', 0, 0)
        return self._current
    
    def iter_top_level_blocks(self) -> Iterator[tuple[str, dict]]:
        """
        Iterate over top-level blocks in the file.
        
        Yields:
            (block_name, block_dict) tuples
            block_dict contains simple key-value pairs extracted from the block
        """
        while self._current and self._current.type != TokenType.EOF:
            # Expect: identifier = { ... }
            if self._current.type not in (TokenType.BARE, TokenType.NUMBER, TokenType.DATE):
                self._advance()
                continue
            
            block_name = self._current.value
            self._advance()
            
            # Expect =
            if self._current.type != TokenType.EQUALS:
                continue
            self._advance()
            
            # Could be simple value or block
            if self._current.type == TokenType.LBRACE:
                self._advance()
                block_content = self._parse_block_content()
                yield block_name, block_content
            else:
                # Simple assignment at top level (rare but possible)
                value = self._current.value
                self._advance()
                yield block_name, {'_value': value}
    
    def _parse_block_content(self, max_depth: int = 10) -> dict:
        """
        Parse content inside a block { ... } into a dict.
        
        Only extracts simple key = value pairs. Nested blocks are
        recorded with their raw content but not deeply parsed
        (to keep it lightweight).
        """
        result = {}
        
        while self._current and self._current.type != TokenType.EOF:
            if self._current.type == TokenType.RBRACE:
                self._advance()
                return result
            
            # Key
            if self._current.type not in (TokenType.BARE, TokenType.NUMBER, TokenType.DATE, TokenType.STRING):
                self._advance()
                continue
            
            key = self._current.value
            self._advance()
            
            # Operator (= or comparison)
            if self._current.type in (TokenType.EQUALS, TokenType.LT, TokenType.GT, 
                                      TokenType.LE, TokenType.GE, TokenType.NE):
                self._advance()
            else:
                # No operator - might be a list item or malformed
                continue
            
            # Value
            if self._current.type == TokenType.LBRACE:
                # Nested block - recurse if not too deep
                self._advance()
                if max_depth > 0:
                    nested = self._parse_block_content(max_depth - 1)
                    result[key] = nested
                else:
                    # Too deep - skip this block
                    self._skip_block()
            elif self._current.type in (TokenType.STRING, TokenType.BARE, 
                                        TokenType.NUMBER, TokenType.DATE):
                result[key] = self._current.value
                self._advance()
            else:
                self._advance()
        
        return result
    
    def _skip_block(self) -> None:
        """Skip a block by counting braces."""
        depth = 1
        while self._current and self._current.type != TokenType.EOF and depth > 0:
            if self._current.type == TokenType.LBRACE:
                depth += 1
            elif self._current.type == TokenType.RBRACE:
                depth -= 1
            self._advance()


def extract_simple_blocks(content: str) -> Iterator[tuple[str, dict]]:
    """
    Convenience function to extract top-level blocks from content.
    
    This is the primary interface for LOOKUPS extractors.
    
    Args:
        content: Raw file content
        
    Yields:
        (block_name, block_dict) tuples
        
    Example:
        for dynasty_id, data in extract_simple_blocks(content):
            name = data.get('name')
            culture = data.get('culture')
    """
    parser = BlockParser(tokenize(content))
    yield from parser.iter_top_level_blocks()
