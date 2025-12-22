"""
Paradox Localization Parser

Parses CK3 localization files (.yml) which use a custom format:

    l_english:
     key:VERSION "value with [Scope.Function] and $variable$ refs"

NOT standard YAML - has special runtime codes like [scope], $var$, #format#!
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Iterator, Tuple


@dataclass
class LocalizationEntry:
    """A single localization key-value entry."""
    key: str
    version: int
    raw_value: str
    line_number: int
    
    # Extracted references
    scripted_refs: List[str] = field(default_factory=list)  # [Scope.Function]
    variable_refs: List[str] = field(default_factory=list)  # $other_key$
    icon_refs: List[str] = field(default_factory=list)       # @icon!
    
    @property
    def plain_text(self) -> str:
        """Strip all codes to get plain display text."""
        text = self.raw_value
        # Remove scripted refs: [anything]
        text = re.sub(r'\[[^\]]+\]', '', text)
        # Remove variable refs: $var$
        text = re.sub(r'\$[a-zA-Z_][a-zA-Z0-9_]*\$', '', text)
        # Remove format codes: #code and #!
        text = re.sub(r'#[a-zA-Z_]+', '', text)
        text = text.replace('#!', '')
        # Remove icons: @icon!
        text = re.sub(r'@[a-zA-Z_][a-zA-Z0-9_]*!?', '', text)
        # Clean up whitespace
        text = ' '.join(text.split())
        return text


@dataclass 
class LocalizationFile:
    """Parsed localization file."""
    language: str
    entries: List[LocalizationEntry]
    parse_errors: List[Tuple[int, str]] = field(default_factory=list)


# Regex patterns
# Language header: l_english:
LANGUAGE_HEADER = re.compile(r'^\s*l_([a-z]+):\s*$')

# Entry: key:VERSION "value" OR key: "value" (version optional)
# Version is optional - some entries use key: "value" without version number
# Keys can contain dots (e.g., event.0001.t, trait_brave.desc)
# Keys can start with digits (e.g., 6540_exotic_wares_gift_modifier)
LOC_ENTRY = re.compile(r'^\s*([a-zA-Z0-9_][a-zA-Z0-9_.]*):(\d*)\s+"(.*)"$')

# Reference patterns within values
SCRIPTED_REF = re.compile(r'\[([^\]]+)\]')
VARIABLE_REF = re.compile(r'\$([a-zA-Z_][a-zA-Z0-9_]*)\$')
ICON_REF = re.compile(r'@([a-zA-Z_][a-zA-Z0-9_]*)!?')


def parse_localization(content: str, filename: str = "unknown.yml") -> LocalizationFile:
    """
    Parse a Paradox localization file.
    
    Args:
        content: File content
        filename: For error messages
        
    Returns:
        LocalizationFile with parsed entries
    """
    # Normalize line endings to Unix-style
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    
    lines = content.split('\n')
    language = None
    entries = []
    errors = []
    
    for line_num, line in enumerate(lines, 1):
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
            
        # Check for language header
        lang_match = LANGUAGE_HEADER.match(line)
        if lang_match:
            if language is None:
                language = lang_match.group(1)
            continue
            
        # Try to parse as entry
        entry_match = LOC_ENTRY.match(line)
        if entry_match:
            key, version_str, raw_value = entry_match.groups()
            
            # Version is optional - default to 0 if not specified
            version = int(version_str) if version_str else 0
            
            # Extract references
            scripted = SCRIPTED_REF.findall(raw_value)
            variables = VARIABLE_REF.findall(raw_value)
            icons = ICON_REF.findall(raw_value)
            
            entry = LocalizationEntry(
                key=key,
                version=version,
                raw_value=raw_value,
                line_number=line_num,
                scripted_refs=scripted,
                variable_refs=variables,
                icon_refs=icons,
            )
            entries.append(entry)
        elif stripped and not stripped.startswith('#'):
            # Non-empty, non-comment line that didn't match - might be continuation
            # or malformed entry
            if ':' in stripped and '"' in stripped:
                errors.append((line_num, f"Malformed entry: {stripped[:60]}..."))
    
    return LocalizationFile(
        language=language or 'unknown',
        entries=entries,
        parse_errors=errors,
    )


def parse_localization_entries(content: str) -> Iterator[LocalizationEntry]:
    """
    Generator that yields LocalizationEntry objects from content.
    
    Use this for streaming/memory-efficient parsing.
    """
    result = parse_localization(content)
    yield from result.entries


# Test when run directly
if __name__ == "__main__":
    test_content = '''l_english:
 trait_brave:0 "Brave"
 trait_brave_desc:2 "This [ROOT.Char.GetHerHis] character is brave. $bonus_line$"
 #comment line
 
 complex_key:1 "Line with #formatting code#! and @icon!"
 with_newline:0 "First line\\nSecond line"
'''
    
    result = parse_localization(test_content, "test.yml")
    print(f"Language: {result.language}")
    print(f"Entries: {len(result.entries)}")
    print(f"Errors: {len(result.parse_errors)}")
    print()
    
    for entry in result.entries:
        print(f"KEY: {entry.key}:{entry.version}")
        print(f"  RAW: {entry.raw_value[:60]}..." if len(entry.raw_value) > 60 else f"  RAW: {entry.raw_value}")
        print(f"  PLAIN: {entry.plain_text}")
        if entry.scripted_refs:
            print(f"  SCRIPTED: {entry.scripted_refs}")
        if entry.variable_refs:
            print(f"  VARIABLES: {entry.variable_refs}")
        if entry.icon_refs:
            print(f"  ICONS: {entry.icon_refs}")
        print()
