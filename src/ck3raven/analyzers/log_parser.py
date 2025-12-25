"""
CK3 Multi-Log Parser

Extends the error parser to handle all CK3 log files:
- error.log: Errors only (already handled by error_parser.py)
- game.log: Runtime errors and warnings during game startup and play
- debug.log: Debug info, system info, mod loading, DLC info

This module provides unified parsing for all log types with
categorization specific to each log's purpose.
"""

import re
import json
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any, Iterator
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Log entry severity levels."""
    DEBUG = "D"      # [D] - Debug information
    INFO = "I"       # [I] - Informational
    WARNING = "W"    # [W] - Warning
    ERROR = "E"      # [E] - Error


class LogType(Enum):
    """Type of log file."""
    ERROR = "error.log"
    GAME = "game.log"
    DEBUG = "debug.log"


@dataclass
class LogEntry:
    """Represents a single log entry from any CK3 log file."""
    timestamp: str
    level: LogLevel
    source_file: str  # C++ source like jomini_script_system.cpp:303
    line_number: Optional[int]
    message: str
    log_type: LogType
    
    # Parsed metadata
    file_path: Optional[str] = None  # Game file path where issue occurred
    game_line: Optional[int] = None  # Line number in game file
    mod_id: Optional[str] = None
    mod_name: Optional[str] = None
    category: str = "unknown"
    subcategory: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['level'] = self.level.value
        d['log_type'] = self.log_type.value
        return d


@dataclass
class DebugInfo:
    """Extracted debug information from debug.log."""
    architecture: Optional[str] = None
    gpu_adapter: Optional[str] = None
    gpu_memory_mb: Optional[float] = None
    worker_threads: Optional[int] = None
    dlcs_enabled: List[str] = field(default_factory=list)
    mods_enabled: List[str] = field(default_factory=list)
    mods_disabled: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Game.log specific categories
GAME_LOG_CATEGORIES = [
    # High priority - actual script/data errors
    ("casus_belli_error", r"casus_belli\.cpp", 2, "Casus belli definition errors"),
    ("decision_error", r"decision_type\.cpp", 3, "Decision configuration errors"),
    ("triggered_string_error", r"triggered_string\.cpp", 3, "Triggered string reference errors"),
    ("mtth_error", r"mtthimpl\.cpp", 2, "MTTH calculation errors"),
    ("landed_title_error", r"landed_title_template\.cpp", 3, "Landed title definition errors"),
    ("coat_of_arms_error", r"coat_of_arms", 4, "Coat of Arms errors"),
    ("culture_error", r"culture_template\.cpp|culture_name_equivalency\.cpp", 3, "Culture definition errors"),
    ("religion_error", r"religion_templates\.cpp", 3, "Religion/faith errors"),
    ("holy_site_error", r"faith_holy_site_template\.cpp", 3, "Holy site configuration errors"),
    ("bookmark_error", r"bookmark\.cpp", 4, "Bookmark/character selection errors"),
    ("building_error", r"building_type\.cpp", 4, "Building/gfx culture flag errors"),
    ("flavorization_error", r"flavorizing\.cpp", 4, "Flavorization/title naming errors"),
    
    # Lower priority - usually cosmetic
    ("portrait_error", r"portrait", 5, "Portrait/appearance errors"),
    ("gui_error", r"pdx_gui|widget", 5, "GUI/interface errors"),
]

# Debug.log specific categories
DEBUG_LOG_CATEGORIES = [
    ("system_init", r"Log system initialized|Architecture|worker threads", 5, "System initialization"),
    ("gpu_info", r"Adapter \d+:|Selected adapter:", 5, "GPU/graphics information"),
    ("dlc_info", r"^DLC:", 5, "DLC loading information"),
    ("mod_info", r"^Mod:", 5, "Mod loading information"),
    ("network_info", r"POPS|Matchmaking|Nakama", 5, "Network/online services"),
    ("settings_info", r"settings|pdx_settings", 5, "Settings loading"),
    ("define_warning", r"Define .* not specified", 4, "Missing defines (usually harmless)"),
]


class CK3LogParser:
    """
    Multi-log parser for CK3's log files.
    
    Parses error.log, game.log, and debug.log with appropriate
    categorization for each.
    """
    
    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        mod_map: Optional[Dict[str, Dict]] = None,
    ):
        """
        Initialize the log parser.
        
        Args:
            logs_dir: Path to CK3 logs directory (default: auto-detect)
            mod_map: Optional mapping of Steam ID -> mod info
        """
        self.logs_dir = logs_dir or self._default_logs_dir()
        self.mod_map = mod_map or {}
        
        # Parsed data
        self.entries: Dict[LogType, List[LogEntry]] = {
            LogType.ERROR: [],
            LogType.GAME: [],
            LogType.DEBUG: [],
        }
        self.debug_info: Optional[DebugInfo] = None
        
        # Statistics per log type
        self.stats: Dict[LogType, Dict] = {}
    
    @staticmethod
    def _default_logs_dir() -> Path:
        """Get default CK3 logs directory."""
        return Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "logs"
    
    def parse_log_line(self, line: str, log_type: LogType) -> Optional[LogEntry]:
        """
        Parse a single log line into a LogEntry object.
        
        Handles format: [HH:MM:SS][LEVEL][source.cpp:LINE]: message
        """
        # Match log format: [timestamp][level][source]: message
        # Level can be D, I, W, E
        match = re.match(r'\[([^\]]+)\]\[([DIWE])\]\[([^\]]+)\]:\s*(.*)', line)
        if not match:
            return None
        
        timestamp, level_str, source_file, message = match.groups()
        
        # Parse level
        try:
            level = LogLevel(level_str)
        except ValueError:
            level = LogLevel.DEBUG
        
        # Extract line number from source file if present
        line_num_match = re.search(r':(\d+)$', source_file)
        line_number = int(line_num_match.group(1)) if line_num_match else None
        
        entry = LogEntry(
            timestamp=timestamp,
            level=level,
            source_file=source_file,
            line_number=line_number,
            message=message,
            log_type=log_type,
        )
        
        # Extract file path and game line from message
        self._extract_file_info(entry)
        
        # Categorize based on log type
        self._categorize_entry(entry)
        
        # Extract mod info
        entry.mod_id, entry.mod_name = self._extract_mod_from_path(entry.file_path or entry.message)
        
        return entry
    
    def _extract_file_info(self, entry: LogEntry):
        """Extract game file path and line number from message."""
        message = entry.message
        
        # Pattern 1: "file: path/to/file.txt line: 123"
        file_match = re.search(r'file:\s*([^\s]+(?:\s+[^\s]+)*?)\s+line:\s*(\d+)', message)
        if file_match:
            entry.file_path = file_match.group(1).strip()
            entry.game_line = int(file_match.group(2))
            return
        
        # Pattern 2: 'path/to/file.yml' or "path/to/file.txt"
        file_match = re.search(r"['\"]([^'\"]*\.(yml|txt|gui|gfx|mod))['\"]", message)
        if file_match:
            entry.file_path = file_match.group(1)
            return
        
        # Pattern 3: at common/xxx/file.txt line : 123 (note space before colon)
        file_match = re.search(r'at\s*([^\s]+\.txt)\s+line\s*:\s*(\d+)', message)
        if file_match:
            entry.file_path = file_match.group(1)
            entry.game_line = int(file_match.group(2))
            return
        
        # Pattern 4: in path/to/file.txt line : 123
        file_match = re.search(r'in\s+([^\s]+\.txt)\s+line\s*:\s*(\d+)', message)
        if file_match:
            entry.file_path = file_match.group(1)
            entry.game_line = int(file_match.group(2))
            return
    
    def _categorize_entry(self, entry: LogEntry):
        """Categorize a log entry based on its source and message."""
        categories = (
            GAME_LOG_CATEGORIES if entry.log_type == LogType.GAME
            else DEBUG_LOG_CATEGORIES if entry.log_type == LogType.DEBUG
            else []  # error.log uses error_parser.py categories
        )
        
        for name, pattern, priority, description in categories:
            if re.search(pattern, entry.source_file, re.IGNORECASE) or \
               re.search(pattern, entry.message, re.IGNORECASE):
                entry.category = name
                entry.subcategory = description
                return
        
        entry.category = "other"
    
    def _extract_mod_from_path(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract mod Steam ID and name from text."""
        if not text:
            return None, None
        
        # Try to extract Steam workshop ID
        ugc_match = re.search(r'ugc_(\d+)', text)
        if ugc_match:
            steam_id = ugc_match.group(1)
            mod_info = self.mod_map.get(steam_id)
            if mod_info:
                return steam_id, mod_info.get('name', f"Mod {steam_id}")
            return steam_id, f"Mod {steam_id}"
        
        return None, None
    
    def parse_game_log(self, log_path: Optional[Path] = None) -> int:
        """
        Parse the game.log file.
        
        Args:
            log_path: Path to game.log (default: logs_dir/game.log)
        
        Returns:
            Number of entries parsed (errors only by default)
        """
        log_path = log_path or (self.logs_dir / "game.log")
        
        self.entries[LogType.GAME] = []
        
        if not log_path.exists():
            return 0
        
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                # game.log primarily has [E] entries we care about
                if '[E]' not in line:
                    continue
                
                entry = self.parse_log_line(line, LogType.GAME)
                if entry:
                    self.entries[LogType.GAME].append(entry)
        
        self._update_stats(LogType.GAME)
        return len(self.entries[LogType.GAME])
    
    def parse_debug_log(
        self,
        log_path: Optional[Path] = None,
        extract_system_info: bool = True,
        include_all_levels: bool = False,
    ) -> int:
        """
        Parse the debug.log file.
        
        Args:
            log_path: Path to debug.log (default: logs_dir/debug.log)
            extract_system_info: Whether to extract system/DLC/mod info
            include_all_levels: If True, include [D] and [I] entries (very verbose)
        
        Returns:
            Number of entries parsed
        """
        log_path = log_path or (self.logs_dir / "debug.log")
        
        self.entries[LogType.DEBUG] = []
        self.debug_info = DebugInfo() if extract_system_info else None
        
        if not log_path.exists():
            return 0
        
        in_dlc_block = False
        in_mod_block = False
        
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    in_dlc_block = False
                    in_mod_block = False
                    continue
                
                # Extract system info from debug entries
                if extract_system_info and self.debug_info:
                    self._extract_debug_info(line)
                    
                    # Track DLC/Mod blocks
                    if "DLC:" in line:
                        in_dlc_block = True
                        in_mod_block = False
                        continue
                    elif "Mod:" in line:
                        in_mod_block = True
                        in_dlc_block = False
                        continue
                    
                    if in_dlc_block and "|" in line:
                        # Format: Name|path|
                        parts = line.split("|")
                        if parts:
                            self.debug_info.dlcs_enabled.append(parts[0])
                        continue
                    
                    if in_mod_block and "|" in line:
                        # Format: Name|path|Enabled/Disabled
                        parts = line.split("|")
                        if len(parts) >= 3:
                            mod_name = parts[0]
                            status = parts[2].strip()
                            if status == "Enabled":
                                self.debug_info.mods_enabled.append(mod_name)
                            else:
                                self.debug_info.mods_disabled.append(mod_name)
                        continue
                
                # Only parse actual log entries with level markers
                if not re.match(r'\[[^\]]+\]\[[DIWE]\]', line):
                    continue
                
                # Filter by level unless include_all_levels
                if not include_all_levels and '[E]' not in line:
                    continue
                
                entry = self.parse_log_line(line, LogType.DEBUG)
                if entry:
                    self.entries[LogType.DEBUG].append(entry)
        
        self._update_stats(LogType.DEBUG)
        return len(self.entries[LogType.DEBUG])
    
    def _extract_debug_info(self, line: str):
        """Extract system information from debug.log lines."""
        if not self.debug_info:
            return
        
        # Architecture
        if "Architecture:" in line:
            match = re.search(r'Architecture:\s*(\S+)', line)
            if match:
                self.debug_info.architecture = match.group(1)
        
        # GPU
        if "Selected adapter:" in line:
            match = re.search(r'Selected adapter:\s*(.+?)\s*\(([\d.]+)\s*MB\)', line)
            if match:
                self.debug_info.gpu_adapter = match.group(1)
                self.debug_info.gpu_memory_mb = float(match.group(2))
        
        # Worker threads
        if "worker threads" in line:
            match = re.search(r'Spawning\s*(\d+)\s*worker threads', line)
            if match:
                self.debug_info.worker_threads = int(match.group(1))
    
    def _update_stats(self, log_type: LogType):
        """Update statistics for a log type."""
        entries = self.entries[log_type]
        
        self.stats[log_type] = {
            'total': len(entries),
            'by_level': Counter(e.level.value for e in entries),
            'by_category': Counter(e.category for e in entries),
            'by_source': Counter(e.source_file for e in entries),
            'by_mod': Counter(e.mod_name for e in entries if e.mod_name),
        }
    
    def get_game_log_summary(self) -> Dict[str, Any]:
        """Get summary of game.log errors."""
        if LogType.GAME not in self.stats:
            return {"error": "game.log not parsed yet"}
        
        stats = self.stats[LogType.GAME]
        return {
            "total_errors": stats['total'],
            "by_category": dict(stats['by_category'].most_common(15)),
            "by_source_file": dict(stats['by_source'].most_common(10)),
            "by_mod": dict(stats['by_mod'].most_common(10)),
        }
    
    def get_debug_info_summary(self) -> Dict[str, Any]:
        """Get extracted debug/system information."""
        if not self.debug_info:
            return {"error": "debug.log not parsed with extract_system_info=True"}
        
        return {
            "system": {
                "architecture": self.debug_info.architecture,
                "gpu": self.debug_info.gpu_adapter,
                "gpu_memory_mb": self.debug_info.gpu_memory_mb,
                "worker_threads": self.debug_info.worker_threads,
            },
            "dlcs_enabled": len(self.debug_info.dlcs_enabled),
            "dlc_list": self.debug_info.dlcs_enabled,
            "mods_enabled": len(self.debug_info.mods_enabled),
            "mods_enabled_list": self.debug_info.mods_enabled,
            "mods_disabled": len(self.debug_info.mods_disabled),
        }
    
    def get_entries(
        self,
        log_type: LogType,
        category: Optional[str] = None,
        level: Optional[LogLevel] = None,
        mod_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[LogEntry]:
        """
        Get filtered list of log entries.
        
        Args:
            log_type: Which log to query
            category: Filter by category
            level: Filter by log level
            mod_filter: Filter by mod name (partial match)
            limit: Maximum results
        
        Returns:
            List of matching entries
        """
        results = self.entries.get(log_type, [])
        
        if category:
            results = [e for e in results if e.category == category]
        
        if level:
            results = [e for e in results if e.level == level]
        
        if mod_filter:
            mod_lower = mod_filter.lower()
            results = [e for e in results if e.mod_name and mod_lower in e.mod_name.lower()]
        
        return results[:limit]
    
    def search_entries(
        self,
        query: str,
        log_type: Optional[LogType] = None,
        limit: int = 50,
    ) -> List[LogEntry]:
        """
        Search log entries by message or file path.
        
        Args:
            query: Search query (case-insensitive)
            log_type: Limit to specific log type (None = all)
            limit: Maximum results
        
        Returns:
            List of matching entries
        """
        query_lower = query.lower()
        results = []
        
        log_types = [log_type] if log_type else list(LogType)
        
        for lt in log_types:
            for entry in self.entries.get(lt, []):
                if query_lower in entry.message.lower():
                    results.append(entry)
                elif entry.file_path and query_lower in entry.file_path.lower():
                    results.append(entry)
                
                if len(results) >= limit:
                    return results
        
        return results
    
    def read_log_file(
        self,
        log_type: LogType,
        start_line: int = 1,
        end_line: Optional[int] = None,
        max_lines: int = 500,
    ) -> Dict[str, Any]:
        """
        Read raw content from a log file.
        
        Args:
            log_type: Which log file to read
            start_line: Line to start from (1-indexed)
            end_line: Line to end at (None = start + max_lines)
            max_lines: Maximum lines to read
        
        Returns:
            Dict with content, line count, etc.
        """
        log_path = self.logs_dir / log_type.value
        
        if not log_path.exists():
            return {"error": f"Log file not found: {log_path}"}
        
        lines = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                total_lines = i
                if i < start_line:
                    continue
                if end_line and i > end_line:
                    break
                if len(lines) >= max_lines:
                    break
                lines.append(line.rstrip())
        
        return {
            "log_type": log_type.value,
            "path": str(log_path),
            "start_line": start_line,
            "lines_read": len(lines),
            "total_lines": total_lines,
            "content": "\n".join(lines),
        }


# Convenience functions

def parse_all_logs(logs_dir: Optional[Path] = None) -> CK3LogParser:
    """
    Parse all CK3 log files.
    
    Returns:
        Configured CK3LogParser with all logs parsed
    """
    parser = CK3LogParser(logs_dir=logs_dir)
    parser.parse_game_log()
    parser.parse_debug_log(extract_system_info=True)
    return parser


def get_game_log_errors(logs_dir: Optional[Path] = None, limit: int = 100) -> List[Dict]:
    """
    Quick access to game.log errors.
    
    Returns:
        List of error entries as dicts
    """
    parser = CK3LogParser(logs_dir=logs_dir)
    parser.parse_game_log()
    return [e.to_dict() for e in parser.entries[LogType.GAME][:limit]]


def get_system_info(logs_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Extract system info from debug.log.
    
    Returns:
        System info dict (GPU, DLCs, mods, etc.)
    """
    parser = CK3LogParser(logs_dir=logs_dir)
    parser.parse_debug_log(extract_system_info=True)
    return parser.get_debug_info_summary()
