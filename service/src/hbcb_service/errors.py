"""Caller-safe service-domain errors.

Messages are intentionally fixed or bounded and never include credentials,
raw idempotency keys, authorization headers, or database/storage URLs.
"""

from __future__ import annotations


class ServiceError(RuntimeError):
    """Base class for stable service failures."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class AuthorizationError(ServiceError):
    pass


class ConfigurationError(ServiceError):
    pass


class IdempotencyConflict(ServiceError):
    pass


class StateConflict(ServiceError):
    pass


class StorageError(ServiceError):
    pass


class QueueError(ServiceError):
    pass


class MigrationError(ServiceError):
    pass
