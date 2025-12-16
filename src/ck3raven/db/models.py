"""
Data Models for ck3raven Database

Dataclasses representing database entities with helper methods.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
import json


@dataclass
class VanillaVersion:
    """A specific CK3 base game state (immutable once stored)."""
    vanilla_version_id: Optional[int] = None
    ck3_version: str = ""
    dlc_set: List[str] = field(default_factory=list)
    build_hash: Optional[str] = None
    ingested_at: Optional[datetime] = None
    notes: Optional[str] = None
    
    @property
    def dlc_set_json(self) -> str:
        return json.dumps(self.dlc_set)
    
    @classmethod
    def from_row(cls, row) -> "VanillaVersion":
        return cls(
            vanilla_version_id=row['vanilla_version_id'],
            ck3_version=row['ck3_version'],
            dlc_set=json.loads(row['dlc_set_json']) if row['dlc_set_json'] else [],
            build_hash=row['build_hash'],
            ingested_at=row['ingested_at'],
            notes=row['notes'],
        )
    
    def __repr__(self):
        return f"VanillaVersion({self.ck3_version}, {len(self.dlc_set)} DLCs)"


@dataclass
class ModPackage:
    """A mod identity (e.g., Steam Workshop ID) that can have many versions."""
    mod_package_id: Optional[int] = None
    workshop_id: Optional[str] = None
    name: str = ""
    source_path: Optional[str] = None
    source_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_row(cls, row) -> "ModPackage":
        return cls(
            mod_package_id=row['mod_package_id'],
            workshop_id=row['workshop_id'],
            name=row['name'],
            source_path=row['source_path'],
            source_url=row['source_url'],
            notes=row['notes'],
            created_at=row['created_at'],
        )
    
    def __repr__(self):
        return f"ModPackage({self.name}, workshop={self.workshop_id})"


@dataclass
class ContentVersion:
    """A specific version of vanilla or a mod package."""
    content_version_id: Optional[int] = None
    kind: str = "mod"  # 'vanilla' or 'mod'
    vanilla_version_id: Optional[int] = None
    mod_package_id: Optional[int] = None
    content_root_hash: str = ""
    file_count: int = 0
    total_size: int = 0
    ingested_at: Optional[datetime] = None
    
    @classmethod
    def from_row(cls, row) -> "ContentVersion":
        return cls(
            content_version_id=row['content_version_id'],
            kind=row['kind'],
            vanilla_version_id=row['vanilla_version_id'],
            mod_package_id=row['mod_package_id'],
            content_root_hash=row['content_root_hash'],
            file_count=row['file_count'],
            total_size=row['total_size'],
            ingested_at=row['ingested_at'],
        )
    
    def __repr__(self):
        return f"ContentVersion({self.kind}, hash={self.content_root_hash[:12]}...)"


@dataclass
class FileContent:
    """Deduplicated file content stored by SHA256 hash."""
    content_hash: str = ""
    content_blob: bytes = b""
    content_text: Optional[str] = None
    size: int = 0
    encoding_guess: Optional[str] = None
    is_binary: bool = False
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_row(cls, row) -> "FileContent":
        return cls(
            content_hash=row['content_hash'],
            content_blob=row['content_blob'],
            content_text=row['content_text'],
            size=row['size'],
            encoding_guess=row['encoding_guess'],
            is_binary=bool(row['is_binary']),
            created_at=row['created_at'],
        )


@dataclass
class FileRecord:
    """A file in a specific content version."""
    file_id: Optional[int] = None
    content_version_id: int = 0
    relpath: str = ""
    content_hash: str = ""
    file_type: Optional[str] = None
    mtime: Optional[str] = None
    deleted: bool = False
    
    @classmethod
    def from_row(cls, row) -> "FileRecord":
        return cls(
            file_id=row['file_id'],
            content_version_id=row['content_version_id'],
            relpath=row['relpath'],
            content_hash=row['content_hash'],
            file_type=row['file_type'],
            mtime=row['mtime'],
            deleted=bool(row['deleted']),
        )
    
    def __repr__(self):
        return f"FileRecord({self.relpath})"


@dataclass
class ParserVersion:
    """Parser version for cache invalidation."""
    parser_version_id: Optional[int] = None
    version_string: str = ""
    git_commit: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    
    @classmethod
    def from_row(cls, row) -> "ParserVersion":
        return cls(
            parser_version_id=row['parser_version_id'],
            version_string=row['version_string'],
            git_commit=row['git_commit'],
            description=row['description'],
            created_at=row['created_at'],
        )
    
    def __repr__(self):
        return f"ParserVersion({self.version_string})"


@dataclass
class ASTRecord:
    """Parsed AST for a file, keyed by (content_hash, parser_version)."""
    ast_id: Optional[int] = None
    content_hash: str = ""
    parser_version_id: int = 0
    ast_blob: bytes = b""
    ast_format: str = "json"
    parse_ok: bool = True
    node_count: Optional[int] = None
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)
    created_at: Optional[datetime] = None
    
    @property
    def diagnostics_json(self) -> str:
        return json.dumps(self.diagnostics)
    
    @classmethod
    def from_row(cls, row) -> "ASTRecord":
        return cls(
            ast_id=row['ast_id'],
            content_hash=row['content_hash'],
            parser_version_id=row['parser_version_id'],
            ast_blob=row['ast_blob'],
            ast_format=row['ast_format'],
            parse_ok=bool(row['parse_ok']),
            node_count=row['node_count'],
            diagnostics=json.loads(row['diagnostics_json']) if row['diagnostics_json'] else [],
            created_at=row['created_at'],
        )
    
    def __repr__(self):
        status = "OK" if self.parse_ok else "FAILED"
        return f"ASTRecord({self.content_hash[:12]}..., {status})"


@dataclass
class Symbol:
    """A symbol definition (something that defines a name/ID/key)."""
    symbol_id: Optional[int] = None
    symbol_type: str = ""  # 'tradition', 'event', 'decision', etc.
    name: str = ""
    scope: Optional[str] = None
    defining_ast_id: Optional[int] = None
    defining_file_id: int = 0
    content_version_id: int = 0
    ast_node_path: Optional[str] = None
    line_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def metadata_json(self) -> str:
        return json.dumps(self.metadata)
    
    @classmethod
    def from_row(cls, row) -> "Symbol":
        return cls(
            symbol_id=row['symbol_id'],
            symbol_type=row['symbol_type'],
            name=row['name'],
            scope=row['scope'],
            defining_ast_id=row['defining_ast_id'],
            defining_file_id=row['defining_file_id'],
            content_version_id=row['content_version_id'],
            ast_node_path=row['ast_node_path'],
            line_number=row['line_number'],
            metadata=json.loads(row['metadata_json']) if row['metadata_json'] else {},
        )
    
    def __repr__(self):
        return f"Symbol({self.symbol_type}:{self.name})"


@dataclass
class Reference:
    """A reference to a symbol (something that uses a name)."""
    ref_id: Optional[int] = None
    ref_type: str = ""  # 'tradition_ref', 'event_ref', etc.
    name: str = ""
    using_ast_id: Optional[int] = None
    using_file_id: int = 0
    content_version_id: int = 0
    ast_node_path: Optional[str] = None
    line_number: Optional[int] = None
    context: Optional[str] = None
    resolution_status: str = "unknown"  # 'resolved', 'unresolved', 'dynamic', 'unknown'
    resolved_symbol_id: Optional[int] = None
    candidates: List[int] = field(default_factory=list)
    
    @property
    def candidates_json(self) -> str:
        return json.dumps(self.candidates) if self.candidates else None
    
    @classmethod
    def from_row(cls, row) -> "Reference":
        return cls(
            ref_id=row['ref_id'],
            ref_type=row['ref_type'],
            name=row['name'],
            using_ast_id=row['using_ast_id'],
            using_file_id=row['using_file_id'],
            content_version_id=row['content_version_id'],
            ast_node_path=row['ast_node_path'],
            line_number=row['line_number'],
            context=row['context'],
            resolution_status=row['resolution_status'],
            resolved_symbol_id=row['resolved_symbol_id'],
            candidates=json.loads(row['candidates_json']) if row['candidates_json'] else [],
        )
    
    def __repr__(self):
        return f"Reference({self.ref_type}:{self.name}, {self.resolution_status})"


@dataclass
class Playset:
    """A user-defined mod collection with load order."""
    playset_id: Optional[int] = None
    name: str = ""
    vanilla_version_id: int = 0
    description: Optional[str] = None
    is_active: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    # Populated separately
    mods: List["PlaysetMod"] = field(default_factory=list)
    
    @classmethod
    def from_row(cls, row) -> "Playset":
        return cls(
            playset_id=row['playset_id'],
            name=row['name'],
            vanilla_version_id=row['vanilla_version_id'],
            description=row['description'],
            is_active=bool(row['is_active']),
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
    
    def __repr__(self):
        active = " [ACTIVE]" if self.is_active else ""
        return f"Playset({self.name}, {len(self.mods)} mods{active})"


@dataclass
class PlaysetMod:
    """A mod in a playset with load order."""
    playset_id: int = 0
    content_version_id: int = 0
    load_order_index: int = 0
    enabled: bool = True
    
    @classmethod
    def from_row(cls, row) -> "PlaysetMod":
        return cls(
            playset_id=row['playset_id'],
            content_version_id=row['content_version_id'],
            load_order_index=row['load_order_index'],
            enabled=bool(row['enabled']),
        )


@dataclass
class Snapshot:
    """A frozen, immutable package capturing state at a point in time."""
    snapshot_id: Optional[int] = None
    name: str = ""
    description: Optional[str] = None
    vanilla_version_id: int = 0
    playset_id: Optional[int] = None
    parser_version_id: Optional[int] = None
    ruleset_version: Optional[str] = None
    include_ast: bool = True
    include_refs: bool = True
    created_at: Optional[datetime] = None
    
    # Populated separately
    members: List[int] = field(default_factory=list)  # content_version_ids
    
    @classmethod
    def from_row(cls, row) -> "Snapshot":
        return cls(
            snapshot_id=row['snapshot_id'],
            name=row['name'],
            description=row['description'],
            vanilla_version_id=row['vanilla_version_id'],
            playset_id=row['playset_id'],
            parser_version_id=row['parser_version_id'],
            ruleset_version=row['ruleset_version'],
            include_ast=bool(row['include_ast']),
            include_refs=bool(row['include_refs']),
            created_at=row['created_at'],
        )
    
    def __repr__(self):
        return f"Snapshot({self.name}, {len(self.members)} versions)"


@dataclass
class ExemplarMod:
    """A curated exemplar mod for linter-by-example."""
    exemplar_id: Optional[int] = None
    mod_package_id: int = 0
    pinned_content_version_id: Optional[int] = None
    reason_tags: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    
    @property
    def reason_tags_json(self) -> str:
        return json.dumps(self.reason_tags)
    
    @property
    def topics_json(self) -> str:
        return json.dumps(self.topics)
    
    @classmethod
    def from_row(cls, row) -> "ExemplarMod":
        return cls(
            exemplar_id=row['exemplar_id'],
            mod_package_id=row['mod_package_id'],
            pinned_content_version_id=row['pinned_content_version_id'],
            reason_tags=json.loads(row['reason_tags_json']) if row['reason_tags_json'] else [],
            topics=json.loads(row['topics_json']) if row['topics_json'] else [],
            notes=row['notes'],
            created_at=row['created_at'],
        )
    
    def __repr__(self):
        return f"ExemplarMod({self.mod_package_id}, topics={self.topics})"
