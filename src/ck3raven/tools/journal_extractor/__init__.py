"""
Journal Extractor - One-shot chat session extraction.

Part of Chat Journaling v2.0 architecture.
MUST be run when VS Code is NOT running.

Usage:
    ck3lens-export-chats
    # or:
    python -m ck3raven.tools.journal_extractor
"""

from .extract import main

__all__ = ['main']
