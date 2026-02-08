#!/usr/bin/env python3
"""
One-shot chat session extractor for CK3 Lens.

SAFETY: This tool REFUSES to run if VS Code is running.
When VS Code is closed, it extracts chat sessions to archive storage.

The process exits completely after extraction - no lingering file handles.
"""

import json
import sys
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# Version
__version__ = "2.0.0"


def get_ck3raven_root() -> Path:
    """Get the ~/.ck3raven directory."""
    return Path.home() / '.ck3raven'


def is_vscode_running() -> bool:
    """
    Check if VS Code process is running.
    
    Uses psutil if available, falls back to platform-specific checks.
    """
    try:
        import psutil
        vscode_names = {'code.exe', 'code', 'code - insiders.exe', 'code - insiders'}
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name']
                if name and name.lower() in vscode_names:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False
    except ImportError:
        # Fallback: use platform-specific process listing
        import subprocess
        import platform
        
        if platform.system() == 'Windows':
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq Code.exe'],
                capture_output=True, text=True
            )
            return 'Code.exe' in result.stdout
        else:
            result = subprocess.run(
                ['pgrep', '-x', 'code'],
                capture_output=True
            )
            return result.returncode == 0


def load_manifest() -> Optional[dict]:
    """Load the journal manifest."""
    manifest_path = get_ck3raven_root() / 'journal_manifest.json'
    if not manifest_path.exists():
        return None
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def parse_chat_session(content: str, session_id: str) -> dict:
    """
    Parse a VS Code chat session JSONL file.
    
    Returns a structured representation of the conversation.
    """
    messages = []
    metadata = {
        'session_id': session_id,
        'created_at': None,
        'title': None,
    }
    
    for line in content.strip().split('\n'):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            
            # Extract metadata from first entry
            if metadata['created_at'] is None and 'creationDate' in entry:
                metadata['created_at'] = entry['creationDate']
            if metadata['title'] is None and 'customTitle' in entry:
                metadata['title'] = entry['customTitle']
            
            # Extract messages
            if 'requests' in entry:
                for req in entry['requests']:
                    # User message
                    if 'message' in req and 'text' in req['message']:
                        messages.append({
                            'role': 'user',
                            'content': req['message']['text'],
                        })
                    
                    # Assistant response
                    if 'response' in req:
                        response_parts = []
                        for part in req['response']:
                            if 'value' in part:
                                response_parts.append(part['value'])
                        if response_parts:
                            messages.append({
                                'role': 'assistant',
                                'content': '\n'.join(response_parts),
                            })
        except json.JSONDecodeError:
            continue
    
    return {
        'metadata': metadata,
        'messages': messages,
    }


def convert_to_markdown(parsed: dict) -> str:
    """Convert parsed chat session to markdown format."""
    lines = []
    meta = parsed['metadata']
    
    # Header
    lines.append(f"# Chat Session: {meta.get('title') or meta['session_id'][:8]}")
    lines.append("")
    lines.append(f"**Session ID:** `{meta['session_id']}`")
    if meta.get('created_at'):
        lines.append(f"**Created:** {meta['created_at']}")
    lines.append("")
    lines.append("---")
    lines.append("")
    
    # Messages
    for msg in parsed['messages']:
        role = msg['role']
        content = msg['content']
        
        if role == 'user':
            lines.append("## User")
            lines.append("")
            lines.append(content)
        else:
            lines.append("## Assistant")
            lines.append("")
            lines.append(content)
        
        lines.append("")
        lines.append("---")
        lines.append("")
    
    return '\n'.join(lines)


