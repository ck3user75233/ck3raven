"""
CK3/Paradox Script Parser

Converts a token stream from the lexer into an Abstract Syntax Tree (AST).
Handles nested blocks, key-value pairs, and lists.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Union, Dict, Any
from enum import Enum, auto

from ck3raven.parser.lexer import Lexer, Token, TokenType, LexerError


class NodeType(Enum):
    """Types of AST nodes."""
    ROOT = auto()           # Top-level container
    BLOCK = auto()          # name = { ... }
    ASSIGNMENT = auto()     # key = value
    VALUE = auto()          # standalone value (in a list)
    LIST = auto()           # { item1 item2 item3 }
    OPERATOR_EXPR = auto()  # key < value, key >= value, etc.


@dataclass
class ASTNode:
    """Base class for AST nodes."""
    node_type: NodeType = None  # Set by subclasses in __post_init__
    line: int = 0
    column: int = 0


@dataclass
class ValueNode(ASTNode):
    """A simple value (string, number, identifier, boolean)."""
    value: str = ""
    value_type: str = "identifier"  # 'string', 'number', 'identifier', 'bool'
    
    def __post_init__(self):
        self.node_type = NodeType.VALUE
    
    def __repr__(self):
        return f"Value({self.value!r}, {self.value_type})"
    
    def to_pdx(self, indent: int = 0) -> str:
        """Serialize value back to PDX format."""
        if self.value_type == 'string':
            return f'"{self.value}"'
        return str(self.value)


@dataclass
class AssignmentNode(ASTNode):
    """A key = value assignment."""
    key: str = ""
    operator: str = "="  # '=', '<', '>', '<=', '>=', '!=', '=='
    value: Union['ASTNode', 'BlockNode', 'ListNode', ValueNode] = None
    
    def __post_init__(self):
        self.node_type = NodeType.ASSIGNMENT
    
    def __repr__(self):
        return f"Assignment({self.key} {self.operator} {self.value})"
    
    def to_pdx(self, indent: int = 0) -> str:
        """Serialize assignment back to PDX format."""
        ind = '\t' * indent
        key_str = self.key
        
        if isinstance(self.value, ValueNode):
            val_str = self.value.to_pdx()
            return f"{ind}{key_str} {self.operator} {val_str}"
        elif isinstance(self.value, BlockNode):
            # Block gets its own serialization
            inner = self.value.to_pdx(indent=indent + 1, include_name=False)
            return f"{ind}{key_str} {self.operator} {{\n{inner}\n{ind}}}"
        elif isinstance(self.value, ListNode):
            inner = self.value.to_pdx(indent=indent + 1)
            return f"{ind}{key_str} {self.operator} {inner}"
        else:
            return f"{ind}{key_str} {self.operator} {self.value}"


@dataclass
class ListNode(ASTNode):
    """A list of values: { item1 item2 item3 }"""
    items: List[Union[ValueNode, 'AssignmentNode', 'BlockNode']] = field(default_factory=list)
    
    def __post_init__(self):
        self.node_type = NodeType.LIST
    
    def __repr__(self):
        return f"List({self.items})"
    
    def to_pdx(self, indent: int = 0) -> str:
        """Serialize list back to PDX format."""
        if not self.items:
            return "{ }"
        
        # For short lists of simple values, put on one line
        if len(self.items) <= 5 and all(isinstance(i, ValueNode) for i in self.items):
            items_str = " ".join(i.to_pdx() for i in self.items)
            return f"{{ {items_str} }}"
        
        # For longer/complex lists, multi-line
        ind = '\t' * indent
        lines = ["{"]
        for item in self.items:
            if isinstance(item, ValueNode):
                lines.append(f"{ind}\t{item.to_pdx()}")
            elif isinstance(item, AssignmentNode):
                lines.append(item.to_pdx(indent=indent + 1))
            elif isinstance(item, BlockNode):
                lines.append(item.to_pdx(indent=indent + 1))
        lines.append(f"{ind}}}")
        return "\n".join(lines)


@dataclass
class BlockNode(ASTNode):
    """A named block: name = { contents }"""
    name: str = ""
    children: List[Union['AssignmentNode', 'BlockNode', ValueNode, ListNode]] = field(default_factory=list)
    operator: str = '='  # Usually '=' but could be comparison operators
    
    def __post_init__(self):
        self.node_type = NodeType.BLOCK
    
    def __repr__(self):
        return f"Block({self.name}, {len(self.children)} children)"
    
    def to_pdx(self, indent: int = 0, include_name: bool = True) -> str:
        """Serialize block back to PDX format."""
        ind = '\t' * indent
        lines = []
        
        # Add opening line with name
        if include_name:
            lines.append(f"{ind}{self.name} {self.operator} {{")
        
        # Serialize children
        for child in self.children:
            if isinstance(child, AssignmentNode):
                lines.append(child.to_pdx(indent=indent + 1))
            elif isinstance(child, BlockNode):
                lines.append(child.to_pdx(indent=indent + 1))
            elif isinstance(child, ValueNode):
                lines.append(f"{ind}\t{child.to_pdx()}")
            elif isinstance(child, ListNode):
                # Rare - list directly in block without key
                lines.append(child.to_pdx(indent=indent + 1))
        
        # Add closing brace
        if include_name:
            lines.append(f"{ind}}}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {'_name': self.name, '_type': 'block'}
        for child in self.children:
            if isinstance(child, AssignmentNode):
                key = child.key
                if isinstance(child.value, ValueNode):
                    value = child.value.value
                elif isinstance(child.value, BlockNode):
                    value = child.value.to_dict()
                elif isinstance(child.value, ListNode):
                    value = [self._node_to_value(item) for item in child.value.items]
                else:
                    value = str(child.value)
                
                # Handle duplicate keys by making lists
                if key in result:
                    if not isinstance(result[key], list):
                        result[key] = [result[key]]
                    result[key].append(value)
                else:
                    result[key] = value
            elif isinstance(child, BlockNode):
                # Anonymous/inline block - rare but possible
                key = child.name
                value = child.to_dict()
                if key in result:
                    if not isinstance(result[key], list):
                        result[key] = [result[key]]
                    result[key].append(value)
                else:
                    result[key] = value
            elif isinstance(child, ValueNode):
                # Standalone value in block (part of a list-like structure)
                if '_values' not in result:
                    result['_values'] = []
                result['_values'].append(child.value)
        return result
    
    def _node_to_value(self, node):
        if isinstance(node, ValueNode):
            return node.value
        elif isinstance(node, BlockNode):
            return node.to_dict()
        elif isinstance(node, AssignmentNode):
            return {node.key: self._node_to_value(node.value)}
        return str(node)


@dataclass
class RootNode(ASTNode):
    """Root of the AST, contains all top-level definitions."""
    children: List[Union[BlockNode, AssignmentNode]] = field(default_factory=list)
    filename: str = "<unknown>"
    
    def __post_init__(self):
        self.node_type = NodeType.ROOT
    
    def __repr__(self):
        return f"Root({self.filename}, {len(self.children)} children)"
    
    def get_blocks(self, name_prefix: str = None) -> List[BlockNode]:
        """Get all top-level blocks, optionally filtered by name prefix."""
        blocks = [c for c in self.children if isinstance(c, BlockNode)]
        if name_prefix:
            blocks = [b for b in blocks if b.name.startswith(name_prefix)]
        return blocks
    
    def get_block(self, name: str) -> Optional[BlockNode]:
        """Get a specific block by exact name."""
        for child in self.children:
            if isinstance(child, BlockNode) and child.name == name:
                return child
        return None


class ParseError(Exception):
    """Error during parsing."""
    def __init__(self, message: str, token: Token = None):
        self.token = token
        if token:
            super().__init__(f"Parse error at line {token.line}, column {token.column}: {message}")
        else:
            super().__init__(f"Parse error: {message}")


class Parser:
    """
    Parser for Paradox/CK3 script files.
    
    Usage:
        parser = Parser(tokens)
        ast = parser.parse()
    """
    
    OPERATORS = {
        TokenType.EQUALS: '=',
        TokenType.LESS_THAN: '<',
        TokenType.GREATER_THAN: '>',
        TokenType.LESS_EQUAL: '<=',
        TokenType.GREATER_EQUAL: '>=',
        TokenType.NOT_EQUAL: '!=',
        TokenType.COMPARE_EQUAL: '==',
        TokenType.QUESTION_EQUALS: '?=',  # null-safe equals
    }
    
    def __init__(self, tokens: List[Token], filename: str = "<unknown>"):
        self.tokens = tokens
        self.filename = filename
        self.pos = 0
        self.length = len(tokens)
    
    def _current(self) -> Optional[Token]:
        """Get current token or None if at end."""
        if self.pos >= self.length:
            return None
        return self.tokens[self.pos]
    
    def _peek(self, offset: int = 1) -> Optional[Token]:
        """Peek ahead by offset tokens."""
        pos = self.pos + offset
        if pos >= self.length:
            return None
        return self.tokens[pos]
    
    def _advance(self) -> Optional[Token]:
        """Advance one token and return the previous one."""
        token = self._current()
        if token is not None:
            self.pos += 1
        return token
    
    def _expect(self, token_type: TokenType, message: str = None) -> Token:
        """Expect a specific token type, raise error if not found."""
        token = self._current()
        if token is None:
            raise ParseError(message or f"Expected {token_type.name}, got end of file")
        if token.type != token_type:
            raise ParseError(
                message or f"Expected {token_type.name}, got {token.type.name}",
                token
            )
        return self._advance()
    
    def _is_operator(self, token: Token) -> bool:
        """Check if token is an operator."""
        return token and token.type in self.OPERATORS
    
    def parse(self) -> RootNode:
        """Parse the token stream into an AST."""
        root = RootNode(filename=self.filename, line=1, column=1)
        
        while True:
            token = self._current()
            if token is None or token.type == TokenType.EOF:
                break
            
            # Parse top-level element
            node = self._parse_element()
            if node:
                root.children.append(node)
        
        return root
    
    def _parse_element(self) -> Optional[Union[BlockNode, AssignmentNode, ValueNode]]:
        """Parse a single element (block, assignment, or value)."""
        token = self._current()
        
        if token is None or token.type == TokenType.EOF:
            return None
        
        # Skip comments and newlines (shouldn't be in token stream normally)
        if token.type in (TokenType.COMMENT, TokenType.NEWLINE):
            self._advance()
            return self._parse_element()
        
        # Handle @ for scripted values (may be assignment like @foo = 30 or value like @foo)
        # Also handle @[expression] inline math
        if token.type == TokenType.AT:
            self._advance()
            next_token = self._current()
            
            # Handle @[expression] - inline math expression
            if next_token and next_token.type == TokenType.LBRACKET:
                self._advance()  # consume [
                # Read tokens until we hit ]
                expr_parts = []
                depth = 1
                while True:
                    t = self._current()
                    if t is None:
                        break
                    if t.type == TokenType.LBRACKET:
                        depth += 1
                        expr_parts.append('[')
                        self._advance()
                    elif t.type == TokenType.RBRACKET:
                        depth -= 1
                        if depth == 0:
                            self._advance()  # consume ]
                            break
                        expr_parts.append(']')
                        self._advance()
                    else:
                        expr_parts.append(t.value)
                        self._advance()
                
                expr_str = '@[' + ' '.join(expr_parts) + ']'
                return ValueNode(
                    value=expr_str,
                    value_type='inline_expression',
                    line=token.line,
                    column=token.column
                )
            
            # Regular @identifier
            ident = self._expect(TokenType.IDENTIFIER, "Expected identifier after @")
            scripted_name = f"@{ident.value}"
            
            # Check if this is an assignment
            next_token = self._current()
            if next_token and self._is_operator(next_token):
                operator = self.OPERATORS[next_token.type]
                self._advance()
                value = self._parse_value()
                return AssignmentNode(
                    key=scripted_name,
                    operator=operator,
                    value=value,
                    line=token.line,
                    column=token.column
                )
            
            return ValueNode(
                value=scripted_name,
                value_type='scripted_value',
                line=token.line,
                column=token.column
            )
        
        # Check for identifier/string/number/param that could be start of assignment or block
        if token.type in (TokenType.IDENTIFIER, TokenType.STRING, TokenType.NUMBER, TokenType.BOOL, TokenType.PARAM):
            return self._parse_assignment_or_value()
        
        # Handle standalone brace (anonymous block / list)
        if token.type == TokenType.LBRACE:
            return self._parse_block_contents()
        
        # Handle closing brace (return to caller)
        if token.type == TokenType.RBRACE:
            return None
        
        raise ParseError(f"Unexpected token {token.type.name}", token)
    
    def _parse_assignment_or_value(self) -> Union[AssignmentNode, BlockNode, ValueNode]:
        """Parse an assignment (key = value) or standalone value."""
        key_token = self._advance()
        key = key_token.value
        key_type = 'identifier'
        if key_token.type == TokenType.STRING:
            key_type = 'string'
        elif key_token.type == TokenType.NUMBER:
            key_type = 'number'
        elif key_token.type == TokenType.BOOL:
            key_type = 'bool'
        elif key_token.type == TokenType.PARAM:
            key_type = 'param'
        
        # Check for operator
        next_token = self._current()
        
        if next_token and self._is_operator(next_token):
            operator = self.OPERATORS[next_token.type]
            self._advance()
            
            # Parse the value
            value_token = self._current()
            
            if value_token is None:
                raise ParseError("Expected value after operator", next_token)
            
            if value_token.type == TokenType.LBRACE:
                # Block: key = { ... }
                block_contents = self._parse_block_contents()
                return BlockNode(
                    name=key,
                    operator=operator,
                    children=block_contents.items if isinstance(block_contents, ListNode) else [block_contents],
                    line=key_token.line,
                    column=key_token.column
                )
            elif value_token.type == TokenType.AT:
                # Scripted value: key = @value or key = @[expression]
                self._advance()
                next_after_at = self._current()
                
                # Handle @[expression] inline math
                if next_after_at and next_after_at.type == TokenType.LBRACKET:
                    self._advance()  # consume [
                    expr_parts = []
                    depth = 1
                    while True:
                        t = self._current()
                        if t is None:
                            break
                        if t.type == TokenType.LBRACKET:
                            depth += 1
                            expr_parts.append('[')
                            self._advance()
                        elif t.type == TokenType.RBRACKET:
                            depth -= 1
                            if depth == 0:
                                self._advance()  # consume ]
                                break
                            expr_parts.append(']')
                            self._advance()
                        else:
                            expr_parts.append(t.value)
                            self._advance()
                    
                    expr_str = '@[' + ' '.join(expr_parts) + ']'
                    value = ValueNode(
                        value=expr_str,
                        value_type='inline_expression',
                        line=value_token.line,
                        column=value_token.column
                    )
                else:
                    # Regular @identifier
                    ident = self._expect(TokenType.IDENTIFIER, "Expected identifier after @")
                    value = ValueNode(
                        value=f"@{ident.value}",
                        value_type='scripted_value',
                        line=value_token.line,
                        column=value_token.column
                    )
                return AssignmentNode(
                    key=key,
                    operator=operator,
                    value=value,
                    line=key_token.line,
                    column=key_token.column
                )
            else:
                # Simple value assignment
                value = self._parse_value()
                return AssignmentNode(
                    key=key,
                    operator=operator,
                    value=value,
                    line=key_token.line,
                    column=key_token.column
                )
        else:
            # Standalone value (no operator)
            return ValueNode(
                value=key,
                value_type=key_type,
                line=key_token.line,
                column=key_token.column
            )
    
    def _parse_value(self) -> ValueNode:
        """Parse a simple value (identifier, string, number, bool, param)."""
        token = self._current()
        
        if token is None:
            raise ParseError("Expected value, got end of file")
        
        if token.type == TokenType.IDENTIFIER:
            self._advance()
            return ValueNode(value=token.value, value_type='identifier', line=token.line, column=token.column)
        elif token.type == TokenType.STRING:
            self._advance()
            return ValueNode(value=token.value, value_type='string', line=token.line, column=token.column)
        elif token.type == TokenType.NUMBER:
            self._advance()
            return ValueNode(value=token.value, value_type='number', line=token.line, column=token.column)
        elif token.type == TokenType.BOOL:
            self._advance()
            return ValueNode(value=token.value, value_type='bool', line=token.line, column=token.column)
        elif token.type == TokenType.PARAM:
            self._advance()
            return ValueNode(value=token.value, value_type='param', line=token.line, column=token.column)
        elif token.type == TokenType.AT:
            self._advance()
            next_token = self._current()
            
            # Handle @[expression] - inline math expression
            if next_token and next_token.type == TokenType.LBRACKET:
                self._advance()  # consume [
                expr_parts = []
                depth = 1
                while True:
                    t = self._current()
                    if t is None:
                        break
                    if t.type == TokenType.LBRACKET:
                        depth += 1
                        expr_parts.append('[')
                        self._advance()
                    elif t.type == TokenType.RBRACKET:
                        depth -= 1
                        if depth == 0:
                            self._advance()  # consume ]
                            break
                        expr_parts.append(']')
                        self._advance()
                    else:
                        expr_parts.append(t.value)
                        self._advance()
                
                expr_str = '@[' + ' '.join(expr_parts) + ']'
                return ValueNode(
                    value=expr_str,
                    value_type='inline_expression',
                    line=token.line,
                    column=token.column
                )
            
            # Regular @identifier
            ident = self._expect(TokenType.IDENTIFIER, "Expected identifier after @")
            return ValueNode(value=f"@{ident.value}", value_type='scripted_value', line=token.line, column=token.column)
        else:
            raise ParseError(f"Expected value, got {token.type.name}", token)
    
    def _parse_block_contents(self) -> ListNode:
        """Parse the contents of a block (inside braces)."""
        self._expect(TokenType.LBRACE, "Expected '{'")
        
        items = []
        
        while True:
            token = self._current()
            
            if token is None:
                raise ParseError("Unexpected end of file in block")
            
            if token.type == TokenType.RBRACE:
                self._advance()
                break
            
            if token.type in (TokenType.COMMENT, TokenType.NEWLINE):
                self._advance()
                continue
            
            element = self._parse_element()
            if element:
                items.append(element)
        
        return ListNode(items=items, line=token.line if token else 0, column=token.column if token else 0)


def parse_source(source: str, filename: str = "<unknown>") -> RootNode:
    """Parse source code string into AST."""
    lexer = Lexer(source, filename)
    tokens = lexer.tokenize_all()
    parser = Parser(tokens, filename)
    return parser.parse()


def parse_file(filepath: str) -> RootNode:
    """Parse a file into AST."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        source = f.read()
    return parse_source(source, filepath)


