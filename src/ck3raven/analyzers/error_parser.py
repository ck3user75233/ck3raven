"""
CK3 Error Log Parser

Parses CK3's error.log into structured error data with:
- Error categorization (script, encoding, missing reference, etc.)
- Priority scoring (1=critical to 5=low)
- Cascade detection (root errors that cause many others)
- Mod attribution (which mod caused which error)

Based on the original ck3_error_parser.py tool.
"""

import re
import json
from pathlib import Path
from collections import defaultdict, Counter
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any, Iterator
from datetime import datetime


@dataclass
class CK3Error:
    """Represents a single error from the error log."""
    timestamp: str
    source_file: str  # C++ source like jomini_script_system.cpp:303
    line_number: Optional[int]
    message: str
    file_path: Optional[str] = None  # Game file path where error occurred
    game_line: Optional[int] = None  # Line number in game file
    mod_id: Optional[str] = None
    mod_name: Optional[str] = None
    category: str = "unknown"
    priority: int = 5  # 1=critical, 5=low
    is_cascading_root: bool = False
    is_cascading_child: bool = False
    cascade_group: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ErrorCategory:
    """Defines error categorization rules."""
    name: str
    pattern: str
    priority: int
    description: str
    is_fixable: bool
    fix_hint: str = ""


@dataclass
class CascadePattern:
    """Detected cascading error pattern."""
    root_error: CK3Error
    child_errors: List[CK3Error]
    pattern_type: str
    confidence: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "confidence": self.confidence,
            "root_error": self.root_error.to_dict(),
            "child_count": len(self.child_errors),
            "child_sample": [e.to_dict() for e in self.child_errors[:5]]
        }


# Error categorization rules (priority: 1=critical, 5=low)
ERROR_CATEGORIES = [
    ErrorCategory("fatal_crash", r"fatal\(crash\)", 1, 
                 "Causes game crashes", True,
                 "Fix immediately - game-breaking"),
    
    ErrorCategory("encoding_error", r"(Incorrect MOD descriptor|Invalid supported_version|Illegal localization break)", 2,
                 "File encoding/format issues", True,
                 "Check UTF-8 BOM encoding and file format"),
    
    ErrorCategory("script_system_error", r"jomini_script_system\.cpp", 2,
                 "Script parsing errors - often causes cascades", True,
                 "Check for syntax errors, missing braces, invalid values"),
    
    ErrorCategory("missing_reference", r"(not defined|not found|does not exist|Unknown)", 3,
                 "References to non-existent game objects", True,
                 "Add missing definitions or remove references"),
    
    ErrorCategory("scope_error", r"(scope|context)", 3,
                 "Incorrect scope usage in scripts", True,
                 "Review trigger/effect scope requirements"),
    
    ErrorCategory("event_error", r"(eventmanager|jomini_event_queue_manager)", 3,
                 "Event system errors", True,
                 "Check event definitions and on_actions"),
    
    ErrorCategory("duplicate_key", r"Duplicate (localization key|entry)", 4,
                 "Duplicate definitions", True,
                 "Remove duplicates or use override files"),
    
    ErrorCategory("localization_missing", r"(Key is missing localization|missing localization key)", 4,
                 "Missing localization strings", True,
                 "Add localization entries"),
    
    ErrorCategory("gui_warning", r"(pdx_gui|Widget cannot have)", 4,
                 "GUI/interface issues", False,
                 "Usually non-critical, visual only"),
    
    ErrorCategory("portrait_error", r"portraitcontext", 4,
                 "Portrait/character model issues", False,
                 "Usually non-critical, cosmetic"),
    
    ErrorCategory("audio_error", r"audio2_fmod_sound", 5,
                 "Audio system issues", False,
                 "Non-critical, audio only"),
]


