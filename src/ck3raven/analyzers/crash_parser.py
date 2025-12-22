"""
CK3 Crash Log Parser

Parses crash folders in the CK3 crashes directory.
Each crash folder contains:
- exception.txt - Stack trace and crash info
- meta.yml - Crash metadata
- logs/ - Copy of logs at crash time (error.log, game.log, debug.log)
- minidump.dmp - Windows minidump (binary)
- last_save.ck3 - Save file at crash time
"""

import re
import os
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime


@dataclass
class CrashReport:
    """Represents a parsed crash report."""
    crash_id: str  # Folder name like ck3_20251217_060926
    crash_time: datetime
    game_version: str
    exception_type: str  # e.g., "EXCEPTION_ACCESS_VIOLATION"
    exception_address: str
    stack_trace: List[str]
    has_save: bool
    has_minidump: bool
    
    # From meta.yml if available
    meta: Dict[str, Any] = field(default_factory=dict)
    
    # Error summary from crash logs
    error_count: int = 0
    critical_errors: List[str] = field(default_factory=list)
    
    # Associated log content (truncated)
    error_log_preview: str = ""
    game_log_preview: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result['crash_time'] = self.crash_time.isoformat() if self.crash_time else None
        return result


def parse_exception_txt(exception_path: Path) -> Dict[str, Any]:
    """
    Parse exception.txt from a crash folder.
    
    Returns:
        Dict with version, exception type, address, and stack trace
    """
    result = {
        "game_version": "unknown",
        "exception_type": "unknown",
        "exception_address": "unknown",
        "stack_trace": []
    }
    
    if not exception_path.exists():
        return result
    
    content = exception_path.read_text(encoding='utf-8', errors='replace')
    
    # Parse version
    version_match = re.search(r'Version:\s*(.+)', content)
    if version_match:
        result["game_version"] = version_match.group(1).strip()
    
    # Parse exception type
    # Format: "Unhandled Exception C0000005 (EXCEPTION_ACCESS_VIOLATION)"
    exception_match = re.search(r'Unhandled Exception\s+\w+\s+\(([^)]+)\)', content)
    if exception_match:
        result["exception_type"] = exception_match.group(1)
    
    # Parse exception address
    address_match = re.search(r'at address\s+(0x[0-9A-Fa-f]+)', content)
    if address_match:
        result["exception_address"] = address_match.group(1)
    
    # Parse stack trace
    stack_lines = []
    in_stack = False
    for line in content.splitlines():
        if "Stack Trace:" in line:
            in_stack = True
            continue
        if in_stack:
            line = line.strip()
            if line and not line.startswith("Application:"):
                stack_lines.append(line)
    
    result["stack_trace"] = stack_lines[:20]  # Limit to 20 frames
    
    return result


def parse_meta_yml(meta_path: Path) -> Dict[str, Any]:
    """
    Parse meta.yml from a crash folder.
    
    Returns:
        Dict with metadata
    """
    result = {}
    
    if not meta_path.exists():
        return result
    
    content = meta_path.read_text(encoding='utf-8', errors='replace')
    
    # Simple YAML-like parsing (key: value)
    for line in content.splitlines():
        if ':' in line:
            key, _, value = line.partition(':')
            result[key.strip()] = value.strip()
    
    return result


def get_log_preview(log_path: Path, max_lines: int = 50, from_end: bool = True) -> str:
    """
    Get a preview of a log file.
    
    Args:
        log_path: Path to log file
        max_lines: Maximum lines to return
        from_end: If True, get last N lines; otherwise first N
    
    Returns:
        Log content preview
    """
    if not log_path.exists():
        return ""
    
    try:
        lines = log_path.read_text(encoding='utf-8', errors='replace').splitlines()
        
        if from_end:
            selected = lines[-max_lines:] if len(lines) > max_lines else lines
        else:
            selected = lines[:max_lines]
        
        return "\n".join(selected)
    except Exception:
        return ""


def count_errors_in_log(log_path: Path) -> tuple:
    """
    Count errors in a log file.
    
    Returns:
        Tuple of (total_count, list of critical error messages)
    """
    if not log_path.exists():
        return 0, []
    
    try:
        content = log_path.read_text(encoding='utf-8', errors='replace')
        
        total = content.count('[E]')
        
        # Find critical errors (priority 1-2 patterns)
        critical_patterns = [
            r'fatal\(crash\)',
            r'jomini_script_system\.cpp.*error',
            r'Incorrect MOD descriptor',
        ]
        
        critical = []
        for line in content.splitlines():
            if '[E]' in line:
                for pattern in critical_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        # Extract just the message part
                        match = re.match(r'\[[^\]]+\]\[E\]\[[^\]]+\]:\s*(.*)', line)
                        if match:
                            critical.append(match.group(1)[:200])
                        break
        
        return total, critical[:10]  # Limit critical errors
    except Exception:
        return 0, []


