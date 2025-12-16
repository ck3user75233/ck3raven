"""
Pytest configuration and shared fixtures.
"""

import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Import ck3raven modules
from ck3raven.parser import parse_file, parse_source
from ck3raven.parser.parser import RootNode, BlockNode, AssignmentNode
from ck3raven.resolver import MergePolicy, CONTENT_TYPES, get_policy_for_path


# =============================================================================
# PATH FIXTURES
# =============================================================================

@pytest.fixture
def fixtures_dir():
    """Path to test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def traditions_dir(fixtures_dir):
    """Path to traditions fixtures."""
    return fixtures_dir / "traditions"


@pytest.fixture
def on_actions_dir(fixtures_dir):
    """Path to on_actions fixtures."""
    return fixtures_dir / "on_actions"


# =============================================================================
# PARSED AST FIXTURES
# =============================================================================

@pytest.fixture
def parsed_traditions(traditions_dir):
    """Parse all tradition fixture files, return dict of {filename: AST}."""
    result = {}
    for file_path in sorted(traditions_dir.glob("*.txt")):
        result[file_path.name] = parse_file(str(file_path))
    return result


@pytest.fixture
def parsed_on_actions(on_actions_dir):
    """Parse all on_action fixture files, return dict of {filename: AST}."""
    result = {}
    for file_path in sorted(on_actions_dir.glob("*.txt")):
        result[file_path.name] = parse_file(str(file_path))
    return result


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def extract_block_keys(ast: RootNode, prefix: str = None) -> list:
    """Extract all top-level block names from an AST."""
    keys = []
    for child in ast.children:
        if isinstance(child, BlockNode):
            if prefix is None or child.name.startswith(prefix):
                keys.append(child.name)
    return keys


def get_block_by_name(ast: RootNode, name: str) -> BlockNode:
    """Find a specific block by name in an AST."""
    for child in ast.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None


def get_assignment_value(block: BlockNode, key: str):
    """Get the value of an assignment within a block."""
    for child in block.children:
        if isinstance(child, AssignmentNode) and child.key == key:
            return child.value
    return None


def get_sub_block(block: BlockNode, name: str) -> BlockNode:
    """Get a sub-block by name within a block."""
    for child in block.children:
        if isinstance(child, BlockNode) and child.name == name:
            return child
    return None
