"""
AST Serialization — Zero-dependency module for AST/JSON conversion.

ARCHITECTURAL RULE: This module has STRICTLY LIMITED dependencies:
- json (stdlib)
- typing (stdlib)  
- ck3raven.parser.parser (node types only)

NO database imports. NO schema imports. NO SQLite.

This isolation allows subprocess parsing to serialize ASTs without
loading the heavy database layer (~150ms import savings per subprocess).

Usage:
    from ck3raven.parser.ast_serde import serialize_ast, deserialize_ast, count_ast_nodes
"""

import json
from typing import Dict, Any, Union

# Import ONLY the node type classes - no database dependencies
from ck3raven.parser.parser import (
    RootNode,
    BlockNode, 
    AssignmentNode,
    ValueNode,
    ListNode,
)


def serialize_ast(ast: RootNode) -> bytes:
    """
    Serialize AST to JSON bytes.
    
    Args:
        ast: Parsed AST root node
        
    Returns:
        UTF-8 encoded JSON bytes
    """
    
    def node_to_dict(node) -> Dict[str, Any]:
        """Convert AST node to serializable dict."""
        if isinstance(node, RootNode):
            return {
                '_type': 'root',
                'filename': str(node.filename),  # Convert Path to string
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, BlockNode):
            return {
                '_type': 'block',
                'name': node.name,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'children': [node_to_dict(c) for c in node.children]
            }
        elif isinstance(node, AssignmentNode):
            return {
                '_type': 'assignment',
                'key': node.key,
                'operator': node.operator,
                'line': node.line,
                'column': node.column,
                'value': node_to_dict(node.value)
            }
        elif isinstance(node, ValueNode):
            return {
                '_type': 'value',
                'value': node.value,
                'value_type': node.value_type,
                'line': node.line,
                'column': node.column,
            }
        elif isinstance(node, ListNode):
            return {
                '_type': 'list',
                'line': node.line,
                'column': node.column,
                'items': [node_to_dict(i) for i in node.items]
            }
        else:
            return {'_type': 'unknown', 'repr': repr(node)}
    
    data = node_to_dict(ast)
    return json.dumps(data, separators=(',', ':')).encode('utf-8')


def deserialize_ast(data: Union[bytes, str]) -> Dict[str, Any]:
    """
    Deserialize AST from JSON bytes or string.
    
    Args:
        data: JSON bytes or string
        
    Returns:
        Dict representation of AST
    """
    if isinstance(data, bytes):
        return json.loads(data.decode('utf-8'))
    return json.loads(data)


def count_ast_nodes(ast_dict: Dict[str, Any]) -> int:
    """
    Count nodes in a serialized AST.
    
    Args:
        ast_dict: Deserialized AST dictionary
        
    Returns:
        Total node count
    """
    count = 1
    for key in ('children', 'items', 'value'):
        if key in ast_dict:
            val = ast_dict[key]
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        count += count_ast_nodes(item)
            elif isinstance(val, dict):
                count += count_ast_nodes(val)
    return count