def parse_crash_folder(crash_path: Path) -> Optional[CrashReport]:
    """
    Parse a single crash folder.
    
    Args:
        crash_path: Path to crash folder (e.g., ck3_20251217_060926)
    
    Returns:
        CrashReport or None if invalid folder
    """
    if not crash_path.is_dir():
        return None
    
    folder_name = crash_path.name
    
    # Parse crash time from folder name (ck3_YYYYMMDD_HHMMSS)
    time_match = re.match(r'ck3_(\d{8})_(\d{6})', folder_name)
    if not time_match:
        return None
    
    try:
        crash_time = datetime.strptime(
            time_match.group(1) + time_match.group(2),
            "%Y%m%d%H%M%S"
        )
    except ValueError:
        crash_time = datetime.now()
    
    # Parse exception.txt
    exception_data = parse_exception_txt(crash_path / "exception.txt")
    
    # Parse meta.yml
    meta = parse_meta_yml(crash_path / "meta.yml")
    
    # Check for files
    has_save = (crash_path / "last_save.ck3").exists()
    has_minidump = (crash_path / "minidump.dmp").exists()
    
    # Get log previews
    logs_dir = crash_path / "logs"
    error_log_preview = get_log_preview(logs_dir / "error.log", max_lines=30, from_end=True)
    game_log_preview = get_log_preview(logs_dir / "game.log", max_lines=20, from_end=True)
    
    # Count errors
    error_count, critical_errors = count_errors_in_log(logs_dir / "error.log")
    
    return CrashReport(
        crash_id=folder_name,
        crash_time=crash_time,
        game_version=exception_data["game_version"],
        exception_type=exception_data["exception_type"],
        exception_address=exception_data["exception_address"],
        stack_trace=exception_data["stack_trace"],
        has_save=has_save,
        has_minidump=has_minidump,
        meta=meta,
        error_count=error_count,
        critical_errors=critical_errors,
        error_log_preview=error_log_preview,
        game_log_preview=game_log_preview,
    )


def get_recent_crashes(
    crashes_dir: Optional[Path] = None,
    limit: int = 10,
) -> List[CrashReport]:
    """
    Get recent crash reports.
    
    Args:
        crashes_dir: Path to CK3 crashes directory (default: auto-detect)
        limit: Maximum number of crashes to return
    
    Returns:
        List of CrashReport, newest first
    """
    if crashes_dir is None:
        crashes_dir = (
            Path.home() / "Documents" / "Paradox Interactive" / 
            "Crusader Kings III" / "crashes"
        )
    
    if not crashes_dir.exists():
        return []
    
    # Get all crash folders
    crash_folders = []
    for item in crashes_dir.iterdir():
        if item.is_dir() and item.name.startswith("ck3_"):
            crash_folders.append(item)
    
    # Sort by name (which contains date) - newest first
    crash_folders.sort(key=lambda x: x.name, reverse=True)
    
    # Parse each folder
    reports = []
    for folder in crash_folders[:limit]:
        report = parse_crash_folder(folder)
        if report:
            reports.append(report)
    
    return reports


def get_crash_summary(crashes_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Get summary of recent crashes.
    
    Args:
        crashes_dir: Path to crashes directory
    
    Returns:
        Summary dict
    """
    crashes = get_recent_crashes(crashes_dir, limit=20)
    
    if not crashes:
        return {
            "total_crashes": 0,
            "recent_crashes": [],
            "common_exception_types": {},
        }
    
    # Count exception types
    exception_counts: Dict[str, int] = {}
    for crash in crashes:
        exc_type = crash.exception_type
        exception_counts[exc_type] = exception_counts.get(exc_type, 0) + 1
    
    return {
        "total_crashes": len(crashes),
        "recent_crashes": [
            {
                "crash_id": c.crash_id,
                "crash_time": c.crash_time.isoformat(),
                "game_version": c.game_version,
                "exception_type": c.exception_type,
                "error_count": c.error_count,
            }
            for c in crashes[:5]
        ],
        "common_exception_types": exception_counts,
        "newest_crash": crashes[0].crash_id if crashes else None,
        "oldest_crash": crashes[-1].crash_id if crashes else None,
    }
