"""
Git Operations

Git commands for live mods, sandboxed to whitelisted paths.
"""
from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Optional

from .workspace import Session


def _run_git(mod_path: Path, *args: str) -> tuple[bool, str, str]:
    """Run git command in mod directory."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=mod_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except FileNotFoundError:
        return False, "", "Git not found in PATH"
    except Exception as e:
        return False, "", str(e)


def git_status(session: Session, mod_id: str) -> dict:
    """Git status for a live mod."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    if not (mod.path / ".git").exists():
        return {"error": f"{mod_id} is not a git repository"}
    
    # Get branch
    ok, branch, err = _run_git(mod.path, "rev-parse", "--abbrev-ref", "HEAD")
    if not ok:
        return {"error": f"Failed to get branch: {err}"}
    branch = branch.strip()
    
    # Get status
    ok, status, err = _run_git(mod.path, "status", "--porcelain")
    if not ok:
        return {"error": f"Failed to get status: {err}"}
    
    staged = []
    unstaged = []
    untracked = []
    
    for line in status.strip().split("\n"):
        if not line:
            continue
        index = line[0]
        worktree = line[1]
        filename = line[3:]
        
        if index == "?":
            untracked.append(filename)
        elif index != " ":
            staged.append({"status": index, "file": filename})
        if worktree not in (" ", "?"):
            unstaged.append({"status": worktree, "file": filename})
    
    return {
        "mod_id": mod_id,
        "branch": branch,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "clean": len(staged) == 0 and len(unstaged) == 0 and len(untracked) == 0
    }


def git_diff(session: Session, mod_id: str, staged: bool = False) -> dict:
    """Show uncommitted changes."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    args = ["diff"]
    if staged:
        args.append("--cached")
    
    ok, diff, err = _run_git(mod.path, *args)
    if not ok:
        return {"error": err}
    
    return {
        "mod_id": mod_id,
        "staged": staged,
        "diff": diff
    }


def git_add(
    session: Session,
    mod_id: str,
    files: Optional[list[str]] = None,
    all_files: bool = False
) -> dict:
    """Stage files for commit."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    if all_files:
        args = ["add", "-A"]
    elif files:
        args = ["add"] + files
    else:
        return {"error": "Must specify files or all_files=True"}
    
    ok, out, err = _run_git(mod.path, *args)
    if not ok:
        return {"success": False, "error": err}
    
    return {"success": True, "mod_id": mod_id}


def git_commit(session: Session, mod_id: str, message: str) -> dict:
    """Commit staged changes."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    ok, out, err = _run_git(mod.path, "commit", "-m", message)
    if not ok:
        if "nothing to commit" in err or "nothing to commit" in out:
            return {"success": False, "error": "Nothing to commit"}
        return {"success": False, "error": err}
    
    # Get commit hash
    ok2, hash_out, _ = _run_git(mod.path, "rev-parse", "HEAD")
    commit_hash = hash_out.strip() if ok2 else "unknown"
    
    return {
        "success": True,
        "mod_id": mod_id,
        "commit_hash": commit_hash,
        "message": message
    }


def git_push(
    session: Session,
    mod_id: str,
    remote: str = "origin",
    branch: Optional[str] = None
) -> dict:
    """Push to remote."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    args = ["push", remote]
    if branch:
        args.append(branch)
    
    ok, out, err = _run_git(mod.path, *args)
    if not ok:
        return {"success": False, "error": err}
    
    return {
        "success": True,
        "mod_id": mod_id,
        "remote": remote,
        "output": out + err
    }


def git_pull(
    session: Session,
    mod_id: str,
    remote: str = "origin",
    branch: Optional[str] = None
) -> dict:
    """Pull from remote."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    
    args = ["pull", remote]
    if branch:
        args.append(branch)
    
    ok, out, err = _run_git(mod.path, *args)
    if not ok:
        return {"success": False, "error": err}
    
    return {
        "success": True,
        "mod_id": mod_id,
        "remote": remote,
        "output": out + err
    }


def git_log(session: Session, mod_id: str, limit: int = 10, file_path: Optional[str] = None) -> dict:
    """Recent commit history."""
    mod = session.get_local_mod(mod_id)
    if not mod:
        return {"error": f"Unknown mod_id: {mod_id}"}
    args = ["log", f"-{limit}", "--pretty=format:%H|%an|%ai|%s"]
    if file_path:
        args.append("--")
        args.append(file_path)

    ok, out, err = _run_git(mod.path, *args)
    if not ok:
        return {"error": err}
    
    commits = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3]
            })
    
    return {
        "mod_id": mod_id,
        "commits": commits
    }
