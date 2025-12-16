"""
PDX Code Formatter

Normalizes PDX/CK3 script files to consistent formatting:
- Consistent tab indentation
- Proper spacing around operators
- Consistent brace placement
- Sorted blocks (optional)

Usage:
    python -m ck3raven.tools.format <file>                    # Format and print to stdout
    python -m ck3raven.tools.format <file> --inplace          # Format in place
    python -m ck3raven.tools.format <file> --check            # Check if formatted (exit 1 if not)
    python -m ck3raven.tools.format <directory> --recursive   # Format all .txt files
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Union
from dataclasses import dataclass
from enum import Enum

from ..parser import parse_file, parse_source
from ..parser.parser import RootNode, BlockNode, AssignmentNode, ValueNode, ListNode


class FormatStyle(Enum):
    """Formatting style options."""
    STANDARD = "standard"       # Default CK3 style
    COMPACT = "compact"         # Minimize whitespace
    EXPANDED = "expanded"       # Maximum readability


@dataclass
class FormatOptions:
    """Configuration for the formatter."""
    indent_char: str = "\t"           # Tab or spaces
    indent_size: int = 1              # Number of indent chars per level
    space_around_equals: bool = True  # key = value vs key=value
    brace_on_same_line: bool = True   # key = { vs key =\n{
    sort_blocks: bool = False         # Alphabetize top-level blocks
    sort_keys: bool = False           # Alphabetize keys within blocks
    inline_short_lists: bool = True   # { a b c } vs multi-line
    inline_list_max_items: int = 5    # Max items for inline list
    blank_lines_between_blocks: int = 1  # Blank lines between top-level blocks
    max_line_length: int = 120        # For future use


class PDXFormatter:
    """
    Formats PDX script files to consistent style.
    
    The formatter works by:
    1. Parsing the file to AST
    2. Walking the AST and serializing with consistent formatting
    3. Outputting the result
    """
    
    def __init__(self, options: FormatOptions = None):
        self.options = options or FormatOptions()
    
    def format_file(self, file_path: Path) -> str:
        """Format a file and return the formatted content."""
        ast = parse_file(str(file_path))
        return self.format_ast(ast)
    
    def format_string(self, content: str, filename: str = "<string>") -> str:
        """Format a string of PDX content."""
        ast = parse_source(content, filename)
        return self.format_ast(ast)
    
    def format_ast(self, root: RootNode) -> str:
        """Format an AST to string."""
        lines = []
        
        children = root.children
        if self.options.sort_blocks:
            children = sorted(children, key=lambda c: getattr(c, 'name', '') or getattr(c, 'key', ''))
        
        for i, child in enumerate(children):
            if isinstance(child, BlockNode):
                lines.append(self._format_block(child, indent=0))
            elif isinstance(child, AssignmentNode):
                lines.append(self._format_assignment(child, indent=0))
            
            # Add blank lines between top-level blocks
            if i < len(children) - 1:
                lines.append("")
        
        return "\n".join(lines) + "\n"
    
    def _indent(self, level: int) -> str:
        """Get indentation string for a level."""
        return self.options.indent_char * (self.options.indent_size * level)
    
    def _format_block(self, block: BlockNode, indent: int) -> str:
        """Format a block node."""
        ind = self._indent(indent)
        lines = []
        
        # Opening line
        op = block.operator
        space = " " if self.options.space_around_equals else ""
        lines.append(f"{ind}{block.name}{space}{op}{space}{{")
        
        # Children
        children = block.children
        if self.options.sort_keys:
            # Sort assignments by key, keep blocks in relative order
            assignments = [(i, c) for i, c in enumerate(children) if isinstance(c, AssignmentNode)]
            blocks = [(i, c) for i, c in enumerate(children) if isinstance(c, BlockNode)]
            values = [(i, c) for i, c in enumerate(children) if isinstance(c, ValueNode)]
            
            assignments.sort(key=lambda x: x[1].key)
            # Reconstruct in order: values first, then sorted assignments, then blocks
            children = [c for _, c in values] + [c for _, c in assignments] + [c for _, c in blocks]
        
        for child in children:
            if isinstance(child, AssignmentNode):
                lines.append(self._format_assignment(child, indent + 1))
            elif isinstance(child, BlockNode):
                lines.append(self._format_block(child, indent + 1))
            elif isinstance(child, ValueNode):
                lines.append(f"{self._indent(indent + 1)}{self._format_value(child)}")
        
        # Closing brace
        lines.append(f"{ind}}}")
        
        return "\n".join(lines)
    
    def _format_assignment(self, assign: AssignmentNode, indent: int) -> str:
        """Format an assignment node."""
        ind = self._indent(indent)
        space = " " if self.options.space_around_equals else ""
        
        if isinstance(assign.value, ValueNode):
            val = self._format_value(assign.value)
            return f"{ind}{assign.key}{space}{assign.operator}{space}{val}"
        
        elif isinstance(assign.value, BlockNode):
            # Inline block
            inner_lines = []
            for child in assign.value.children:
                if isinstance(child, AssignmentNode):
                    inner_lines.append(self._format_assignment(child, indent + 1))
                elif isinstance(child, BlockNode):
                    inner_lines.append(self._format_block(child, indent + 1))
                elif isinstance(child, ValueNode):
                    inner_lines.append(f"{self._indent(indent + 1)}{self._format_value(child)}")
            
            if inner_lines:
                inner = "\n".join(inner_lines)
                return f"{ind}{assign.key}{space}{assign.operator}{space}{{\n{inner}\n{ind}}}"
            else:
                return f"{ind}{assign.key}{space}{assign.operator}{space}{{ }}"
        
        elif isinstance(assign.value, ListNode):
            list_str = self._format_list(assign.value, indent)
            return f"{ind}{assign.key}{space}{assign.operator}{space}{list_str}"
        
        else:
            return f"{ind}{assign.key}{space}{assign.operator}{space}{assign.value}"
    
    def _format_value(self, value: ValueNode) -> str:
        """Format a value node."""
        if value.value_type == 'string':
            # Ensure proper quoting
            return f'"{value.value}"'
        return str(value.value)
    
    def _format_list(self, lst: ListNode, indent: int) -> str:
        """Format a list node."""
        if not lst.items:
            return "{ }"
        
        # Check if we can inline this list
        all_simple = all(isinstance(item, ValueNode) for item in lst.items)
        short_enough = len(lst.items) <= self.options.inline_list_max_items
        
        if self.options.inline_short_lists and all_simple and short_enough:
            items = " ".join(self._format_value(item) for item in lst.items)
            return f"{{ {items} }}"
        
        # Multi-line list
        lines = ["{"]
        for item in lst.items:
            if isinstance(item, ValueNode):
                lines.append(f"{self._indent(indent + 1)}{self._format_value(item)}")
            elif isinstance(item, AssignmentNode):
                lines.append(self._format_assignment(item, indent + 1))
            elif isinstance(item, BlockNode):
                lines.append(self._format_block(item, indent + 1))
        lines.append(f"{self._indent(indent)}}}")
        
        return "\n".join(lines)


def format_file(file_path: Path, options: FormatOptions = None) -> str:
    """Convenience function to format a file."""
    formatter = PDXFormatter(options)
    return formatter.format_file(file_path)


def check_formatted(file_path: Path, options: FormatOptions = None) -> bool:
    """Check if a file is already formatted. Returns True if formatted."""
    formatter = PDXFormatter(options)
    formatted = formatter.format_file(file_path)
    
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        original = f.read()
    
    return formatted == original


def format_directory(dir_path: Path, pattern: str = "*.txt", 
                    recursive: bool = True, inplace: bool = False,
                    options: FormatOptions = None) -> List[Path]:
    """Format all matching files in a directory."""
    formatter = PDXFormatter(options)
    formatted_files = []
    
    glob_method = dir_path.rglob if recursive else dir_path.glob
    
    for file_path in glob_method(pattern):
        if not file_path.is_file():
            continue
        
        try:
            result = formatter.format_file(file_path)
            
            if inplace:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(result)
            
            formatted_files.append(file_path)
            
        except Exception as e:
            print(f"Error formatting {file_path}: {e}", file=sys.stderr)
    
    return formatted_files


def main():
    parser = argparse.ArgumentParser(description="Format PDX/CK3 script files")
    parser.add_argument("path", type=Path, help="File or directory to format")
    parser.add_argument("--inplace", "-i", action="store_true", 
                       help="Modify files in place")
    parser.add_argument("--check", "-c", action="store_true",
                       help="Check if files are formatted (exit 1 if not)")
    parser.add_argument("--recursive", "-r", action="store_true",
                       help="Recursively format directory")
    parser.add_argument("--sort-blocks", action="store_true",
                       help="Sort top-level blocks alphabetically")
    parser.add_argument("--sort-keys", action="store_true",
                       help="Sort keys within blocks")
    parser.add_argument("--compact", action="store_true",
                       help="Use compact formatting style")
    
    args = parser.parse_args()
    
    # Build options
    options = FormatOptions()
    if args.sort_blocks:
        options.sort_blocks = True
    if args.sort_keys:
        options.sort_keys = True
    if args.compact:
        options.space_around_equals = False
        options.inline_list_max_items = 10
    
    formatter = PDXFormatter(options)
    
    if args.path.is_file():
        # Single file
        if args.check:
            if check_formatted(args.path, options):
                print(f"✓ {args.path} is formatted")
                sys.exit(0)
            else:
                print(f"✗ {args.path} needs formatting")
                sys.exit(1)
        
        try:
            result = formatter.format_file(args.path)
            
            if args.inplace:
                with open(args.path, 'w', encoding='utf-8') as f:
                    f.write(result)
                print(f"Formatted: {args.path}")
            else:
                print(result)
                
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    
    elif args.path.is_dir():
        # Directory
        files = format_directory(args.path, recursive=args.recursive, 
                                inplace=args.inplace, options=options)
        print(f"Formatted {len(files)} files")
    
    else:
        print(f"Error: {args.path} not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
