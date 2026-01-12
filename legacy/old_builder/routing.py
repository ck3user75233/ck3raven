"""
File Routing Table - Deterministic Processing Envelopes

This module defines the canonical routing table that maps file identity (path + extension)
to processing envelopes. The destination of a file is known at the moment it is identified.

CANONICAL PRINCIPLE:
> Each file has a known processing destination at the moment it is identified.
> The queue schedules/retries/resumes. It does not decide WHAT a file is.

Processing stages (bitmask flags):
- INGEST:      Read file from disk, store in file_contents
- PARSE:       Parse content → AST
- SYMBOLS:     Extract symbol definitions from AST
- REFS:        Extract symbol references from AST
- LOCALIZATION: Extract localization entries (YML files only)
- LOOKUPS:     Build lookup tables (traits, events, decisions, etc.)
"""

from enum import IntFlag, auto
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional


class ProcessingStage(IntFlag):
    """Bitmask flags for processing stages."""
    NONE = 0
    INGEST = auto()       # 1 - Read file, store content
    PARSE = auto()        # 2 - Parse to AST
    SYMBOLS = auto()      # 4 - Extract symbol definitions
    REFS = auto()         # 8 - Extract symbol references
    LOCALIZATION = auto() # 16 - Extract localization entries
    LOOKUPS = auto()      # 32 - Build lookup tables
    
    # Common combinations
    SCRIPT_FULL = INGEST | PARSE | SYMBOLS | REFS
    DATA_ONLY = INGEST  # Pure data files, no parsing
    LOC_FULL = INGEST | LOCALIZATION
    LOOKUP_ELIGIBLE = INGEST | PARSE | SYMBOLS | REFS | LOOKUPS


@dataclass(frozen=True)
class ProcessingEnvelope:
    """
    The complete set of processing steps for a file.
    
    Immutable once created. Determined at file identification time.
    """
    stages: ProcessingStage
    file_type: str  # Human-readable type name
    
    def requires(self, stage: ProcessingStage) -> bool:
        """Check if this envelope includes a stage."""
        return bool(self.stages & stage)
    
    @property
    def requires_parse(self) -> bool:
        return self.requires(ProcessingStage.PARSE)
    
    @property
    def requires_symbols(self) -> bool:
        return self.requires(ProcessingStage.SYMBOLS)
    
    @property
    def requires_refs(self) -> bool:
        return self.requires(ProcessingStage.REFS)


# =============================================================================
# ROUTING RULES (Order matters - first match wins)
# =============================================================================

# Folders that should be skipped entirely (pure data, no value in indexing)
SKIP_FOLDERS = frozenset({
    'gfx',
    'fonts',
    'music',
    'sound',
    'dlc_metadata',
    'content_source',
})

# Folders that are data-only (ingest but no parse/symbols/refs)
DATA_ONLY_FOLDERS = frozenset({
    'map_data',
    'common/bookmark_portraits',
    'common/genes',
    'common/event_backgrounds',
})

# Folders where ref extraction is skipped (large AST, 0 refs)
NO_REF_FOLDERS = frozenset({
    'common/landed_titles',
    'common/culture/name_equivalency',
})

# Folders that generate lookup tables
LOOKUP_FOLDERS = frozenset({
    'common/traits',
    'common/decisions',
    'events',
    'common/dynasties',
    'common/characters',
    'common/provinces',
    'common/titles',
    'common/holy_sites',
})

# Extensions that trigger localization processing
LOC_EXTENSIONS = frozenset({'.yml', '.yaml'})

# Extensions that are parseable CK3 script
SCRIPT_EXTENSIONS = frozenset({'.txt', '.gui', '.gfx', '.sfx', '.asset'})


