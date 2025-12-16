"""
Tests for the ck3raven parser module.
"""

import pytest
from ck3raven.parser import parse_source, parse_file, BlockNode, AssignmentNode, ValueNode


class TestBasicParsing:
    """Test basic parsing functionality."""
    
    def test_empty_source(self):
        """Parse empty source."""
        ast = parse_source("")
        assert len(ast.children) == 0
    
    def test_simple_assignment(self):
        """Parse simple key = value."""
        ast = parse_source('name = "Test"')
        assert len(ast.children) == 1
        assert isinstance(ast.children[0], AssignmentNode)
        assert ast.children[0].key == "name"
        assert ast.children[0].value.value == "Test"
    
    def test_simple_block(self):
        """Parse simple block."""
        ast = parse_source('my_block = { foo = bar }')
        assert len(ast.children) == 1
        assert isinstance(ast.children[0], BlockNode)
        assert ast.children[0].name == "my_block"
        assert len(ast.children[0].children) == 1
    
    def test_nested_blocks(self):
        """Parse nested blocks."""
        source = '''
        outer = {
            inner = {
                value = 42
            }
        }
        '''
        ast = parse_source(source)
        assert len(ast.children) == 1
        outer = ast.children[0]
        assert outer.name == "outer"
        inner = outer.children[0]
        assert isinstance(inner, BlockNode)
        assert inner.name == "inner"
    
    def test_number_values(self):
        """Parse number values."""
        ast = parse_source('value = 42\nfloat = 0.5\nneg = -10')
        assert len(ast.children) == 3
        assert ast.children[0].value.value == "42"
        assert ast.children[1].value.value == "0.5"
        assert ast.children[2].value.value == "-10"
    
    def test_boolean_values(self):
        """Parse yes/no booleans."""
        ast = parse_source('enabled = yes\ndisabled = no')
        assert len(ast.children) == 2
        assert ast.children[0].value.value == "yes"
        assert ast.children[0].value.value_type == "bool"
        assert ast.children[1].value.value == "no"
    
    def test_comments_ignored(self):
        """Comments should be ignored."""
        source = '''
        # This is a comment
        value = 42 # inline comment
        '''
        ast = parse_source(source)
        assert len(ast.children) == 1
        assert ast.children[0].key == "value"


class TestTraditionParsing:
    """Test parsing tradition-like structures."""
    
    def test_tradition_block(self):
        """Parse a typical tradition block."""
        source = '''
        tradition_mountain_homes = {
            category = regional
            
            parameters = {
                mountain_trait_bonuses = yes
            }
            
            character_modifier = {
                mountains_advantage = 5
            }
        }
        '''
        ast = parse_source(source)
        assert len(ast.children) == 1
        tradition = ast.children[0]
        assert tradition.name == "tradition_mountain_homes"
        assert len(tradition.children) == 3
    
    def test_get_blocks_by_prefix(self):
        """Test filtering blocks by prefix."""
        source = '''
        tradition_foo = { category = regional }
        tradition_bar = { category = combat }
        other_thing = { value = 1 }
        '''
        ast = parse_source(source)
        traditions = ast.get_blocks("tradition_")
        assert len(traditions) == 2
        assert all(b.name.startswith("tradition_") for b in traditions)


class TestOperators:
    """Test comparison operators."""
    
    def test_comparison_operators(self):
        """Parse comparison operators."""
        source = '''
        count < 5
        value > 10
        age >= 18
        prestige <= 1000
        factor != 0
        check == yes
        '''
        ast = parse_source(source)
        assert len(ast.children) == 6
        assert ast.children[0].operator == "<"
        assert ast.children[1].operator == ">"
        assert ast.children[2].operator == ">="
        assert ast.children[3].operator == "<="
        assert ast.children[4].operator == "!="
        assert ast.children[5].operator == "=="


class TestScriptedValues:
    """Test @ scripted value syntax."""
    
    def test_scripted_value_assignment(self):
        """Parse scripted value assignment."""
        ast = parse_source('@my_value = 100')
        assert len(ast.children) == 1
        assert ast.children[0].key == "@my_value"
    
    def test_scripted_value_reference(self):
        """Parse scripted value reference."""
        ast = parse_source('cost = @base_cost')
        assert len(ast.children) == 1
        assert ast.children[0].value.value == "@base_cost"
        assert ast.children[0].value.value_type == "scripted_value"


class TestSerialization:
    """Test AST to PDX serialization."""
    
    def test_round_trip_simple(self):
        """Parse and serialize should produce equivalent output."""
        source = 'name = "Test"'
        ast = parse_source(source)
        output = ast.children[0].to_pdx()
        assert 'name = "Test"' in output
    
    def test_block_serialization(self):
        """Block serialization should preserve structure."""
        source = '''
        my_block = {
            value = 42
            enabled = yes
        }
        '''
        ast = parse_source(source)
        output = ast.children[0].to_pdx()
        assert "my_block" in output
        assert "value = 42" in output
        assert "enabled = yes" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
