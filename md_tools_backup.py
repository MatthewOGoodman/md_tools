"""
md_tools_backup — timestamped backups for md_tools' destructive verbs.

Functions:
    find_root_dir(start_path, markers)   Walk up to the nearest project root
    create_backup(filepath, tool_name)   Timestamped backup with hourly dedup
    cleanup_backups(directory)            Keep only the most recent backup per file

Backups land in ~/.claude/backups/<tool_name>/, named by project and relative
directory so one backup directory can hold files from many projects.
"""

import glob
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime


def find_root_dir(start_path, markers=None):
    """Walk up from start_path until a directory containing any marker is found.

    Args:
        start_path: File or directory path to start from.
        markers: List of filenames/dirnames to look for (ANY match stops).
                 Default: ["CLAUDE.md"]

    Returns:
        str: Directory containing the first marker match, or None.
    """
    if markers is None:
        markers = ["CLAUDE.md"]

    current = os.path.abspath(start_path)
    if os.path.isfile(current):
        current = os.path.dirname(current)

    while current != os.path.dirname(current):
        for marker in markers:
            if os.path.exists(os.path.join(current, marker)):
                return current
        current = os.path.dirname(current)

    return None


# ============================================================================



_backed_up = set()


def _get_backup_prefix(filepath):
    """Generate project-aware backup prefix for a file.

    Uses find_root_dir to locate the project root, then builds a prefix
    from the project name and any subdirectories.

    Args:
        filepath: Absolute path to the file being backed up.

    Returns:
        str: Prefix string like "claude-wrangler" or "claude-wrangler_.claude".
    """
    abs_path = os.path.abspath(filepath)
    project_root = find_root_dir(abs_path)

    if project_root:
        project_name = os.path.basename(project_root)
        rel_path = os.path.relpath(abs_path, project_root)
        parts = rel_path.split(os.sep)
        dir_parts = parts[:-1]

        if not dir_parts:
            prefix = project_name
        else:
            prefix = f"{project_name}_" + "_".join(dir_parts)

        # Fix invisible prefix: .claude → home.claude
        if prefix.startswith(".claude"):
            prefix = prefix.replace(".claude", "home.claude", 1)

        return prefix

    # Not in any project — use last 2 directory components
    parts = abs_path.split(os.sep)
    dir_parts = parts[:-1]
    return "_".join(dir_parts[-2:]) if len(dir_parts) >= 2 else "root"


def create_backup(filepath, tool_name):
    """Create a timestamped backup of a file.

    Backups are stored in ~/.claude/backups/{tool_name}/.
    Skips if the same file was already backed up this hour or this invocation.
    Uses project-aware prefix for the backup filename.

    Args:
        filepath: Absolute path to the file to back up.
        tool_name: Tool identifier for backup subdirectory (e.g., 'md_tools').

    Returns:
        str: Path to the backup file, or None if skipped.
    """
    if filepath in _backed_up:
        return None

    backup_dir = os.path.expanduser(f"~/.claude/backups/{tool_name}")
    os.makedirs(backup_dir, exist_ok=True)

    # Generate prefix and filename components
    prefix = _get_backup_prefix(filepath)
    filename = os.path.basename(filepath)
    base = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1]

    # Hourly dedup: skip if backup exists from the same hour
    current_hour = datetime.now().strftime("%Y%m%d_%H")
    name_pattern = f"{prefix}.{base}" if prefix else base
    existing = glob.glob(os.path.join(backup_dir, f"{name_pattern}.backup_{current_hour}*"))
    if existing:
        _backed_up.add(filepath)
        return existing[0]

    # Create backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{name_pattern}.backup_{timestamp}{ext}"
    backup_path = os.path.join(backup_dir, backup_filename)

    shutil.copy(filepath, backup_path)
    _backed_up.add(filepath)
    print(f"  → Created backup: {backup_filename} (in {backup_dir})", file=sys.stderr)
    return backup_path


def cleanup_backups(directory):
    """Delete all but most recent backup for each file in directory.

    Groups backups by base filename (before .backup_ timestamp),
    keeps the most recent per group, deletes the rest.

    Args:
        directory: Path to backup directory. Handles ~ expansion.

    Returns:
        bool: True if successful.
    """
    directory = os.path.expanduser(directory)

    backup_pattern = os.path.join(directory, "*.backup_*")
    backup_files = glob.glob(backup_pattern)

    if not backup_files:
        print("No backups found")
        return True

    pattern = re.compile(r'^(.+?)\.backup_(\d{8}_\d{6})\.?(.*)$')
    groups = defaultdict(list)

    for filepath in backup_files:
        filename = os.path.basename(filepath)
        match = pattern.match(filename)
        if match:
            base = match.group(1)
            groups[base].append(filepath)

    deleted = 0
    for base, files in groups.items():
        files.sort()
        for filepath in files[:-1]:
            os.remove(filepath)
            print(f"  → Deleted old backup: {os.path.basename(filepath)}")
            deleted += 1

    if deleted:
        print(f"✓ Cleaned up {deleted} old backup(s)")
    else:
        print("No old backups to clean up")

    return True
