"""Strict JSON decoding and deterministic canonical JSON.

This module deliberately uses only the Python standard library so it can run in
the API process, the one-shot launcher, and Blender's bundled Python.  Request
decoding rejects duplicate object keys and JavaScript-style non-finite numeric
constants before any generator code sees the value.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union


JSONScalar = Union[None, bool, str, int, float, Decimal]
JSONValue = Union[JSONScalar, Sequence["JSONValue"], Mapping[str, "JSONValue"]]

MAX_BUILD_REQUEST_BYTES = 64 * 1024
MAX_JSON_NESTING = 32
MAX_NUMBER_SIGNIFICANT_DIGITS = 256
MAX_NUMBER_ABS_EXPONENT = 1024


class ContractValidationError(ValueError):
    """A stable, caller-safe contract rejection."""

    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.path = path

    def __str__(self) -> str:
        return f"{self.code} at {self.path}: {self.message}"


def _bounded_key_label(key: Any, maximum_characters: int = 64) -> str:
    """Return a single-line bounded label safe to include in validation logs."""

    if not isinstance(key, str):
        return f"<non-string {type(key).__name__}>"
    truncated = key[:maximum_characters]
    rendered = json.dumps(truncated, ensure_ascii=True)
    if len(key) > maximum_characters:
        rendered += f"...(+{len(key) - maximum_characters} chars)"
    return rendered


def _reject_nonfinite_constant(token: str) -> None:
    raise ContractValidationError(
        "nonfinite_number", f"non-finite JSON number {token!r} is forbidden"
    )


def _bounded_decimal(token: str) -> Decimal:
    """Parse a JSON number without permitting pathological decimal expansion."""

    if len(token) > MAX_NUMBER_SIGNIFICANT_DIGITS + 32:
        raise ContractValidationError(
            "numeric_limit", "JSON number token exceeds the bounded numeric policy"
        )
    try:
        value = Decimal(token)
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ContractValidationError("invalid_number", "invalid JSON number") from exc
    _validate_decimal_bounds(value)
    return value


def _validate_decimal_bounds(value: Decimal) -> None:
    if not value.is_finite():
        raise ContractValidationError(
            "nonfinite_number", "canonical JSON forbids non-finite numbers"
        )
    sign, digits, exponent = value.as_tuple()
    del sign
    if len(digits) > MAX_NUMBER_SIGNIFICANT_DIGITS:
        raise ContractValidationError(
            "numeric_limit",
            f"JSON numbers may contain at most {MAX_NUMBER_SIGNIFICANT_DIGITS} significant digits",
        )
    if not isinstance(exponent, int) or abs(exponent) > MAX_NUMBER_ABS_EXPONENT:
        raise ContractValidationError(
            "numeric_limit",
            f"JSON numeric exponent magnitude may not exceed {MAX_NUMBER_ABS_EXPONENT}",
        )
    try:
        adjusted = value.adjusted() if value else 0
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ContractValidationError("numeric_limit", "JSON number is outside policy") from exc
    if abs(adjusted) > MAX_NUMBER_ABS_EXPONENT:
        raise ContractValidationError(
            "numeric_limit",
            f"JSON numeric magnitude may not exceed exponent {MAX_NUMBER_ABS_EXPONENT}",
        )


def bounded_decimal_value(value: Any, path: str = "$") -> Decimal:
    """Normalize a Python numeric value under the same policy as JSON decoding."""

    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ContractValidationError("expected_number", "value must be a number", path)
    if isinstance(value, int):
        if value.bit_length() > 851:
            raise ContractValidationError(
                "numeric_limit",
                f"JSON integers may contain at most {MAX_NUMBER_SIGNIFICANT_DIGITS} digits",
                path,
            )
        result = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("nonfinite_number", "number must be finite", path)
        result = Decimal(str(value))
    else:
        result = value
    try:
        _validate_decimal_bounds(result)
    except ContractValidationError as exc:
        raise ContractValidationError(exc.code, exc.message, path) from exc
    return result


def _object_without_duplicates(
    pairs: Iterable[Tuple[str, Any]],
) -> Mapping[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError(
                "duplicate_key",
                f"duplicate object key {_bounded_key_label(key)} is forbidden",
            )
        result[key] = value
    return result


def _check_nesting(value: Any, depth: int = 0) -> None:
    if depth > MAX_JSON_NESTING:
        raise ContractValidationError(
            "excessive_nesting",
            f"JSON nesting exceeds the {MAX_JSON_NESTING}-level limit",
        )
    if isinstance(value, Mapping):
        for item in value.values():
            _check_nesting(item, depth + 1)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_nesting(item, depth + 1)


def decode_json_document(
    payload: Union[str, bytes, bytearray, memoryview],
    *,
    max_bytes: Optional[int] = None,
) -> Any:
    """Decode one strict UTF-8 JSON document.

    ``max_bytes`` is evaluated against the original byte representation (or the
    UTF-8 encoding of a ``str``) before parsing.  This is the v0.1 request-size
    enforcement point and therefore runs before validation or Blender startup.
    """

    if isinstance(payload, str):
        try:
            raw = payload.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ContractValidationError(
                "invalid_unicode", "JSON contains an unpaired Unicode surrogate"
            ) from exc
    elif isinstance(payload, (bytes, bytearray, memoryview)):
        raw = bytes(payload)
    else:
        raise ContractValidationError(
            "invalid_payload_type", "JSON payload must be UTF-8 bytes or text"
        )

    if max_bytes is not None and len(raw) > max_bytes:
        raise ContractValidationError(
            "payload_too_large",
            f"JSON payload is {len(raw)} bytes; maximum is {max_bytes} bytes",
        )

    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise ContractValidationError(
            "invalid_utf8", "JSON payload must be valid UTF-8"
        ) from exc

    try:
        value = json.loads(
            text,
            parse_int=_bounded_decimal,
            parse_float=_bounded_decimal,
            parse_constant=_reject_nonfinite_constant,
            object_pairs_hook=_object_without_duplicates,
        )
    except ContractValidationError:
        raise
    except (json.JSONDecodeError, RecursionError, InvalidOperation, ValueError, OverflowError) as exc:
        raise ContractValidationError("invalid_json", "payload is not valid JSON") from exc

    _check_nesting(value)
    return value


def _canonical_number(value: Union[int, float, Decimal]) -> str:
    if isinstance(value, bool):
        raise ContractValidationError("invalid_number", "boolean is not a JSON number")
    if isinstance(value, int):
        # 851 bits bounds conversion to at most 257 decimal digits.  The exact
        # decimal-length check then preserves all permitted 256-digit integers.
        if value.bit_length() > 851:
            raise ContractValidationError(
                "numeric_limit",
                f"JSON integers may contain at most {MAX_NUMBER_SIGNIFICANT_DIGITS} digits",
            )
        rendered_int = str(value)
        if len(rendered_int.lstrip("-")) > MAX_NUMBER_SIGNIFICANT_DIGITS:
            raise ContractValidationError(
                "numeric_limit",
                f"JSON integers may contain at most {MAX_NUMBER_SIGNIFICANT_DIGITS} digits",
            )
        return rendered_int
    value = bounded_decimal_value(value)
    if value == 0:
        return "0"
    try:
        rendered = format(value, "f")
    except (InvalidOperation, ValueError) as exc:
        raise ContractValidationError("invalid_number", "invalid decimal value") from exc
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_fragment(value: Any, path: str) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except UnicodeEncodeError as exc:
            raise ContractValidationError(
                "invalid_unicode", "string contains an unpaired Unicode surrogate", path
            ) from exc
    if isinstance(value, (int, float, Decimal)):
        return _canonical_number(value)
    if isinstance(value, Mapping):
        fragments = []
        keys = list(value.keys())
        if any(not isinstance(key, str) for key in keys):
            raise ContractValidationError(
                "invalid_object_key", "JSON object keys must be strings", path
            )
        for key in sorted(keys):
            key_json = json.dumps(key, ensure_ascii=False, separators=(",", ":"))
            fragments.append(
                f"{key_json}:{_canonical_fragment(value[key], path + '.' + key)}"
            )
        return "{" + ",".join(fragments) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(
            _canonical_fragment(item, f"{path}[{index}]")
            for index, item in enumerate(value)
        ) + "]"
    raise ContractValidationError(
        "invalid_json_value", f"unsupported JSON value {type(value).__name__}", path
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON with sorted keys and normalized numbers.

    Numerically equivalent forms such as ``1``, ``1.0``, and ``1e0`` serialize
    identically.  The output intentionally contains no insignificant whitespace.
    """

    try:
        return _canonical_fragment(value, "$").encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(
            "invalid_unicode", "JSON contains an unpaired Unicode surrogate"
        ) from exc


def canonical_sha256(value: Any) -> str:
    """Hash the canonical UTF-8 JSON representation of ``value``."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def require_object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError("expected_object", "value must be an object", path)
    return value


def reject_extra_fields(
    value: Mapping[str, Any], allowed: Iterable[str], path: str
) -> None:
    allowed_set = set(allowed)
    extras = [key for key in value if key not in allowed_set]
    if extras:
        labels = sorted(_bounded_key_label(key) for key in extras[:3])
        if len(extras) > 3:
            labels.append(f"...and {len(extras) - 3} more")
        raise ContractValidationError(
            "extra_property",
            "unexpected field(s): " + ", ".join(labels),
            path,
        )


def require_fields(value: Mapping[str, Any], required: Iterable[str], path: str) -> None:
    missing = sorted(set(required) - set(value))
    if missing:
        raise ContractValidationError(
            "missing_property",
            "missing required field(s): " + ", ".join(missing),
            path,
        )
