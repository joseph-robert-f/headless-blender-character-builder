"""Locating a usable Blender.

A user who already has Blender installed should not have to tell us where it
is, and a user who does not should get a sentence that tells them exactly what
to do rather than a stack trace.
"""

import glob
import os
import platform
import re
import shutil
import subprocess

from . import MINIMUM_BLENDER

ENV_VAR = "HBCB_BLENDER"

_MACOS_CANDIDATES = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "~/Applications/Blender.app/Contents/MacOS/Blender",
)

_LINUX_CANDIDATES = (
    "/usr/bin/blender",
    "/usr/local/bin/blender",
    "/snap/bin/blender",
    "/var/lib/flatpak/exports/bin/org.blender.Blender",
    "~/.local/share/flatpak/exports/bin/org.blender.Blender",
)

_WINDOWS_GLOBS = (
    r"C:\Program Files\Blender Foundation\Blender*\blender.exe",
    r"C:\Program Files (x86)\Blender Foundation\Blender*\blender.exe",
)


def _candidates():
    override = os.environ.get(ENV_VAR)
    if override:
        # An explicit override is used even if it turns out not to work, so the
        # error names the path the user actually chose.
        yield os.path.expanduser(override)
        return

    found = shutil.which("blender")
    if found:
        yield found

    system = platform.system()
    if system == "Darwin":
        for path in _MACOS_CANDIDATES:
            yield os.path.expanduser(path)
    elif system == "Windows":
        for pattern in _WINDOWS_GLOBS:
            for path in sorted(glob.glob(pattern), reverse=True):
                yield path
    else:
        for path in _LINUX_CANDIDATES:
            yield os.path.expanduser(path)


def find():
    """Path to a Blender executable, or None."""
    for path in _candidates():
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def version(executable):
    """(major, minor, patch) reported by `executable`, or None if unreadable."""
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"Blender\s+(\d+)\.(\d+)(?:\.(\d+))?", result.stdout or "")
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def bpy_module_available():
    """True when Blender is importable as the `bpy` PyPI module.

    This is the fallback for environments where installing the Blender
    application is awkward but `pip install bpy` is not.
    """
    try:
        import bpy  # noqa: F401
    except Exception:
        return False
    return True


def format_version(value):
    return ".".join(str(part) for part in value)


INSTALL_HINT = """Blender was not found.

Fix any one of these:
  * install Blender %s or newer from https://www.blender.org/download/
  * point %s at the executable, for example:
        export %s=/Applications/Blender.app/Contents/MacOS/Blender
  * install Blender as a Python module:  pip install bpy
  * or skip the local install entirely and use the container:  make demo""" % (
    format_version(MINIMUM_BLENDER),
    ENV_VAR,
    ENV_VAR,
)