def extract_workspace(workspace: dict, journals_root: Path) -> dict:
    """
    Extract chat sessions from one workspace.
    
    Copies raw files and converts to markdown archives.
    """
    result = {
        'workspace_key': workspace['workspace_key'],
        'workspace_name': workspace['workspace_name'],
        'files_extracted': 0,
        'archives_created': 0,
        'errors': [],
    }
    
    chat_path = Path(workspace['chat_sessions_path'])
    if not chat_path.exists():
        result['errors'].append(f"Path does not exist: {chat_path}")
        return result
    
    # Output directories
    workspace_journal = journals_root / workspace['workspace_key']
    raw_dir = workspace_journal / 'raw'
    archives_dir = workspace_journal / 'chat_archives'
    raw_dir.mkdir(parents=True, exist_ok=True)
    archives_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all session files
    session_files = list(chat_path.glob('*.jsonl')) + list(chat_path.glob('*.json'))
    
    for file in session_files:
        try:
            # CRITICAL: Open → Read → Close (minimize handle duration)
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Copy raw file
            raw_dest = raw_dir / file.name
            with open(raw_dest, 'w', encoding='utf-8') as f:
                f.write(content)
            result['files_extracted'] += 1
            
            # Parse and convert to markdown
            session_id = file.stem
            try:
                parsed = parse_chat_session(content, session_id)
                if parsed['messages']:  # Only create archive if there are messages
                    md_content = convert_to_markdown(parsed)
                    md_dest = archives_dir / f"{session_id}.md"
                    with open(md_dest, 'w', encoding='utf-8') as f:
                        f.write(md_content)
                    result['archives_created'] += 1
            except Exception as e:
                result['errors'].append(f"Parse error {file.name}: {str(e)}")
                # Raw copy still succeeded, continue
                
        except Exception as e:
            result['errors'].append(f"{file.name}: {str(e)}")
    
    return result


def main():
    """Main entry point for the CLI."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Extract VS Code chat sessions to CK3 Lens journal archives.',
        epilog='This tool must be run when VS Code is CLOSED.'
    )
    parser.add_argument(
        '--force', '-f',
        action='store_true',
        help='Force extraction even if VS Code appears to be running (dangerous!)'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results as JSON'
    )
    parser.add_argument(
        '--version', '-v',
        action='version',
        version=f'%(prog)s {__version__}'
    )
    
    args = parser.parse_args()
    
    def output(data: dict):
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            if data.get('success'):
                print(f"✓ Extraction complete")
                print(f"  Workspaces: {data.get('workspaces_processed', 0)}")
                print(f"  Files extracted: {data.get('files_extracted', 0)}")
                print(f"  Archives created: {data.get('archives_created', 0)}")
                if data.get('total_errors', 0) > 0:
                    print(f"  Errors: {data['total_errors']}")
            else:
                print(f"✗ {data.get('error', 'Unknown error')}")
                if data.get('hint'):
                    print(f"  Hint: {data['hint']}")
    
    # GUARD: Refuse to run if VS Code is running
    if not args.force and is_vscode_running():
        output({
            'success': False,
            'error': 'VS Code is running. Close it first.',
            'hint': 'Use --force to override (dangerous - may cause chat session loss).'
        })
        sys.exit(1)
    
    if args.force and is_vscode_running():
        if not args.json:
            print("⚠ WARNING: VS Code appears to be running. Proceeding anyway (--force).")
    
    # Load manifest
    manifest = load_manifest()
    if not manifest:
        output({
            'success': False,
            'error': 'Manifest not found.',
            'hint': 'Run VS Code with CK3 Lens extension first to generate manifest.'
        })
        sys.exit(1)
    
    if not manifest.get('workspaces'):
        output({
            'success': False,
            'error': 'No workspaces in manifest.',
            'hint': 'Open a workspace in VS Code with CK3 Lens extension.'
        })
        sys.exit(1)
    
    # Extract from each workspace
    journals_root = get_ck3raven_root() / 'journals'
    results = []
    
    for workspace in manifest['workspaces']:
        result = extract_workspace(workspace, journals_root)
        results.append(result)
    
    # Summary
    total_files = sum(r['files_extracted'] for r in results)
    total_archives = sum(r['archives_created'] for r in results)
    total_errors = sum(len(r['errors']) for r in results)
    
    output({
        'success': True,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'workspaces_processed': len(results),
        'files_extracted': total_files,
        'archives_created': total_archives,
        'total_errors': total_errors,
        'details': results if args.json else None,
    })
    
    sys.exit(0 if total_errors == 0 else 2)


if __name__ == '__main__':
    main()
