# QBuilder Routing Table

> **Version:** 1  
> **Status:** Canonical (machine-validated against routing_table.json)  
> **Last Updated:** January 10, 2026

This document describes the file routing rules for QBuilder-Daemon. The routing table
determines what processing envelope is assigned to each file based on its path and extension.

**The JSON file (`qbuilder/routing_table.json`) is authoritative.** This markdown must match
exactly. Run `qbuilder validate-routing-table` to verify.

---

## Processing Steps

Steps execute in order within an envelope. A file receives exactly one envelope.

| Step | Order | Description |
|------|-------|-------------|
| INGEST | 1 | Read file from disk, compute content hash, store in file_contents table |
| PARSE | 2 | Parse CK3 script content into AST, store in asts table keyed by content_hash |
| SYMBOLS | 3 | Extract symbol definitions from AST, store in symbols table |
| REFS | 4 | Extract symbol references from AST, store in refs table |
| LOCALIZATION | 5 | Parse YML localization, store in localization_entries table |
| LOOKUP_TRAITS | 6 | Build trait_lookups table from parsed traits |
| LOOKUP_EVENTS | 6 | Build event_lookups table from parsed events |
| LOOKUP_DECISIONS | 6 | Build decision_lookups table from parsed decisions |
| LOOKUP_DYNASTIES | 6 | Build dynasty_lookups table from parsed dynasties |
| LOOKUP_CHARACTERS | 6 | Build character_lookups table from parsed characters |
| LOOKUP_TITLES | 6 | Build title_lookups table from parsed titles |
| LOOKUP_PROVINCES | 6 | Build province_lookups table from parsed provinces |
| LOOKUP_HOLY_SITES | 6 | Build holy_site_lookups table from parsed holy sites |

---

## Envelopes

An envelope is a complete set of processing steps for a file type.

| Envelope | Steps | Notes |
|----------|-------|-------|
| SKIP | (none) | File should not be processed (graphics, audio, fonts, etc.) |
| INGEST_ONLY | INGEST | Store file content only, no parsing or extraction |
| SCRIPT_FULL | INGEST -> PARSE -> SYMBOLS -> REFS | Full CK3 script processing: parse AST, extract symbols and references |
| SCRIPT_NO_REFS | INGEST -> PARSE -> SYMBOLS | Parse and extract symbols, but skip ref extraction (large hierarchical files) |
| LOCALIZATION | INGEST -> LOCALIZATION | Parse YML localization files into localization_entries table |
| LOOKUP_TRAITS | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_TRAITS | Full script processing plus trait lookup table extraction |
| LOOKUP_EVENTS | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_EVENTS | Full script processing plus event lookup table extraction |
| LOOKUP_DECISIONS | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_DECISIONS | Full script processing plus decision lookup table extraction |
| LOOKUP_DYNASTIES | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_DYNASTIES | Full script processing plus dynasty lookup table extraction |
| LOOKUP_CHARACTERS | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_CHARACTERS | Full script processing plus character lookup table extraction |
| LOOKUP_TITLES | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_TITLES | Full script processing plus title lookup table extraction |
| LOOKUP_PROVINCES | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_PROVINCES | Full script processing plus province lookup table extraction |
| LOOKUP_HOLY_SITES | INGEST -> PARSE -> SYMBOLS -> REFS -> LOOKUP_HOLY_SITES | Full script processing plus holy site lookup table extraction |

---

## File Type Matching Rules

Rules are evaluated in order. First match wins.

