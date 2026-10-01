"""Small OS adapters for project paths and kernel-owned file leases.

This is not a generated-code execution or Windows durable-evidence adapter.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import stat


def is_redirected(path: Path) -> bool:
    """Include all Windows reparse points, including junctions on Python 3.11."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def safe_path(path: Path) -> Path:
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("Parent traversal is not permitted in project or runtime paths.")
    path = Path(os.path.abspath(path))
    if os.name == "nt" and path.drive.startswith("\\\\"):
        raise ValueError("Use a local drive. Do not use network paths or device paths.")
    for part in (path, *path.parents):
        if is_redirected(part):
            raise ValueError("Project paths must not contain symlinks, junctions or other reparse points")
    return path


@contextmanager
def exclusive_lock(path: Path):
    """One nonblocking kernel lease; close/crash releases it on POSIX and Windows.

    Lock files are never deleted or replaced. POSIX retains the existing flock
    behavior; Windows locks byte zero with msvcrt, including beyond EOF.
    """
    path = safe_path(path)
    if path.exists() and not path.is_file():
        raise ValueError("Lock path must be a regular file")
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    acquired = False
    try:
        opened, named = os.fstat(descriptor), path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or is_redirected(path)
                or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("Lock path changed or is not a regular local file")
        if os.name == "nt":
            import msvcrt
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise BlockingIOError(errno.EAGAIN, "A process holds the project lease.") from exc
                raise
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        try:
            if acquired and os.name == "nt":
                import msvcrt
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(descriptor)
