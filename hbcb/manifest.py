"""Manifest assembly.

The manifest is the build's receipt: what was asked for, what produced it, what
came out, and whether it passed. It is written last and only on success, so its
presence in an output directory is itself the signal that the directory is
complete.

`manifest.json` hashes every other artifact but not itself -- a file cannot
contain its own hash.
"""

import os
import platform
import subprocess
import sys

from . import GENERATOR_ID, GENERATOR_VERSION, __version__, canonical

MANIFEST_VERSION = "manifest/v1"
MANIFEST_NAME = "manifest.json"

# Written into the container image at build time; see docker/builder.Dockerfile.
IMAGE_REVISION_FILE = "/opt/builder/revision"


def project_revision():
    """Identify the source that produced this build, best effort.

    Three sources in order of trust: an explicit environment override, the
    revision baked into a container image, and finally the working tree's git
    commit. Returns None when none of them is available, which is honest rather
    than inventing a value.
    """
    override = os.environ.get("HBCB_PROJECT_REVISION")
    if override:
        return override.strip()

    if os.path.isfile(IMAGE_REVISION_FILE):
        try:
            with open(IMAGE_REVISION_FILE, encoding="utf-8") as handle:
                value = handle.read().strip()
            if value:
                return value
        except OSError:
            pass

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def hash_artifacts(output_dir, relative_paths):
    """Hash and size every published artifact except the manifest itself."""
    artifacts = {}
    for relative in sorted(relative_paths):
        if relative == MANIFEST_NAME:
            continue
        absolute = os.path.join(output_dir, relative)
        artifacts[relative] = {
            "sha256": canonical.sha256_of_file(absolute),
            "bytes": os.path.getsize(absolute),
        }
    return artifacts


def build(request, execution, model, qa_summary, artifacts, adjustments, status):
    """Assemble the manifest document."""
    return {
        "manifest_version": MANIFEST_VERSION,
        "status": status,
        "generator": {
            "id": GENERATOR_ID,
            "version": GENERATOR_VERSION,
            "toolkit_version": __version__,
        },
        "request": request.to_json(),
        "execution": execution,
        "model": model,
        "qa": qa_summary,
        "adjustments": adjustments,
        "artifacts": artifacts,
    }


def execution_context(mode, blender_version, duration_seconds, created_at):
    """Provenance for the process that produced the build.

    `created_at` is passed in rather than read here so a caller that needs a
    byte-reproducible manifest can hold it fixed.
    """
    return {
        "mode": mode,
        "blender_version": blender_version,
        "python_version": sys.version.split()[0],
        "platform": "%s-%s" % (platform.system().lower(), platform.machine()),
        "project_revision": project_revision(),
        "worker_image_reference": os.environ.get("HBCB_IMAGE_REFERENCE"),
        "worker_image_digest": os.environ.get("HBCB_IMAGE_DIGEST"),
        "created_at": created_at,
        "duration_seconds": round(duration_seconds, 3),
    }


def verify_artifacts(output_dir, manifest):
    """Re-hash the artifacts a manifest claims and report any mismatch.

    Returns a list of human-readable problems; empty means the directory
    matches its manifest exactly.
    """
    problems = []
    for relative, expected in sorted(manifest.get("artifacts", {}).items()):
        absolute = os.path.join(output_dir, relative)
        if not os.path.isfile(absolute):
            problems.append("%s: listed in the manifest but missing" % relative)
            continue
        actual_size = os.path.getsize(absolute)
        if actual_size != expected["bytes"]:
            problems.append(
                "%s: size is %d bytes, manifest says %d"
                % (relative, actual_size, expected["bytes"])
            )
        actual_hash = canonical.sha256_of_file(absolute)
        if actual_hash != expected["sha256"]:
            problems.append(
                "%s: sha256 is %s, manifest says %s"
                % (relative, actual_hash[:16], expected["sha256"][:16])
            )
    return problems