def get_processing_envelope(relpath: str) -> Optional[ProcessingEnvelope]:
    """
    Determine the processing envelope for a file.
    
    This is the canonical routing function. It is DETERMINISTIC:
    same input always produces same output.
    
    Args:
        relpath: Relative path within content root (e.g., "common/traits/00_traits.txt")
    
    Returns:
        ProcessingEnvelope if file should be processed, None if should be skipped
    """
    path = PurePosixPath(relpath.replace('\\', '/').lower())
    ext = path.suffix.lower()
    
    # Get first folder component for classification
    parts = path.parts
    if not parts:
        return None
    
    first_folder = parts[0]
    
    # Check skip folders first
    if first_folder in SKIP_FOLDERS:
        return None
    
    # Build folder path for matching (e.g., "common/traits")
    folder_path = str(path.parent) if path.parent != PurePosixPath('.') else first_folder
    
    # Localization files
    if ext in LOC_EXTENSIONS:
        if 'localization' in folder_path or 'localisation' in folder_path:
            return ProcessingEnvelope(
                stages=ProcessingStage.LOC_FULL,
                file_type='localization'
            )
        # YML files outside localization folder - just ingest
        return ProcessingEnvelope(
            stages=ProcessingStage.INGEST,
            file_type='config_yml'
        )
    
    # Non-script extensions - ingest only or skip
    if ext not in SCRIPT_EXTENSIONS:
        if ext in {'.dds', '.png', '.jpg', '.tga', '.psd'}:
            return None  # Skip image files
        if ext in {'.mp3', '.wav', '.ogg'}:
            return None  # Skip audio files
        if ext in {'.ttf', '.otf'}:
            return None  # Skip font files
        # Other unknown extensions - ingest for reference but don't parse
        return ProcessingEnvelope(
            stages=ProcessingStage.INGEST,
            file_type='binary_data'
        )
    
    # Check data-only folders
    for data_folder in DATA_ONLY_FOLDERS:
        if folder_path.startswith(data_folder):
            return ProcessingEnvelope(
                stages=ProcessingStage.DATA_ONLY,
                file_type='data_structure'
            )
    
    # Check no-ref folders
    for no_ref_folder in NO_REF_FOLDERS:
        if folder_path.startswith(no_ref_folder):
            return ProcessingEnvelope(
                stages=ProcessingStage.INGEST | ProcessingStage.PARSE | ProcessingStage.SYMBOLS,
                file_type='hierarchical_data'
            )
    
    # Check lookup-eligible folders
    for lookup_folder in LOOKUP_FOLDERS:
        if folder_path.startswith(lookup_folder):
            return ProcessingEnvelope(
                stages=ProcessingStage.LOOKUP_ELIGIBLE,
                file_type=f'lookup:{lookup_folder.split("/")[-1]}'
            )
    
    # Default: full script processing
    return ProcessingEnvelope(
        stages=ProcessingStage.SCRIPT_FULL,
        file_type='script'
    )


def get_stage_order() -> list[ProcessingStage]:
    """
    Return stages in execution order.
    
    Within a single work item, these stages must execute in this order.
    This is an implementation detail internal to the worker.
    """
    return [
        ProcessingStage.INGEST,
        ProcessingStage.PARSE,
        ProcessingStage.SYMBOLS,
        ProcessingStage.REFS,
        ProcessingStage.LOCALIZATION,
        ProcessingStage.LOOKUPS,
    ]


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    # Test routing table
    test_cases = [
        ("common/traits/00_traits.txt", "lookup:traits"),
        ("events/lifestyle_events.txt", "lookup:events"),
        ("common/on_action/yearly.txt", "script"),
        ("localization/english/traits_l_english.yml", "localization"),
        ("common/genes/01_gene_categories.txt", "data_structure"),
        ("common/landed_titles/00_landed_titles.txt", "hierarchical_data"),
        ("gfx/interface/icons/traits.dds", None),
        ("common/scripted_effects/00_effects.txt", "script"),
    ]
    
    print("File Routing Table Test:")
    print("-" * 80)
    for relpath, expected_type in test_cases:
        envelope = get_processing_envelope(relpath)
        actual_type = envelope.file_type if envelope else None
        status = "OK" if actual_type == expected_type else "FAIL"
        print(f"{status} {relpath}")
        print(f"  Expected: {expected_type}, Got: {actual_type}")
        if envelope:
            print(f"  Stages: {envelope.stages}")
        print()
