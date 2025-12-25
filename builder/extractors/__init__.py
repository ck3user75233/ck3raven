"""
Builder Extractors

This package contains database population extractors that transform
source files into database rows. These are WRITE operations that
should ONLY be called by the builder daemon.

Subpackages:
    lookups/ - Lookup table extractors (province, character, dynasty, landed_titles)
"""

from builder.extractors.lookups import (
    extract_provinces,
    extract_characters,
    extract_dynasties,
    extract_landed_titles,
    extract_titles,  # Backwards compatibility alias
)

__all__ = [
    "extract_provinces",
    "extract_characters",
    "extract_dynasties",
    "extract_landed_titles",
    "extract_titles",
]
