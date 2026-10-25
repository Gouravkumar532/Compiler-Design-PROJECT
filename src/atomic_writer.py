"""
Atomic File Writer & Backup Facility (Idea 9: Phase 4)

Guarantees safety so user source files are never corrupted by unexpected
interrupts, crashes, or partial writes.
"""

import os
import shutil
import tempfile
from typing import Dict, Optional


def create_backup(file_path: str, backup_ext: str = ".bak") -> Optional[str]:
    """
    Creates a backup copy of file_path with given extension (e.g., test.cpp.bak).
    Returns the backup file path, or None if the source file does not exist.
    """
    if not os.path.isfile(file_path):
        return None

    backup_path = file_path + backup_ext
    shutil.copy2(file_path, backup_path)
    return backup_path


def restore_backup(file_path: str, backup_ext: str = ".bak") -> bool:
    """
    Restores file_path from its backup file if it exists.
    Returns True if successfully restored, False otherwise.
    """
    backup_path = file_path + backup_ext
    if not os.path.isfile(backup_path):
        return False

    shutil.copy2(backup_path, file_path)
    return True


def atomic_write(
    file_path: str,
    content: str,
    backup: bool = False,
    backup_ext: str = ".bak",
    encoding: str = "utf-8",
) -> bool:
    """
    Atomically writes content to file_path.
    1. Optionally creates a backup file (<file_path>.bak) if requested.
    2. Writes to a temporary file in the same directory.
    3. Atomically replaces target file using os.replace().
    Guarantees no partial or corrupted writes if interrupted.
    """
    abs_path = os.path.abspath(file_path)
    dir_name = os.path.dirname(abs_path) or "."

    # 1. Backup if requested
    if backup and os.path.isfile(abs_path):
        create_backup(abs_path, backup_ext)

    # 2. Temporary file in same directory (guarantees same filesystem for atomic rename)
    temp_fd, temp_path = tempfile.mkstemp(
        dir=dir_name,
        prefix=f".{os.path.basename(abs_path)}.tmp_",
        suffix=".tmp",
    )

    try:
        with os.fdopen(temp_fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())

        # 3. Atomic replacement
        os.replace(temp_path, abs_path)
        return True
    except Exception:
        # Clean up temporary file on failure
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


def atomic_write_many(
    updates: Dict[str, str],
    backup: bool = False,
    backup_ext: str = ".bak",
    encoding: str = "utf-8",
) -> bool:
    """Commit multiple files as one rollback-capable transaction."""
    if not updates:
        return True
    staged: Dict[str, str] = {}
    originals: Dict[str, bytes] = {}
    replaced = []
    try:
        for file_path, content in updates.items():
            target = os.path.abspath(file_path)
            directory = os.path.dirname(target) or "."
            with open(target, "rb") as existing:
                originals[target] = existing.read()
            fd, temp_path = tempfile.mkstemp(
                dir=directory, prefix=f".{os.path.basename(target)}.txn_", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding=encoding, newline="") as staged_file:
                staged_file.write(content)
                staged_file.flush()
                os.fsync(staged_file.fileno())
            staged[target] = temp_path

        if backup:
            for target in staged:
                create_backup(target, backup_ext)

        for target, temp_path in staged.items():
            os.replace(temp_path, target)
            replaced.append(target)
        return True
    except Exception:
        for target in reversed(replaced):
            fd, restore_path = tempfile.mkstemp(
                dir=os.path.dirname(target) or ".",
                prefix=f".{os.path.basename(target)}.rollback_",
                suffix=".tmp",
            )
            with os.fdopen(fd, "wb") as restore_file:
                restore_file.write(originals[target])
                restore_file.flush()
                os.fsync(restore_file.fileno())
            os.replace(restore_path, target)
        raise
    finally:
        for temp_path in staged.values():
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
