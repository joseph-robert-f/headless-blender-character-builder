"""Canonical JSON encoding and hashing.

Reproducibility claims in the manifest are only meaningful if two machines agree
on what the "same" request is. Everything hashed by this project goes through
`canonical_json` first: sorted keys, no insignificant whitespace, and a single
normalised spelling for every number.

Stdlib only, because this module is imported both by the host CLI and by code
running inside Blender's bundled Python, which has no third-party packages.
"""

import hashlib
import json

# Floats are rounded before encoding so that values that differ only by
# accumulated binary error hash identically. Ten places is far below any
# dimension this project measures (millimetres, to two decimals at most).
_FLOAT_PLACES = 10


def normalize(value):
    """Return `value` with numbers reduced to one canonical spelling."""
    if isinstance(value, bool):
        # bool before int: bool is an int subclass and must stay true/false.
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("non-finite numbers cannot be canonicalised")
        rounded = round(value, _FLOAT_PLACES)
        if rounded == int(rounded) and abs(rounded) < 2**53:
            return int(rounded)
        # `+ 0.0` collapses -0.0 to 0.0.
        return rounded + 0.0
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    return value


def canonical_json(value):
    """Serialise `value` to the canonical string form used for hashing."""
    return json.dumps(
        normalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_of_obj(value):
    """SHA-256 of the canonical encoding of a JSON-compatible object."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_of_file(path, chunk_size=1024 * 1024):
    """Streaming SHA-256 of a file, safe for large binary artifacts."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    """Write pretty, stable JSON with a trailing newline."""
    text = json.dumps(
        normalize(value), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
