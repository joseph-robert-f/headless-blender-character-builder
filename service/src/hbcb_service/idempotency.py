"""Bounded idempotency-key handling and canonical request fingerprints."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Union

from shared.character_spec import BuildRequest, validate_build_request
from shared.json_contract import ContractValidationError

from .errors import IdempotencyConflict, ServiceError


MIN_IDEMPOTENCY_KEY_BYTES = 8
MAX_IDEMPOTENCY_KEY_BYTES = 128
MIN_IDEMPOTENCY_SECRET_BYTES = 32
MAX_IDEMPOTENCY_SECRET_BYTES = 128
IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]*$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class RequestFingerprint:
    request_sha256: str
    spec_sha256: str
    canonical_request: bytes

    @classmethod
    def from_request(cls, request: Union[BuildRequest, bytes, str]) -> "RequestFingerprint":
        validated = validate_build_request(request)
        return cls(
            request_sha256=validated.request_sha256,
            spec_sha256=validated.spec_sha256,
            canonical_request=validated.canonical_bytes,
        )

    def __post_init__(self) -> None:
        if SHA256_PATTERN.fullmatch(self.request_sha256) is None:
            raise ServiceError("invalid_fingerprint", "request fingerprint is invalid")
        if SHA256_PATTERN.fullmatch(self.spec_sha256) is None:
            raise ServiceError("invalid_fingerprint", "spec fingerprint is invalid")
        if not self.canonical_request or len(self.canonical_request) > 64 * 1024:
            raise ServiceError("invalid_fingerprint", "canonical request is outside policy")
        try:
            validated = validate_build_request(self.canonical_request)
        except ContractValidationError as exc:
            raise ServiceError("invalid_fingerprint", "canonical request is invalid") from exc
        if validated.canonical_bytes != self.canonical_request:
            raise ServiceError("invalid_fingerprint", "request bytes are not canonical")
        if not hmac.compare_digest(validated.request_sha256, self.request_sha256):
            raise ServiceError("invalid_fingerprint", "canonical request hash does not match")
        if not hmac.compare_digest(validated.spec_sha256, self.spec_sha256):
            raise ServiceError("invalid_fingerprint", "canonical spec hash does not match")


def validate_idempotency_key(value: str) -> bytes:
    if not isinstance(value, str):
        raise ServiceError("invalid_idempotency_key", "Idempotency-Key must be text")
    try:
        encoded = value.encode("ascii", "strict")
    except UnicodeEncodeError as exc:
        raise ServiceError(
            "invalid_idempotency_key", "Idempotency-Key must use bounded ASCII"
        ) from exc
    if not MIN_IDEMPOTENCY_KEY_BYTES <= len(encoded) <= MAX_IDEMPOTENCY_KEY_BYTES:
        raise ServiceError(
            "invalid_idempotency_key",
            f"Idempotency-Key must be {MIN_IDEMPOTENCY_KEY_BYTES}-{MAX_IDEMPOTENCY_KEY_BYTES} bytes",
        )
    if IDEMPOTENCY_KEY_PATTERN.fullmatch(value) is None:
        raise ServiceError(
            "invalid_idempotency_key", "Idempotency-Key contains forbidden characters"
        )
    return encoded


def digest_idempotency_key(value: str, secret: bytes) -> str:
    key = validate_idempotency_key(value)
    if not isinstance(secret, bytes) or not MIN_IDEMPOTENCY_SECRET_BYTES <= len(secret) <= MAX_IDEMPOTENCY_SECRET_BYTES:
        raise ServiceError("invalid_idempotency_secret", "idempotency secret is outside policy")
    return hmac.new(secret, key, hashlib.sha256).hexdigest()


def require_same_request(existing_sha256: str, supplied_sha256: str) -> None:
    if SHA256_PATTERN.fullmatch(existing_sha256) is None or SHA256_PATTERN.fullmatch(supplied_sha256) is None:
        raise ServiceError("invalid_fingerprint", "request fingerprint is invalid")
    if not hmac.compare_digest(existing_sha256, supplied_sha256):
        raise IdempotencyConflict(
            "idempotency_conflict",
            "Idempotency-Key was already used for a different request",
        )
