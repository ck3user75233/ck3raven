"""
ck3raven.parser - Paradox Script Parser

Lexer and parser for CK3/Paradox script files.
Converts .txt files into an Abstract Syntax Tree (AST).

IMPORT ARCHITECTURE:
This module uses lazy imports to avoid loading the full parser when only
node types are needed (e.g., for ast_serde serialization).
"""


def __getattr__(name: str):
    """Lazy import - loads submodules only when accessed."""
    # Lexer exports
    if name in ("Lexer", "Token", "TokenType", "LexerError", "tokenize_file"):
        from ck3raven.parser import lexer
        return getattr(lexer, name)
    
    # Parser exports
    if name in ("Parser", "RecoveringParser", "ParseError", "ParseDiagnostic", 
                "ParseResult", "parse_file", "parse_source", "parse_source_recovering",
                "ASTNode", "NodeType", "RootNode", "BlockNode", "AssignmentNode",
                "ValueNode", "ListNode"):
        from ck3raven.parser import parser
        return getattr(parser, name)
    
    raise AttributeError(f"module 'ck3raven.parser' has no attribute {name!r}")


__all__ = [
    # Lexer
    "Lexer",
    "Token", 
    "TokenType",
    "LexerError",
    "tokenize_file",
    # Parser
    "Parser",
    "RecoveringParser",
    "ParseError",
    "ParseDiagnostic",
    "ParseResult",
    "parse_file",
    "parse_source",
    "parse_source_recovering",
    # AST Nodes
    "ASTNode",
    "NodeType",
    "RootNode",
    "BlockNode",
    "AssignmentNode",
    "ValueNode",
    "ListNode",
]
