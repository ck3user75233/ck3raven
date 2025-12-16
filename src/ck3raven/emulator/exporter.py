"""
Game State Exporter

Exports resolved game state to files with provenance annotations.

Outputs:
1. Resolved content files with source comments
2. Conflict reports (JSON, CSV, Markdown)
3. Provenance manifests
"""

import sqlite3
import json
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

from ..tools.format import PDXFormatter, FormatOptions
from .state import GameState, FolderState, ResolvedDefinition, ConflictRecord


@dataclass
class ExportOptions:
    """Options for export."""
    output_dir: Path = None
    include_provenance: bool = True      # Add comments showing source mod
    include_overridden: bool = True      # List overridden mods in comments
    separate_files: bool = False         # One file per definition (vs combined)
    format_output: bool = True           # Pretty-print the output
    generate_report: bool = True         # Generate conflict report
    report_format: str = "markdown"      # 'markdown', 'json', 'csv', or 'all'


class GameStateExporter:
    """Export resolved game state."""
    
    def __init__(self, game_state: GameState, options: ExportOptions = None):
        self.state = game_state
        self.options = options or ExportOptions()
        if self.options.output_dir is None:
            self.options.output_dir = Path("./resolved_output")
        self.formatter = PDXFormatter() if self.options.format_output else None
    
    def export_all(self, folders: List[str] = None) -> None:
        """Export all folders."""
        if folders is None:
            folders = list(self.state.folders.keys())
        
        self.options.output_dir.mkdir(parents=True, exist_ok=True)
        
        for folder in folders:
            if folder in self.state.folders:
                self.export_folder(folder)
        
        if self.options.generate_report:
            self.export_conflict_report()
    
    def export_folder(self, folder: str) -> Path:
        """Export a single folder to resolved file(s)."""
        folder_state = self.state.get_folder(folder)
        if not folder_state:
            raise ValueError(f"No state for {folder}")
        
        out_dir = self.options.output_dir / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        
        if self.options.separate_files:
            # One file per definition
            for key, defn in folder_state.definitions.items():
                file_path = out_dir / f"{key}.txt"
                self._write_definition(file_path, defn, folder_state)
            return out_dir
        else:
            # Combined file
            folder_name = folder.replace("/", "_")
            file_path = out_dir / f"00_resolved_{folder_name}.txt"
            self._write_combined(file_path, folder_state)
            return file_path
    
    def _write_definition(self, path: Path, defn: ResolvedDefinition, 
                          folder_state: FolderState) -> None:
        """Write a single definition to file."""
        lines = []
        
        if self.options.include_provenance:
            lines.extend(self._make_provenance_header(defn, folder_state))
        
        # Serialize AST dict back to PDX format
        lines.append(self._ast_to_pdx(defn.key, defn.ast_dict))
        lines.append("")
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def _write_combined(self, path: Path, folder_state: FolderState) -> None:
        """Write all definitions to a single file."""
        lines = []
        
        # File header
        lines.append(f"# Resolved {folder_state.folder}")
        lines.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"# Playset: {self.state.playset_name}")
        lines.append(f"# Definitions: {folder_state.definition_count}")
        lines.append(f"# Conflicts: {folder_state.conflict_count}")
        lines.append("")
        
        for key, defn in folder_state.definitions.items():
            if self.options.include_provenance:
                lines.extend(self._make_provenance_header(defn, folder_state))
            
            lines.append(self._ast_to_pdx(key, defn.ast_dict))
            lines.append("")
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    
    def _make_provenance_header(self, defn: ResolvedDefinition,
                                 folder_state: FolderState) -> List[str]:
        """Create provenance comment header."""
        lines = []
        lines.append(f"# Source: {defn.source.source_name}")
        lines.append(f"# File: {defn.source.relpath}")
        
        if self.options.include_overridden:
            # Find conflicts for this key
            for conflict in folder_state.conflicts:
                if conflict.key == defn.key:
                    if conflict.losers:
                        loser_names = [l.source_name for l in conflict.losers]
                        lines.append(f"# Overrides: {', '.join(loser_names)}")
                    break
        
        return lines
    
    def _ast_to_pdx(self, key: str, ast_dict: Dict[str, Any]) -> str:
        """Convert AST dict back to PDX script format."""
        # Simple serialization - can be enhanced with formatter
        return self._serialize_node(ast_dict, 0)
    
    def _serialize_node(self, node: Dict[str, Any], indent: int) -> str:
        """Serialize an AST node dict to PDX string."""
        ind = "\t" * indent
        node_type = node.get("_type", "")
        
        if node_type == "block":
            name = node.get("name", "")
            op = node.get("operator", "=")
            children = node.get("children", [])
            
            lines = [f"{ind}{name} {op} {{"]
            for child in children:
                lines.append(self._serialize_node(child, indent + 1))
            lines.append(f"{ind}}}")
            return "\n".join(lines)
        
        elif node_type == "assignment":
            key = node.get("key", "")
            value = node.get("value", {})
            op = node.get("operator", "=")
            
            if isinstance(value, dict):
                if value.get("_type") == "block":
                    value_str = self._serialize_node(value, indent).lstrip()
                    return f"{ind}{key} {op} {value_str}"
                elif value.get("_type") == "value":
                    val = value.get("value", "")
                    return f"{ind}{key} {op} {val}"
            return f"{ind}{key} {op} {value}"
        
        elif node_type == "value":
            return f"{ind}{node.get('value', '')}"
        
        return f"{ind}# Unknown node type: {node_type}"
    
    def export_conflict_report(self) -> Path:
        """Export conflict report in configured format(s)."""
        conflicts = self.state.get_all_conflicts()
        
        if self.options.report_format == "all":
            formats = ["markdown", "json", "csv"]
        else:
            formats = [self.options.report_format]
        
        paths = []
        for fmt in formats:
            if fmt == "markdown":
                path = self._export_markdown_report(conflicts)
            elif fmt == "json":
                path = self._export_json_report(conflicts)
            elif fmt == "csv":
                path = self._export_csv_report(conflicts)
            else:
                continue
            paths.append(path)
        
        return paths[0] if paths else None
    
    def _export_markdown_report(self, conflicts: List[ConflictRecord]) -> Path:
        """Export markdown conflict report."""
        path = self.options.output_dir / "conflict_report.md"
        
        lines = []
        lines.append("# Conflict Report")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"Playset: {self.state.playset_name}")
        lines.append("")
        lines.append("## Summary")
        lines.append(f"- Total conflicts: {len(conflicts)}")
        lines.append(f"- Folders: {len(self.state.folders)}")
        lines.append(f"- Total definitions: {self.state.total_definitions}")
        lines.append("")
        
        # Group by folder
        by_folder = {}
        for c in conflicts:
            by_folder.setdefault(c.folder, []).append(c)
        
        for folder in sorted(by_folder.keys()):
            folder_conflicts = by_folder[folder]
            lines.append(f"## {folder} ({len(folder_conflicts)} conflicts)")
            lines.append("")
            
            for c in folder_conflicts:
                loser_names = ", ".join(l.source_name for l in c.losers)
                lines.append(f"- **{c.key}**")
                lines.append(f"  - Winner: {c.winner.source_name}")
                lines.append(f"  - Overrides: {loser_names}")
            lines.append("")
        
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return path
    
    def _export_json_report(self, conflicts: List[ConflictRecord]) -> Path:
        """Export JSON conflict report."""
        path = self.options.output_dir / "conflict_report.json"
        
        data = {
            "playset": self.state.playset_name,
            "generated": datetime.now().isoformat(),
            "total_conflicts": len(conflicts),
            "conflicts": [
                {
                    "key": c.key,
                    "folder": c.folder,
                    "policy": c.policy.name,
                    "winner": {
                        "source": c.winner.source_name,
                        "file": c.winner.relpath,
                        "line": c.winner.line
                    },
                    "losers": [
                        {"source": l.source_name, "file": l.relpath, "line": l.line}
                        for l in c.losers
                    ]
                }
                for c in conflicts
            ]
        }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return path
    
    def _export_csv_report(self, conflicts: List[ConflictRecord]) -> Path:
        """Export CSV conflict report."""
        path = self.options.output_dir / "conflict_report.csv"
        
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "key", "folder", "policy", "winner_source", "winner_file",
                "loser_count", "loser_sources"
            ])
            
            for c in conflicts:
                loser_sources = "; ".join(l.source_name for l in c.losers)
                writer.writerow([
                    c.key, c.folder, c.policy.name,
                    c.winner.source_name, c.winner.relpath,
                    len(c.losers), loser_sources
                ])
        
        return path
    
    def export_provenance_manifest(self) -> Path:
        """Export a manifest of all definitions with their sources."""
        path = self.options.output_dir / "provenance_manifest.json"
        
        manifest = {
            "playset": self.state.playset_name,
            "generated": datetime.now().isoformat(),
            "folders": {}
        }
        
        for folder, folder_state in self.state.folders.items():
            manifest["folders"][folder] = {
                "policy": folder_state.policy.name,
                "definitions": {
                    key: {
                        "source": defn.source.source_name,
                        "file": defn.source.relpath,
                        "line": defn.source.line
                    }
                    for key, defn in folder_state.definitions.items()
                }
            }
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        return path
