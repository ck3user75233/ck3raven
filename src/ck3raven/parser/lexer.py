"""
CK3/Paradox Script Lexer (Tokenizer)

Converts raw .txt script files into a stream of tokens.
Handles: identifiers, operators, braces, strings, numbers, comments.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator, List, Optional


class TokenType(Enum):
    """Types of tokens in Paradox script."""
    IDENTIFIER = auto()      # foo, bar_baz, tradition_mountain_homes
    STRING = auto()          # "quoted string"
    NUMBER = auto()          # 123, -0.5, 0.25
    EQUALS = auto()          # =
    LBRACE = auto()          # {
    RBRACE = auto()          # }
    LBRACKET = auto()        # [
    RBRACKET = auto()        # ]
    LESS_THAN = auto()       # <
    GREATER_THAN = auto()    # >
    LESS_EQUAL = auto()      # <=
    GREATER_EQUAL = auto()   # >=
    NOT_EQUAL = auto()       # !=
    COMPARE_EQUAL = auto()   # ==
    QUESTION = auto()        # ?
    QUESTION_EQUALS = auto() # ?= (null-safe equals)
    COLON = auto()           # :
    AT = auto()              # @ (for scripted values like @my_value)
    PLUS = auto()            # + (in expressions)
    MINUS = auto()           # - (standalone, not part of number)
    STAR = auto()            # * (multiplication)
    SLASH = auto()           # / (division)
    PARAM = auto()           # $PARAM$ (parameter substitution)
    COMMENT = auto()         # # comment to end of line
    NEWLINE = auto()         # \n
    EOF = auto()             # End of file
    BOOL = auto()            # yes, no
    COMMA = auto()           # , (used in some defines like { "a", "b" })


@dataclass
class Token:
    """A single token from the lexer."""
    type: TokenType
    value: str
    line: int
    column: int
    
    def __repr__(self):
        if self.type == TokenType.NEWLINE:
            return f"Token({self.type.name}, '\\n', L{self.line}:{self.column})"
        return f"Token({self.type.name}, {self.value!r}, L{self.line}:{self.column})"


class LexerError(Exception):
    """Error during lexical analysis."""
    def __init__(self, message: str, line: int, column: int):
        self.line = line
        self.column = column
        super().__init__(f"Lexer error at line {line}, column {column}: {message}")


class Lexer:
    """
    Tokenizer for Paradox/CK3 script files.
    
    Usage:
        lexer = Lexer(source_text)
        tokens = list(lexer.tokenize())
    """
    
    # Characters that can appear in identifiers
    # Note: | is used in define:Namespace|CONSTANT syntax
    # Note: & can appear in identifiers (eliminate_&_replace_faith_effect)
    # Note: ' (apostrophe) can appear in some barony names (b_mansa'l-kharaz)
    # Note: / is used in sound paths (event:/SFX/Events/...)
    # Note: Unicode letters allowed for names like Linnéa, Θ (theta), etc.
    # Note: % can appear in identifiers (SUCCESS_%) and number suffixes (29%)
    IDENT_SPECIAL = set("_.|&'-:/%")  # Special chars allowed in identifiers
    
    @staticmethod
    def _is_ident_start(ch: str) -> bool:
        """Check if character can start an identifier (letter or underscore)."""
        return ch == '_' or ch.isalpha()
    
    @staticmethod  
    def _is_ident_cont(ch: str) -> bool:
        """Check if character can continue an identifier."""
        return ch.isalnum() or ch in Lexer.IDENT_SPECIAL
    
    def __init__(self, source: str, filename: str = "<unknown>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.column = 1
        self.length = len(source)
    
    def _current(self) -> Optional[str]:
        """Get current character or None if at end."""
        if self.pos >= self.length:
            return None
        return self.source[self.pos]
    
    def _peek(self, offset: int = 1) -> Optional[str]:
        """Peek ahead by offset characters."""
        pos = self.pos + offset
        if pos >= self.length:
            return None
        return self.source[pos]
    
    def _advance(self) -> Optional[str]:
        """Advance one character and return it."""
        ch = self._current()
        if ch is not None:
            self.pos += 1
            if ch == '\n':
                self.line += 1
                self.column = 1
            else:
                self.column += 1
        return ch
    
    def _skip_whitespace(self) -> None:
        """Skip spaces and tabs (but not newlines)."""
        while self._current() in (' ', '\t', '\r'):
            self._advance()
    
    def _read_string(self, quote_char: str = '"') -> str:
        """Read a quoted string, handling escapes. Supports both " and ' quotes."""
        start_line = self.line
        start_col = self.column
        
        # Skip opening quote
        self._advance()
        
        result = []
        while True:
            ch = self._current()
            if ch is None:
                raise LexerError("Unterminated string", start_line, start_col)
            if ch == quote_char:
                self._advance()  # Skip closing quote
                break
            if ch == '\\':
                # Handle escape sequences
                self._advance()
                esc = self._current()
                if esc == 'n':
                    result.append('\n')
                elif esc == 't':
                    result.append('\t')
                elif esc == quote_char:
                    result.append(quote_char)
                elif esc == '\\':
                    result.append('\\')
                else:
                    # Unknown escape, keep as-is
                    result.append('\\')
                    if esc:
                        result.append(esc)
                self._advance()
            else:
                result.append(ch)
                self._advance()
        
        return ''.join(result)
    
    def _read_identifier(self) -> str:
        """Read an identifier (including dotted names like scope.thing)."""
        result = []
        while True:
            ch = self._current()
            if ch is None:
                break
            if self._is_ident_cont(ch):
                result.append(ch)
                self._advance()
            else:
                break
        return ''.join(result)
    
    def _read_number(self) -> str:
        """Read a number (integer or decimal)."""
        result = []
        # Handle negative sign
        if self._current() == '-':
            result.append('-')
            self._advance()
        
        # Read digits and decimal point
        has_dot = False
        while True:
            ch = self._current()
            if ch is None:
                break
            if ch.isdigit():
                result.append(ch)
                self._advance()
            elif ch == '.' and not has_dot:
                has_dot = True
                result.append(ch)
                self._advance()
            else:
                break
        
        # Check for trailing % (e.g., 29% in GUI position values)
        if self._current() == '%':
            result.append('%')
            self._advance()
        
        return ''.join(result)
    
    def _read_comment(self) -> str:
        """Read a comment from # to end of line."""
        result = []
        # Skip the #
        self._advance()
        while True:
            ch = self._current()
            if ch is None or ch == '\n':
                break
            result.append(ch)
            self._advance()
        return ''.join(result)
    
    def tokenize(self, include_comments: bool = False, include_newlines: bool = False) -> Iterator[Token]:
        """
        Generate tokens from the source.
        
        Args:
            include_comments: If True, emit COMMENT tokens. Otherwise skip them.
            include_newlines: If True, emit NEWLINE tokens. Otherwise skip them.
        """
        while True:
            self._skip_whitespace()
            
            ch = self._current()
            start_line = self.line
            start_col = self.column
            
            if ch is None:
                yield Token(TokenType.EOF, '', start_line, start_col)
                break
            
            # Newline
            if ch == '\n':
                self._advance()
                if include_newlines:
                    yield Token(TokenType.NEWLINE, '\n', start_line, start_col)
                continue
            
            # Comment
            if ch == '#':
                comment = self._read_comment()
                if include_comments:
                    yield Token(TokenType.COMMENT, comment, start_line, start_col)
                continue
            
            # String (double or single quoted)
            if ch == '"':
                value = self._read_string('"')
                yield Token(TokenType.STRING, value, start_line, start_col)
                continue
            
            if ch == "'":
                value = self._read_string("'")
                yield Token(TokenType.STRING, value, start_line, start_col)
                continue
            
            # Operators (multi-char first)
            if ch == '<':
                self._advance()
                if self._current() == '=':
                    self._advance()
                    yield Token(TokenType.LESS_EQUAL, '<=', start_line, start_col)
                else:
                    yield Token(TokenType.LESS_THAN, '<', start_line, start_col)
                continue
            
            if ch == '>':
                self._advance()
                if self._current() == '=':
                    self._advance()
                    yield Token(TokenType.GREATER_EQUAL, '>=', start_line, start_col)
                else:
                    yield Token(TokenType.GREATER_THAN, '>', start_line, start_col)
                continue
            
            if ch == '!':
                self._advance()
                if self._current() == '=':
                    self._advance()
                    yield Token(TokenType.NOT_EQUAL, '!=', start_line, start_col)
                else:
                    # Standalone ! is not valid in CK3 script syntax
                    raise LexerError(f"Unexpected character '!'", start_line, start_col)
                continue
            
            if ch == '=':
                self._advance()
                if self._current() == '=':
                    self._advance()
                    yield Token(TokenType.COMPARE_EQUAL, '==', start_line, start_col)
                else:
                    yield Token(TokenType.EQUALS, '=', start_line, start_col)
                continue
            
            # Single-char operators
            if ch == '{':
                self._advance()
                yield Token(TokenType.LBRACE, '{', start_line, start_col)
                continue
            
            if ch == '}':
                self._advance()
                yield Token(TokenType.RBRACE, '}', start_line, start_col)
                continue
            
            if ch == '?':
                self._advance()
                # Check for ?= (null-coalescing equals)
                if self._current() == '=':
                    self._advance()
                    yield Token(TokenType.QUESTION_EQUALS, '?=', start_line, start_col)
                else:
                    yield Token(TokenType.QUESTION, '?', start_line, start_col)
                continue
            
            if ch == ':':
                self._advance()
                yield Token(TokenType.COLON, ':', start_line, start_col)
                continue
            
            if ch == '@':
                self._advance()
                yield Token(TokenType.AT, '@', start_line, start_col)
                continue
            
            # Brackets for inline expressions like @[value + 10]
            if ch == '[':
                self._advance()
                yield Token(TokenType.LBRACKET, '[', start_line, start_col)
                continue
            
            if ch == ']':
                self._advance()
                yield Token(TokenType.RBRACKET, ']', start_line, start_col)
                continue
            
            # Math operators for inline expressions
            if ch == '+':
                self._advance()
                yield Token(TokenType.PLUS, '+', start_line, start_col)
                continue
            
            if ch == '-':
                # Check if this is a negative number or standalone minus
                if self._peek() and self._peek().isdigit():
                    value = self._read_number()
                    yield Token(TokenType.NUMBER, value, start_line, start_col)
                else:
                    self._advance()
                    yield Token(TokenType.MINUS, '-', start_line, start_col)
                continue
            
            if ch == '*':
                self._advance()
                yield Token(TokenType.STAR, '*', start_line, start_col)
                continue
            
            if ch == '/':
                self._advance()
                yield Token(TokenType.SLASH, '/', start_line, start_col)
                continue
            
            # Comma (used in some defines like { "friend", "rival" })
            if ch == ',':
                self._advance()
                yield Token(TokenType.COMMA, ',', start_line, start_col)
                continue
            
            # Parameter substitution: $PARAM$
            if ch == '$':
                self._advance()
                param_name = []
                while self._current() and self._current() not in ('$', ' ', '\t', '\n', '\r', '=', '{', '}'):
                    param_name.append(self._advance())
                if self._current() == '$':
                    self._advance()
                yield Token(TokenType.PARAM, '$' + ''.join(param_name) + '$', start_line, start_col)
                continue
            
            # Number (positive numbers only - negative handled by MINUS token above)
            if ch.isdigit():
                value = self._read_number()
                yield Token(TokenType.NUMBER, value, start_line, start_col)
                continue
            
            # Identifier (or yes/no boolean)
            # Identifier (including scope chains like .host after $PARAM$)
            # Allow . at start for scope continuation
            if self._is_ident_start(ch) or ch == '.':
                value = self._read_identifier()
                # If it's just a dot, skip forward for the actual identifier
                if value == '.':
                    # Standalone dot - treat as continuation marker for scope chain
                    value = '.' + self._read_identifier()
                if value in ('yes', 'no'):
                    yield Token(TokenType.BOOL, value, start_line, start_col)
                else:
                    yield Token(TokenType.IDENTIFIER, value, start_line, start_col)
                continue
            
            # Unknown character
            raise LexerError(f"Unexpected character {ch!r}", start_line, start_col)
    
    def tokenize_all(self, include_comments: bool = False, include_newlines: bool = False) -> List[Token]:
        """Convenience method to get all tokens as a list."""
        return list(self.tokenize(include_comments, include_newlines))


def tokenize_file(filepath: str, **kwargs) -> List[Token]:
    """Tokenize a file and return all tokens. Handles encoding fallback."""
    # Try UTF-8 with BOM first, then UTF-8, then latin-1 (which always succeeds)
    for encoding in ['utf-8-sig', 'utf-8', 'latin-1']:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                source = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    lexer = Lexer(source, filename=filepath)
    return lexer.tokenize_all(**kwargs)


if __name__ == "__main__":
    # Quick test
    test_source = '''
    # This is a comment
    tradition_mountain_homes = {
        name = "Mountain Homes"
        description = "A test tradition"
        
        ai_will_do = {
            base = 10
            modifier = {
                factor = 2
                has_trait = brave
            }
        }
        
        heavy_infantry_damage = 0.15
        enabled = yes
    }
    '''
    
    lexer = Lexer(test_source, "<test>")
    print("Tokens:")
    for token in lexer.tokenize():
        print(f"  {token}")
