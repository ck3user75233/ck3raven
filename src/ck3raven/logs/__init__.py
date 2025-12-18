"""
CK3 Log Parsing Module

Provides parsers for CK3's various log files:
- error.log - Script and system errors
- game.log - Game events and state changes
- debug.log - Debug output
- Crash logs - exception.txt, meta.yml, and associated logs
"""

from ck3raven.logs.error_parser import (
    CK3Error,
    ErrorCategory,
    CascadePattern,
    CK3ErrorParser,
    parse_error_log,
    get_errors_summary,
)

from ck3raven.logs.crash_parser import (
    CrashReport,
    parse_crash_folder,
    get_recent_crashes,
)

__all__ = [
    # Error parsing
    "CK3Error",
    "ErrorCategory", 
    "CascadePattern",
    "CK3ErrorParser",
    "parse_error_log",
    "get_errors_summary",
    # Crash parsing
    "CrashReport",
    "parse_crash_folder",
    "get_recent_crashes",
]
