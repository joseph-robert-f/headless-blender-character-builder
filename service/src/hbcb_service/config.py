"""Bounded service configuration with secret-safe representations."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit

from .auth import validate_service_token
from .errors import ConfigurationError


NAMESPACE_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
ACCESS_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")
DATABASE_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
BUCKET_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])$")
ENDPOINT_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::[0-9]{1,5})?$")
HEX_SECRET_PATTERN = re.compile(r"^[0-9a-f]{64,256}$")
PLACEHOLDER_MARKERS = ("change-me", "replace-me", "example-secret", "placeholder")


class SecretValue:
    """A bounded secret which never renders its value through repr or str."""

    __slots__ = ("__value",)

    def __init__(self, value: str, *, minimum: int = 16, maximum: int = 2048) -> None:
        if not isinstance(value, str) or not minimum <= len(value) <= maximum:
            raise ConfigurationError("invalid_secret", "secret value is outside policy")
        lowered = value.lower()
        if any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            raise ConfigurationError("placeholder_secret", "placeholder secrets are forbidden")
        if any(ord(character) < 33 or ord(character) > 126 for character in value):
            raise ConfigurationError("invalid_secret", "secret value is outside policy")
        self.__value = value

    def reveal(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    __str__ = __repr__


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value:
        raise ConfigurationError("missing_configuration", f"required setting {name} is missing")
    return value


def _service_url(
    value: str,
    *,
    schemes: tuple[str, ...],
    label: str,
    require_username: bool,
    path_pattern: re.Pattern[str],
) -> SecretValue:
    if len(value) > 2048:
        raise ConfigurationError("invalid_service_url", f"{label} URL is outside policy")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("invalid_service_url", f"{label} URL is outside policy") from exc
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.fragment
        or parsed.query
        or (require_username and not parsed.username)
        or not parsed.password
        or path_pattern.fullmatch(parsed.path) is None
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ConfigurationError("invalid_service_url", f"{label} URL is outside policy")
    return SecretValue(value)


def _namespace(environment: Mapping[str, str]) -> str:
    namespace = _required(environment, "HBCB_DEPLOYMENT_NAMESPACE")
    if NAMESPACE_PATTERN.fullmatch(namespace) is None:
        raise ConfigurationError("invalid_namespace", "deployment namespace is outside policy")
    return namespace


def _storage_endpoint(environment: Mapping[str, str], name: str) -> str:
    endpoint = _required(environment, name)
    if ENDPOINT_PATTERN.fullmatch(endpoint) is None or "/" in endpoint or "://" in endpoint:
        raise ConfigurationError("invalid_storage_endpoint", "storage endpoint is outside policy")
    if ":" in endpoint:
        port_text = endpoint.rsplit(":", 1)[1]
        if not 1 <= int(port_text) <= 65535:
            raise ConfigurationError("invalid_storage_endpoint", "storage endpoint is outside policy")
    return endpoint


def _storage_bucket(environment: Mapping[str, str]) -> str:
    bucket = _required(environment, "HBCB_STORAGE_BUCKET")
    if BUCKET_PATTERN.fullmatch(bucket) is None or ".." in bucket:
        raise ConfigurationError("invalid_storage_bucket", "storage bucket is outside policy")
    return bucket


def _storage_secure(environment: Mapping[str, str]) -> bool:
    secure_text = _required(environment, "HBCB_STORAGE_SECURE")
    if secure_text not in ("true", "false"):
        raise ConfigurationError("invalid_storage_secure", "storage secure flag must be true or false")
    return secure_text == "true"


def _storage_credentials(environment: Mapping[str, str]) -> tuple[SecretValue, SecretValue]:
    access_key = _required(environment, "HBCB_STORAGE_ACCESS_KEY")
    if ACCESS_KEY_PATTERN.fullmatch(access_key) is None:
        raise ConfigurationError("invalid_storage_access_key", "storage access key is outside policy")
    return (
        SecretValue(access_key, minimum=3, maximum=64),
        SecretValue(_required(environment, "HBCB_STORAGE_SECRET_KEY"), minimum=32, maximum=128),
    )


@dataclass(frozen=True)
class ServiceConfig:
    deployment_namespace: str
    api_token: SecretValue
    idempotency_secret: bytes = field(repr=False)
    database_url: SecretValue
    redis_url: SecretValue
    storage_internal_endpoint: str
    storage_public_endpoint: str
    storage_access_key: SecretValue
    storage_secret_key: SecretValue
    storage_bucket: str
    storage_secure: bool
    signed_url_ttl_seconds: int

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "ServiceConfig":
        namespace = _namespace(environment)
        api_token_text = validate_service_token(_required(environment, "HBCB_API_TOKEN"))
        idempotency_text = _required(environment, "HBCB_IDEMPOTENCY_SECRET")
        if HEX_SECRET_PATTERN.fullmatch(idempotency_text) is None or len(idempotency_text) % 2:
            raise ConfigurationError("invalid_idempotency_secret", "idempotency secret is outside policy")
        idempotency_secret = bytes.fromhex(idempotency_text)
        if not 32 <= len(idempotency_secret) <= 128:
            raise ConfigurationError("invalid_idempotency_secret", "idempotency secret is outside policy")

        internal_endpoint = _storage_endpoint(environment, "HBCB_STORAGE_INTERNAL_ENDPOINT")
        public_endpoint = _storage_endpoint(environment, "HBCB_STORAGE_PUBLIC_ENDPOINT")
        access_key, secret_key = _storage_credentials(environment)
        bucket = _storage_bucket(environment)
        secure = _storage_secure(environment)
        ttl_text = _required(environment, "HBCB_SIGNED_URL_TTL_SECONDS")
        if not ttl_text.isascii() or not ttl_text.isdigit():
            raise ConfigurationError("invalid_signed_url_ttl", "signed URL TTL is outside policy")
        ttl = int(ttl_text)
        if not 30 <= ttl <= 900:
            raise ConfigurationError("invalid_signed_url_ttl", "signed URL TTL is outside policy")

        return cls(
            deployment_namespace=namespace,
            api_token=SecretValue(api_token_text, minimum=43, maximum=256),
            idempotency_secret=idempotency_secret,
            database_url=_service_url(
                _required(environment, "HBCB_DATABASE_URL"),
                schemes=("postgresql",),
                label="database",
                require_username=True,
                path_pattern=re.compile(r"^/[A-Za-z0-9_-]{1,63}$"),
            ),
            redis_url=_service_url(
                _required(environment, "HBCB_REDIS_URL"),
                schemes=("redis", "rediss"),
                label="Redis",
                require_username=False,
                path_pattern=re.compile(r"^/(?:[0-9]|1[0-5])$"),
            ),
            storage_internal_endpoint=internal_endpoint,
            storage_public_endpoint=public_endpoint,
            storage_access_key=access_key,
            storage_secret_key=secret_key,
            storage_bucket=bucket,
            storage_secure=secure,
            signed_url_ttl_seconds=ttl,
        )

    def redacted(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "deployment_namespace": self.deployment_namespace,
                "storage_bucket": self.storage_bucket,
                "storage_internal_endpoint": self.storage_internal_endpoint,
                "storage_public_endpoint": self.storage_public_endpoint,
                "storage_secure": self.storage_secure,
                "signed_url_ttl_seconds": self.signed_url_ttl_seconds,
                "api_token": "<redacted>",
                "database_url": "<redacted>",
                "idempotency_secret": "<redacted>",
                "redis_url": "<redacted>",
                "storage_access_key": "<redacted>",
                "storage_secret_key": "<redacted>",
            }
        )


@dataclass(frozen=True)
class WorkerConfig:
    deployment_namespace: str
    database_url: SecretValue
    redis_url: SecretValue
    storage_internal_endpoint: str
    storage_access_key: SecretValue
    storage_secret_key: SecretValue
    storage_bucket: str
    storage_secure: bool

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "WorkerConfig":
        access_key, secret_key = _storage_credentials(environment)
        return cls(
            deployment_namespace=_namespace(environment),
            database_url=_service_url(
                _required(environment, "HBCB_DATABASE_URL"),
                schemes=("postgresql",),
                label="database",
                require_username=True,
                path_pattern=re.compile(r"^/[A-Za-z0-9_-]{1,63}$"),
            ),
            redis_url=_service_url(
                _required(environment, "HBCB_REDIS_URL"),
                schemes=("redis", "rediss"),
                label="Redis",
                require_username=False,
                path_pattern=re.compile(r"^/(?:[0-9]|1[0-5])$"),
            ),
            storage_internal_endpoint=_storage_endpoint(
                environment, "HBCB_STORAGE_INTERNAL_ENDPOINT"
            ),
            storage_access_key=access_key,
            storage_secret_key=secret_key,
            storage_bucket=_storage_bucket(environment),
            storage_secure=_storage_secure(environment),
        )


@dataclass(frozen=True)
class MigratorConfig:
    deployment_namespace: str
    database_url: SecretValue

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "MigratorConfig":
        return cls(
            deployment_namespace=_namespace(environment),
            database_url=_service_url(
                _required(environment, "HBCB_DATABASE_URL"),
                schemes=("postgresql",),
                label="database",
                require_username=True,
                path_pattern=re.compile(r"^/[A-Za-z0-9_-]{1,63}$"),
            ),
        )


def _database_role(environment: Mapping[str, str], name: str) -> str:
    role = _required(environment, name)
    if DATABASE_ROLE_PATTERN.fullmatch(role) is None:
        raise ConfigurationError("invalid_database_role", "database role is outside policy")
    return role


@dataclass(frozen=True)
class DatabaseInitializationConfig:
    """One-shot local database bootstrap settings.

    The initializer alone receives the admin URL and role passwords.  API and
    worker processes receive only their own already-scoped connection URLs.
    """

    deployment_namespace: str
    database_name: str
    admin_database_url: SecretValue
    migrator_database_url: SecretValue
    admin_username: str
    api_username: str
    api_password: SecretValue
    worker_username: str
    worker_password: SecretValue
    migrator_username: str
    migrator_password: SecretValue

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str]
    ) -> "DatabaseInitializationConfig":
        database_name = _required(environment, "POSTGRES_DB")
        if DATABASE_NAME_PATTERN.fullmatch(database_name) is None:
            raise ConfigurationError("invalid_database_name", "database name is outside policy")
        admin_value = _required(environment, "HBCB_DATABASE_ADMIN_URL")
        migrator_value = _required(environment, "HBCB_DATABASE_MIGRATOR_URL")
        admin_url = _service_url(
            admin_value,
            schemes=("postgresql",),
            label="admin database",
            require_username=True,
            path_pattern=re.compile(r"^/[A-Za-z0-9_-]{1,63}$"),
        )
        migrator_url = _service_url(
            migrator_value,
            schemes=("postgresql",),
            label="migrator database",
            require_username=True,
            path_pattern=re.compile(r"^/[A-Za-z0-9_-]{1,63}$"),
        )
        admin_parts = urlsplit(admin_value)
        migrator_parts = urlsplit(migrator_value)
        admin_username = admin_parts.username or ""
        api_username = _database_role(environment, "HBCB_DATABASE_API_USER")
        worker_username = _database_role(environment, "HBCB_DATABASE_WORKER_USER")
        migrator_username = _database_role(environment, "HBCB_DATABASE_MIGRATOR_USER")
        if DATABASE_ROLE_PATTERN.fullmatch(admin_username) is None:
            raise ConfigurationError("invalid_database_role", "database role is outside policy")
        if (
            admin_parts.hostname,
            admin_parts.port,
            admin_parts.path,
        ) != (
            migrator_parts.hostname,
            migrator_parts.port,
            migrator_parts.path,
        ):
            raise ConfigurationError(
                "database_target_mismatch", "database initialization URLs target different databases"
            )
        if admin_parts.path != "/" + database_name:
            raise ConfigurationError(
                "database_target_mismatch", "database name does not match initialization URL"
            )
        if migrator_parts.username != migrator_username:
            raise ConfigurationError(
                "database_role_mismatch", "migrator URL does not use the configured role"
            )
        if len({admin_username, api_username, worker_username, migrator_username}) != 4:
            raise ConfigurationError(
                "database_role_overlap", "database initialization roles must be distinct"
            )
        return cls(
            deployment_namespace=_namespace(environment),
            database_name=database_name,
            admin_database_url=admin_url,
            migrator_database_url=migrator_url,
            admin_username=admin_username,
            api_username=api_username,
            api_password=SecretValue(
                _required(environment, "HBCB_DATABASE_API_PASSWORD"),
                minimum=32,
                maximum=128,
            ),
            worker_username=worker_username,
            worker_password=SecretValue(
                _required(environment, "HBCB_DATABASE_WORKER_PASSWORD"),
                minimum=32,
                maximum=128,
            ),
            migrator_username=migrator_username,
            migrator_password=SecretValue(
                _required(environment, "HBCB_DATABASE_MIGRATOR_PASSWORD"),
                minimum=32,
                maximum=128,
            ),
        )

    def redacted(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "deployment_namespace": self.deployment_namespace,
                "database_name": self.database_name,
                "admin_username": self.admin_username,
                "api_username": self.api_username,
                "worker_username": self.worker_username,
                "migrator_username": self.migrator_username,
                "admin_database_url": "<redacted>",
                "migrator_database_url": "<redacted>",
                "api_password": "<redacted>",
                "worker_password": "<redacted>",
                "migrator_password": "<redacted>",
            }
        )