if __name__ == "__main__":
    # Quick test
    test_source = '''
    # This is a tradition
    tradition_mountain_homes = {
        category = regional
        
        layers = {
            0 = martial
            1 = intrigue
        }
        
        is_shown = {
            OR = {
                has_cultural_pillar = heritage_north_germanic
                has_cultural_pillar = heritage_central_germanic
            }
        }
        
        can_pick = {
            NOT = { has_cultural_tradition = tradition_mountain_homes }
        }
        
        parameters = {
            mountain_trait_bonuses = yes
        }
        
        character_modifier = {
            mountains_advantage = 5
            hills_advantage = 5
        }
        
        cost = {
            prestige = {
                add = 1000
                multiply = tradition_base_cost_multiplier
            }
        }
        
        ai_will_do = {
            base = 10
            modifier = {
                factor = 2.0
                any_sub_realm_county = {
                    percent >= 0.3
                    any_county_province = {
                        terrain = mountains
                    }
                }
            }
        }
    }
    
    tradition_warrior_culture = {
        category = combat
        martial_bonus = 2
    }
    '''
    
    print("Parsing test source...")
    ast = parse_source(test_source, "<test>")
    print(f"Parsed: {ast}")
    print(f"\nTop-level blocks:")
    for block in ast.get_blocks():
        print(f"  - {block.name}")
        print(f"    Children: {len(block.children)}")
