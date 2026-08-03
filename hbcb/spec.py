"""Loading, validating, and resolving a BuildRequest.

This is the single place a request becomes trustworthy. Every execution mode
(native CLI, container, and any future HTTP service) resolves through here, so
none of them can drift into accepting something the others reject.
"""

import json
import os
import re

from . import canonical, presets, print_profiles
from .exit_codes import FILESYSTEM, INVALID_REQUEST, BuildError
from .validate import SchemaError, SchemaStore

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_DIR)
SCHEMA_DIR = os.path.join(REPO_ROOT, "schemas")

REQUEST_SCHEMA = "build-request-v1.schema.json"
SPEC_SCHEMA = "character-spec-v1.schema.json"

# A build request is a small declarative document. The cap exists so a hostile
# or accidental multi-megabyte file is rejected before it is parsed.
MAX_REQUEST_BYTES = 64 * 1024
MAX_SLUG_LENGTH = 48

_store = None


def store():
    """Shared schema store. Reads each schema file at most once per process."""
    global _store
    if _store is None:
        _store = SchemaStore(SCHEMA_DIR)
    return _store


def slugify(name):
    """Filesystem-safe slug derived from a display name.

    Output is restricted to lowercase alphanumerics and single hyphens, which
    keeps it safe as a path component on every supported platform.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = slug[:MAX_SLUG_LENGTH].strip("-")
    return slug or "character"


def load_request_file(path):
    """Read and parse a request file, with size and syntax errors mapped to exit codes."""
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise BuildError(FILESYSTEM, "cannot read request file %s: %s" % (path, error)) from error
    if size > MAX_REQUEST_BYTES:
        raise BuildError(
            INVALID_REQUEST,
            "request file is %d bytes, over the %d byte limit" % (size, MAX_REQUEST_BYTES),
        )
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except UnicodeDecodeError as error:
        raise BuildError(INVALID_REQUEST, "request file is not valid UTF-8: %s" % error) from error
    except json.JSONDecodeError as error:
        raise BuildError(
            INVALID_REQUEST,
            "request file is not valid JSON (line %d, column %d): %s"
            % (error.lineno, error.colno, error.msg),
        ) from error
    except OSError as error:
        raise BuildError(FILESYSTEM, "cannot read request file %s: %s" % (path, error)) from error


class ResolvedRequest:
    """A validated request plus everything derived from it.

    Two hashes are recorded on purpose. `request_sha256` covers the bytes the
    caller actually submitted, which is what an idempotency key or an audit
    trail cares about. `resolved_sha256` covers the document after defaults are
    filled, which is what determines the geometry -- so spelling a default out
    explicitly does not change the structural result.

    There is no seed. `geometric-character@1.0.0` makes no random choices, so
    an identical request produces an identical structure without one.
    """

    def __init__(self, raw, resolved, print_profile):
        self.raw = raw
        self.resolved = resolved
        self.spec = resolved["spec"]
        self.print_profile = print_profile
        self.request_sha256 = canonical.sha256_of_obj(raw)
        self.resolved_sha256 = canonical.sha256_of_obj(resolved)
        self.spec_sha256 = canonical.sha256_of_obj(self.spec)
        self.generator = resolved["generator"]
        self.output_profile = resolved["output_profile"]
        self.render_profile = resolved["render_profile"]
        self.quality_profile = resolved["quality_profile"]
        self.slug = slugify(self.spec["name"])

    @property
    def strict_qa(self):
        """True when a failed print check must fail the build."""
        return self.quality_profile == "geometry-v1"

    def to_json(self):
        """The shape embedded in the manifest under `request`."""
        return {
            "request_sha256": self.request_sha256,
            "resolved_sha256": self.resolved_sha256,
            "spec_sha256": self.spec_sha256,
            "resolved": self.resolved,
            "print_profile": self.print_profile,
        }


def resolve(raw):
    """Validate a raw request document and return a `ResolvedRequest`.

    Raises BuildError(INVALID_REQUEST) with every schema problem listed, so a
    user fixing a hand-written file sees all of them in one pass.
    """
    if not isinstance(raw, dict):
        raise BuildError(
            INVALID_REQUEST,
            "a BuildRequest must be a JSON object, got %s" % type(raw).__name__,
        )
    schemas = store()
    try:
        schemas.validate(REQUEST_SCHEMA, raw)
    except SchemaError as error:
        raise BuildError(
            INVALID_REQUEST,
            "BuildRequest failed validation:\n  - %s" % "\n  - ".join(error.errors),
        ) from error

    resolved = schemas.fill_defaults(REQUEST_SCHEMA, raw)
    profile = print_profiles.resolve(resolved.get("print_profile"))
    # The resolved document carries the fully expanded profile so the manifest
    # and the geometry agree on the thresholds that were actually applied.
    resolved["print_profile"] = profile
    return ResolvedRequest(raw, resolved, profile)


def resolve_file(path):
    return resolve(load_request_file(path))


def resolve_preset(name):
    try:
        raw = presets.get(name)
    except KeyError:
        raise BuildError(
            INVALID_REQUEST,
            "unknown preset %r (available: %s)" % (name, ", ".join(presets.names())),
        ) from None
    return resolve(raw)