class CK3ErrorParser:
    """Parser for CK3 error logs with cascade detection."""
    
    def __init__(
        self,
        logs_dir: Optional[Path] = None,
        mod_map: Optional[Dict[str, Dict]] = None,
    ):
        """
        Initialize the error parser.
        
        Args:
            logs_dir: Path to CK3 logs directory (default: auto-detect)
            mod_map: Optional mapping of Steam ID -> mod info
        """
        self.logs_dir = logs_dir or self._default_logs_dir()
        self.mod_map = mod_map or {}
        
        self.errors: List[CK3Error] = []
        self.cascade_patterns: List[CascadePattern] = []
        
        # Statistics
        self.stats = {
            'total_errors': 0,
            'by_category': Counter(),
            'by_priority': Counter(),
            'by_mod': Counter(),
            'by_source': Counter(),
            'cascades_detected': 0
        }
    
    @staticmethod
    def _default_logs_dir() -> Path:
        """Get default CK3 logs directory."""
        return Path.home() / "Documents" / "Paradox Interactive" / "Crusader Kings III" / "logs"
    
    def set_mod_map(self, mod_map: Dict[str, Dict]):
        """Set the mod mapping for attribution."""
        self.mod_map = mod_map
    
    def load_mod_map_from_playset(self, playset_json_path: Path):
        """Load mod mapping from a playset JSON file."""
        with open(playset_json_path, 'r', encoding='utf-8') as f:
            playset = json.load(f)
        
        self.mod_map = {}
        for mod in playset.get('mods', []):
            steam_id = mod.get('steamId', '')
            if steam_id:
                self.mod_map[steam_id] = {
                    'name': mod.get('displayName', 'Unknown'),
                    'position': mod.get('position', -1),
                    'enabled': mod.get('enabled', False)
                }
    
    def extract_mod_from_path(self, file_path: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract mod Steam ID and name from file path."""
        if not file_path:
            return None, None
        
        # Try to extract Steam workshop ID from path
        # Format: mod/ugc_STEAMID.mod or localization/english/file.yml
        ugc_match = re.search(r'ugc_(\d+)', file_path)
        if ugc_match:
            steam_id = ugc_match.group(1)
            mod_info = self.mod_map.get(steam_id)
            if mod_info:
                return steam_id, mod_info['name']
            return steam_id, f"Mod {steam_id}"
        
        # Check if file contains mod-specific markers
        for steam_id, mod_info in self.mod_map.items():
            mod_name_slug = re.sub(r'[^a-z0-9]+', '_', mod_info['name'].lower())
            if mod_name_slug in file_path.lower():
                return steam_id, mod_info['name']
        
        return None, None
    
    def categorize_error(self, error: CK3Error):
        """Categorize an error based on its message and source."""
        for category in ERROR_CATEGORIES:
            if re.search(category.pattern, error.message, re.IGNORECASE) or \
               re.search(category.pattern, error.source_file, re.IGNORECASE):
                error.category = category.name
                error.priority = category.priority
                return
        
        error.category = "unknown"
        error.priority = 5
    
    def parse_error_line(self, line: str) -> Optional[CK3Error]:
        """Parse a single error log line into a CK3Error object."""
        # Format: [08:19:09][E][dlc.cpp:1314]: Incorrect MOD descriptor: "mod/RICE-EPE-Compatch.mod"
        match = re.match(r'\[([^\]]+)\]\[E\]\[([^\]]+)\]:\s*(.*)', line)
        if not match:
            return None
        
        timestamp, source_file, message = match.groups()
        
        # Extract line number from source file if present
        line_num_match = re.search(r':(\d+)$', source_file)
        line_number = int(line_num_match.group(1)) if line_num_match else None
        
        # Try to extract file path and game line from message
        file_path = None
        game_line = None
        
        # Pattern 1: "file: path/to/file.txt line: 123"
        file_match = re.search(r'file:\s*([^\s]+(?:\s+[^\s]+)*?)\s+line:\s*(\d+)', message)
        if file_match:
            file_path = file_match.group(1).strip()
            game_line = int(file_match.group(2))
        
        # Pattern 2: 'path/to/file.yml'
        if not file_path:
            file_match = re.search(r"'([^']*\.(yml|txt|gui|gfx|mod))'", message)
            if file_match:
                file_path = file_match.group(1)
        
        # Pattern 3: "path/to/file.txt"
        if not file_path:
            file_match = re.search(r'"([^"]*\.(yml|txt|gui|gfx|mod))"', message)
            if file_match:
                file_path = file_match.group(1)
        
        # Pattern 4: mod/ugc_XXXXX.mod
        if not file_path:
            file_match = re.search(r'(mod/ugc_\d+\.mod)', message)
            if file_match:
                file_path = file_match.group(1)
        
        error = CK3Error(
            timestamp=timestamp,
            source_file=source_file,
            line_number=line_number,
            message=message,
            file_path=file_path,
            game_line=game_line,
        )
        
        # Extract mod information
        error.mod_id, error.mod_name = self.extract_mod_from_path(file_path or message)
        
        # Categorize the error
        self.categorize_error(error)
        
        return error
    
    def parse_log(self, log_path: Optional[Path] = None) -> int:
        """
        Parse the error log file.
        
        Args:
            log_path: Path to error.log (default: logs_dir/error.log)
        
        Returns:
            Number of errors parsed
        """
        log_path = log_path or (self.logs_dir / "error.log")
        
        self.errors = []
        
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or '[E]' not in line:
                    continue
                
                error = self.parse_error_line(line)
                if error:
                    self.errors.append(error)
        
        self._update_statistics()
        return len(self.errors)
    
    def parse_log_content(self, content: str) -> int:
        """
        Parse error log content from a string.
        
        Args:
            content: Error log content as string
        
        Returns:
            Number of errors parsed
        """
        self.errors = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line or '[E]' not in line:
                continue
            
            error = self.parse_error_line(line)
            if error:
                self.errors.append(error)
        
        self._update_statistics()
        return len(self.errors)
    
    def _update_statistics(self):
        """Update error statistics."""
        self.stats = {
            'total_errors': len(self.errors),
            'by_category': Counter(),
            'by_priority': Counter(),
            'by_mod': Counter(),
            'by_source': Counter(),
            'cascades_detected': 0
        }
        
        for error in self.errors:
            self.stats['by_category'][error.category] += 1
            self.stats['by_priority'][error.priority] += 1
            self.stats['by_source'][error.source_file] += 1
            
            if error.mod_name:
                self.stats['by_mod'][error.mod_name] += 1
    
    def detect_cascading_errors(self):
        """
        Detect cascading error patterns where one root error causes many others.
        
        Patterns detected:
        1. Script syntax error -> many "not defined" errors
        2. Encoding error -> parser disruption causing downstream errors
        3. Repeated identical errors (spam)
        """
        self.cascade_patterns = []
        
        # Pattern 1: Script system errors followed by missing reference errors
        script_errors = [e for e in self.errors if e.category == "script_system_error"][:100]
        
        for script_error in script_errors:
            timestamp_base = self._parse_timestamp(script_error.timestamp)
            if not timestamp_base:
                continue
            
            # Find nearby errors (within 100 positions)
            error_idx = self.errors.index(script_error)
            nearby_errors = self.errors[max(0, error_idx-50):min(len(self.errors), error_idx+150)]
            
            potential_children = []
            for other_error in nearby_errors:
                if other_error == script_error:
                    continue
                
                other_timestamp = self._parse_timestamp(other_error.timestamp)
                if not other_timestamp:
                    continue
                
                # Within 5 seconds and same file or related
                time_diff = abs((other_timestamp - timestamp_base).total_seconds())
                if time_diff <= 5:
                    if other_error.category in ["missing_reference", "scope_error", "event_error"]:
                        if not other_error.file_path or other_error.file_path == script_error.file_path:
                            potential_children.append(other_error)
            
            if len(potential_children) >= 3:
                cascade = CascadePattern(
                    root_error=script_error,
                    child_errors=potential_children,
                    pattern_type="script_parse_cascade",
                    confidence=0.8 if len(potential_children) >= 10 else 0.6
                )
                self.cascade_patterns.append(cascade)
                
                script_error.is_cascading_root = True
                script_error.cascade_group = len(self.cascade_patterns)
                
                for child in potential_children:
                    child.is_cascading_child = True
                    child.cascade_group = len(self.cascade_patterns)
        
        # Pattern 2: Encoding errors causing mod-wide issues
        encoding_errors = [e for e in self.errors if e.category == "encoding_error"][:50]
        
        errors_by_mod = defaultdict(list)
        for error in self.errors:
            if error.mod_id:
                errors_by_mod[error.mod_id].append(error)
        
        for encoding_error in encoding_errors:
            if not encoding_error.mod_id:
                continue
            
            same_mod_errors = [
                e for e in errors_by_mod.get(encoding_error.mod_id, [])
                if e != encoding_error
                and self._is_after(e.timestamp, encoding_error.timestamp)
            ]
            
            if len(same_mod_errors) >= 5:
                cascade = CascadePattern(
                    root_error=encoding_error,
                    child_errors=same_mod_errors[:100],
                    pattern_type="mod_load_cascade",
                    confidence=0.9
                )
                self.cascade_patterns.append(cascade)
                
                encoding_error.is_cascading_root = True
                encoding_error.cascade_group = len(self.cascade_patterns)
                
                for child in same_mod_errors[:100]:
                    child.is_cascading_child = True
                    child.cascade_group = len(self.cascade_patterns)
        
        # Pattern 3: Repeated identical errors (spam)
        error_counts = Counter()
        for error in self.errors:
            msg = error.message or ""
            sig = error.source_file + ":" + re.sub(r'\d+', 'N', msg[:100])
            error_counts[sig] += 1
        
        for sig, count in error_counts.items():
            if count >= 10:
                matching_errors = [
                    e for e in self.errors
                    if (e.source_file + ":" + re.sub(r'\d+', 'N', (e.message or "")[:100])) == sig
                ]
                
                if matching_errors:
                    root = matching_errors[0]
                    children = matching_errors[1:]
                    
                    cascade = CascadePattern(
                        root_error=root,
                        child_errors=children,
                        pattern_type="repeated_error_spam",
                        confidence=1.0
                    )
                    self.cascade_patterns.append(cascade)
                    
                    root.is_cascading_root = True
                    root.cascade_group = len(self.cascade_patterns)
                    
                    for child in children:
                        child.is_cascading_child = True
                        child.cascade_group = len(self.cascade_patterns)
        
        self.stats['cascades_detected'] = len(self.cascade_patterns)
    
    def _parse_timestamp(self, timestamp: str) -> Optional[datetime]:
        """Parse timestamp string to datetime."""
        try:
            return datetime.strptime(timestamp, "%H:%M:%S")
        except:
            return None
    
    def _is_after(self, time1: str, time2: str) -> bool:
        """Check if time1 is after time2."""
        t1 = self._parse_timestamp(time1)
        t2 = self._parse_timestamp(time2)
        if t1 and t2:
            return t1 > t2
        return False
    
    def get_errors(
        self,
        category: Optional[str] = None,
        priority: Optional[int] = None,
        mod_filter: Optional[str] = None,
        exclude_cascade_children: bool = False,
        limit: int = 100,
    ) -> List[CK3Error]:
        """
        Get filtered list of errors.
        
        Args:
            category: Filter by error category
            priority: Filter by max priority (1-5)
            mod_filter: Filter by mod name (partial match)
            exclude_cascade_children: Exclude errors that are cascade children
            limit: Maximum results to return
        
        Returns:
            List of matching errors
        """
        results = self.errors
        
        if category:
            results = [e for e in results if e.category == category]
        
        if priority:
            results = [e for e in results if e.priority <= priority]
        
        if mod_filter:
            mod_lower = mod_filter.lower()
            results = [e for e in results if e.mod_name and mod_lower in e.mod_name.lower()]
        
        if exclude_cascade_children:
            results = [e for e in results if not e.is_cascading_child]
        
        return results[:limit]
    
    def search_errors(
        self,
        query: str,
        limit: int = 50,
    ) -> List[CK3Error]:
        """
        Search errors by message or file path.
        
        Args:
            query: Search query (case-insensitive)
            limit: Maximum results
        
        Returns:
            List of matching errors
        """
        query_lower = query.lower()
        results = []
        
        for error in self.errors:
            if query_lower in error.message.lower():
                results.append(error)
            elif error.file_path and query_lower in error.file_path.lower():
                results.append(error)
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_errors": self.stats['total_errors'],
            "cascades_detected": self.stats['cascades_detected'],
            "by_priority": {
                1: self.stats['by_priority'].get(1, 0),
                2: self.stats['by_priority'].get(2, 0),
                3: self.stats['by_priority'].get(3, 0),
                4: self.stats['by_priority'].get(4, 0),
                5: self.stats['by_priority'].get(5, 0),
            },
            "by_category": dict(self.stats['by_category'].most_common(15)),
            "by_mod": dict(self.stats['by_mod'].most_common(20)),
            "priority_labels": {
                1: "CRITICAL",
                2: "HIGH", 
                3: "MEDIUM",
                4: "LOW",
                5: "VERY LOW"
            }
        }
    
    def get_actionable_errors(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get high-priority, actionable errors (not cascade children).
        
        Returns errors that should be fixed, prioritized by importance.
        """
        actionable = [
            e for e in self.errors 
            if e.priority <= 3 and not e.is_cascading_child
        ]
        
        # Sort by priority, then by cascade root status
        actionable.sort(key=lambda e: (e.priority, -int(e.is_cascading_root)))
        
        results = []
        for error in actionable[:limit]:
            cat = next((c for c in ERROR_CATEGORIES if c.name == error.category), None)
            results.append({
                **error.to_dict(),
                "fix_hint": cat.fix_hint if cat else None,
                "description": cat.description if cat else None,
            })
        
        return results


# Convenience functions

def parse_error_log(
    log_path: Optional[Path] = None,
    detect_cascades: bool = True,
) -> CK3ErrorParser:
    """
    Parse a CK3 error log file.
    
    Args:
        log_path: Path to error.log (default: auto-detect)
        detect_cascades: Whether to run cascade detection
    
    Returns:
        Configured CK3ErrorParser with parsed data
    """
    parser = CK3ErrorParser()
    
    if log_path:
        parser.logs_dir = log_path.parent
        parser.parse_log(log_path)
    else:
        parser.parse_log()
    
    if detect_cascades:
        parser.detect_cascading_errors()
    
    return parser


def get_errors_summary(log_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Quick summary of errors from the error log.
    
    Args:
        log_path: Path to error.log (default: auto-detect)
    
    Returns:
        Summary dict with counts and top errors
    """
    parser = parse_error_log(log_path)
    return parser.get_summary()
