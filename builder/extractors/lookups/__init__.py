"""
Lookup Table Extractors

Extract ID-keyed reference data from CK3 data files into lookup tables.
These handle numeric IDs that need to be resolved to human-readable names:
    - province IDs (e.g., 2333 → Paris)
    - character IDs (e.g., 163110 → Charlemagne)
    - dynasty IDs (e.g., 699 → Karling)
    - title mappings (k_france → tier='k', capital=c_paris)

Unlike symbols (string-keyed, from ASTs), lookups handle opaque numeric IDs.
"""

from builder.extractors.lookups.province import extract_provinces
from builder.extractors.lookups.character import extract_characters
from builder.extractors.lookups.dynasty import extract_dynasties
from builder.extractors.lookups.title import extract_titles
from builder.extractors.lookups.title_history import extract_title_history

__all__ = [
    "extract_provinces",
    "extract_characters", 
    "extract_dynasties",
    "extract_titles",
    "extract_title_history",
]