| File Type | Match Rule | Envelope | Notes |
|-----------|------------|----------|-------|
| GRAPHICS | ext: .dds, .png, .jpg, .jpeg, .tga, .psd, .bmp | SKIP | Image files - no processing value |
| AUDIO | ext: .mp3, .wav, .ogg, .wem, .bnk | SKIP | Audio files - no processing value |
| FONTS | ext: .ttf, .otf, .fnt | SKIP | Font files - no processing value |
| VIDEO | ext: .bik, .bk2 | SKIP | Video files - no processing value |
| GFX_FOLDER | paths: gfx/ | SKIP | Graphics folder - skip entirely |
| FONTS_FOLDER | paths: fonts/ | SKIP | Fonts folder - skip entirely |
| MUSIC_FOLDER | paths: music/ | SKIP | Music folder - skip entirely |
| SOUND_FOLDER | paths: sound/ | SKIP | Sound folder - skip entirely |
| DLC_METADATA_FOLDER | paths: dlc_metadata/ | SKIP | DLC metadata - not useful for modding |
| CONTENT_SOURCE_FOLDER | paths: content_source/ | SKIP | Content source - development files |
| LOCALIZATION_YML | paths: localization/, localisation/; ext: .yml, .yaml | LOCALIZATION | Localization files - parse as YML |
| CONFIG_YML | ext: .yml, .yaml | INGEST_ONLY | Non-localization YML files (mod descriptors, etc.) |
| MAP_DATA | paths: map_data/ | INGEST_ONLY | Map data files - binary/specialized format |
| BOOKMARK_PORTRAITS | paths: common/bookmark_portraits/ | INGEST_ONLY | Bookmark portrait data - large structured data |
| GENES | paths: common/genes/ | INGEST_ONLY | Gene definitions - large structured data |
| EVENT_BACKGROUNDS | paths: common/event_backgrounds/ | INGEST_ONLY | Event background definitions |
| LANDED_TITLES | paths: common/landed_titles/ | SCRIPT_NO_REFS | Landed titles - huge AST, skip ref extraction |
| NAME_EQUIVALENCY | paths: common/culture/name_equivalency/ | SCRIPT_NO_REFS | Name equivalency - large data, skip refs |
| TRAITS | paths: common/traits/ | LOOKUP_TRAITS | Trait definitions - full processing + lookup table |
| DECISIONS | paths: common/decisions/ | LOOKUP_DECISIONS | Decision definitions - full processing + lookup table |
| EVENTS | paths: events/ | LOOKUP_EVENTS | Event definitions - full processing + lookup table |
| DYNASTIES | paths: common/dynasties/ | LOOKUP_DYNASTIES | Dynasty definitions - full processing + lookup table |
| CHARACTERS | paths: common/characters/, history/characters/ | LOOKUP_CHARACTERS | Character definitions - full processing + lookup table |
| TITLES_HISTORY | paths: history/titles/ | LOOKUP_TITLES | Title history - full processing + lookup table |
| PROVINCES_HISTORY | paths: history/provinces/ | LOOKUP_PROVINCES | Province history - full processing + lookup table |
| HOLY_SITES | paths: common/holy_sites/ | LOOKUP_HOLY_SITES | Holy site definitions - full processing + lookup table |
| SCRIPT_TXT | ext: .txt | SCRIPT_FULL | Default CK3 script file - full processing |
| GUI_FILE | ext: .gui | SCRIPT_FULL | GUI definition file |
| GFX_SCRIPT | ext: .gfx | SCRIPT_FULL | GFX script file (sprite definitions, etc.) |
| SFX_SCRIPT | ext: .sfx | SCRIPT_FULL | SFX script file (sound effect definitions) |
| ASSET_FILE | ext: .asset | SCRIPT_FULL | Asset definition file |
| UNKNOWN | (fallback) | INGEST_ONLY | Fallback for unknown file types - store content only |

---

## Open Routing Questions

No open questions at this time. All file types in the database have been assigned envelopes.

---

## Validation

Run the following to validate this document matches the JSON:

```bash
python -m qbuilder.cli validate-routing-table
```

This checks:
1. All envelopes in JSON are documented in markdown
2. All file types in JSON are documented in markdown  
3. Step orders match
4. Match rules match

---

## Statistics

- **Envelopes:** 13
- **File Types:** 32
- **Steps:** 13
