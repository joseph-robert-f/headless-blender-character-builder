#!/usr/bin/env python3
"""Render and validate the merged G8 VPS Compose model without secrets.

Only the Python standard library is used.  The rendered model can contain the
temporary fixture credentials, so subprocess output is parsed in memory and
is never echoed, including on failure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = ROOT / "compose.yaml"
VPS_COMPOSE = ROOT / "deploy" / "vps" / "compose.yaml"

PRODUCTION_SERVICES = frozenset(
    {"postgres", "redis", "database-init", "api", "worker", "maintenance", "caddy"}
)
LOCAL_SERVICES = frozenset({"minio", "minio-init", "service-test"})
HARDENED_SERVICES = frozenset(
    {"database-init", "api", "worker", "maintenance", "caddy"}
)
LOCAL_PROFILES = frozenset({"local-fixture", "local-test"})
LOCAL_MINIO_SERVICES = frozenset({"minio", "minio-init"})
NONZERO_DIGEST = re.compile(r"^[0-9a-f]{64}$")
LOG_SIZE = re.compile(r"^([1-9][0-9]{0,2})([kmg])$")
MAX_LOG_BYTES = 100 * 1024 * 1024


class GateFailure(RuntimeError):
    """A bounded, nonsecret failure suitable for terminal output."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateFailure(message)


def _write_env(path: Path, values: Mapping[str, str]) -> None:
    for name, value in values.items():
        if (
            re.fullmatch(r"[A-Z][A-Z0-9_]*", name) is None
            or not value
            or "\n" in value
            or "\r" in value
        ):
            raise GateFailure("temporary environment fixture is invalid")
    payload = "".join(f"{name}={value}\n" for name, value in values.items())
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)


def _fixture_environment(root: Path) -> Path:
    secrets = root / "secrets"
    state = root / "state"
    secrets.mkdir(mode=0o700)
    (state / "caddy-data").mkdir(parents=True)
    (state / "caddy-config").mkdir(parents=True)

    digest = {
        "api": "1" * 64,
        "worker": "2" * 64,
        "caddy": "3" * 64,
        "builder": "4" * 64,
    }
    values = {
        "HBCB_DEPLOYMENT_NAMESPACE": "production",
        "HBCB_API_TOKEN": "a" * 64,
        "HBCB_IDEMPOTENCY_SECRET": "b" * 64,
        "POSTGRES_DB": "hbcb",
        "POSTGRES_USER": "hbcb_admin",
        "POSTGRES_PASSWORD": "c" * 64,
        "HBCB_DATABASE_API_USER": "hbcb_api",
        "HBCB_DATABASE_API_PASSWORD": "d" * 64,
        "HBCB_DATABASE_WORKER_USER": "hbcb_worker",
        "HBCB_DATABASE_WORKER_PASSWORD": "e" * 64,
        "HBCB_DATABASE_MAINTENANCE_USER": "hbcb_maintenance",
        "HBCB_DATABASE_MAINTENANCE_PASSWORD": "f" * 64,
        "HBCB_DATABASE_MIGRATOR_USER": "hbcb_migrator",
        "HBCB_DATABASE_MIGRATOR_PASSWORD": "0a" * 32,
        "REDIS_PASSWORD": "1a" * 32,
        "MINIO_ROOT_USER": "disabled_root",
        "MINIO_ROOT_PASSWORD": "1b" * 32,
        "HBCB_STORAGE_API_ACCESS_KEY": "disabled_api",
        "HBCB_STORAGE_API_SECRET_KEY": "1c" * 32,
        "HBCB_STORAGE_WORKER_ACCESS_KEY": "disabled_worker",
        "HBCB_STORAGE_WORKER_SECRET_KEY": "1d" * 32,
        "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY": "disabled_maintenance",
        "HBCB_STORAGE_MAINTENANCE_SECRET_KEY": "1e" * 32,
        "HBCB_STORAGE_BUCKET": "hbcb-artifacts",
        "HBCB_STORAGE_INTERNAL_ENDPOINT": "s3-private.example.invalid:443",
        "HBCB_STORAGE_PUBLIC_ENDPOINT": "artifacts.example.invalid:443",
        "HBCB_STORAGE_INTERNAL_SECURE": "true",
        "HBCB_STORAGE_PUBLIC_SECURE": "true",
        "HBCB_STORAGE_REGION": "us-east-1",
        "HBCB_SIGNED_URL_TTL_SECONDS": "300",
        "HBCB_API_IMAGE": f"ghcr.io/example/hbcb-api@sha256:{digest['api']}",
        "HBCB_WORKER_IMAGE": (
            f"ghcr.io/example/hbcb-worker@sha256:{digest['worker']}"
        ),
        "HBCB_CADDY_IMAGE": f"caddy:2.10.2@sha256:{digest['caddy']}",
        "HBCB_BUILDER_IMAGE": (
            f"ghcr.io/example/hbcb-builder@sha256:{digest['builder']}"
        ),
        "HBCB_BUILDER_IMAGE_REFERENCE": (
            f"ghcr.io/example/hbcb-builder@sha256:{digest['builder']}"
        ),
        "HBCB_BUILDER_IMAGE_ID": f"sha256:{digest['builder']}",
        "HBCB_VPS_SECRETS_DIR": str(secrets),
        "HBCB_VPS_STATE_DIR": str(state),
        "HBCB_STORAGE_NETWORK": "hbcb-storage-private",
        "HBCB_API_DOMAIN": "api.example.invalid",
        "HBCB_ACME_EMAIL": "operator@example.invalid",
    }

    database_admin_url = (
        "postgresql://hbcb_admin:" + values["POSTGRES_PASSWORD"] + "@postgres:5432/hbcb"
    )
    database_migrator_url = (
        "postgresql://hbcb_migrator:"
        + values["HBCB_DATABASE_MIGRATOR_PASSWORD"]
        + "@postgres:5432/hbcb"
    )
    redis_url = "redis://:" + values["REDIS_PASSWORD"] + "@redis:6379/0"
    _write_env(
        secrets / "postgres.env",
        {
            "POSTGRES_DB": values["POSTGRES_DB"],
            "POSTGRES_USER": values["POSTGRES_USER"],
            "POSTGRES_PASSWORD": values["POSTGRES_PASSWORD"],
        },
    )
    _write_env(
        secrets / "redis.env",
        {"REDIS_PASSWORD": values["REDIS_PASSWORD"]},
    )
    _write_env(
        secrets / "database-init.env",
        {
            "HBCB_DATABASE_ADMIN_URL": database_admin_url,
            "HBCB_DATABASE_MIGRATOR_URL": database_migrator_url,
            "HBCB_DATABASE_API_USER": values["HBCB_DATABASE_API_USER"],
            "HBCB_DATABASE_API_PASSWORD": values["HBCB_DATABASE_API_PASSWORD"],
            "HBCB_DATABASE_WORKER_USER": values["HBCB_DATABASE_WORKER_USER"],
            "HBCB_DATABASE_WORKER_PASSWORD": values[
                "HBCB_DATABASE_WORKER_PASSWORD"
            ],
            "HBCB_DATABASE_MAINTENANCE_USER": values[
                "HBCB_DATABASE_MAINTENANCE_USER"
            ],
            "HBCB_DATABASE_MAINTENANCE_PASSWORD": values[
                "HBCB_DATABASE_MAINTENANCE_PASSWORD"
            ],
            "HBCB_DATABASE_MIGRATOR_USER": values[
                "HBCB_DATABASE_MIGRATOR_USER"
            ],
            "HBCB_DATABASE_MIGRATOR_PASSWORD": values[
                "HBCB_DATABASE_MIGRATOR_PASSWORD"
            ],
        },
    )
    _write_env(
        secrets / "api.env",
        {
            "HBCB_API_TOKEN": values["HBCB_API_TOKEN"],
            "HBCB_IDEMPOTENCY_SECRET": values["HBCB_IDEMPOTENCY_SECRET"],
            "HBCB_DATABASE_URL": (
                "postgresql://hbcb_api:"
                + values["HBCB_DATABASE_API_PASSWORD"]
                + "@postgres:5432/hbcb"
            ),
            "HBCB_REDIS_URL": redis_url,
            "HBCB_STORAGE_ACCESS_KEY": values["HBCB_STORAGE_API_ACCESS_KEY"],
            "HBCB_STORAGE_SECRET_KEY": values["HBCB_STORAGE_API_SECRET_KEY"],
        },
    )
    _write_env(
        secrets / "worker.env",
        {
            "HBCB_DATABASE_URL": (
                "postgresql://hbcb_worker:"
                + values["HBCB_DATABASE_WORKER_PASSWORD"]
                + "@postgres:5432/hbcb"
            ),
            "HBCB_REDIS_URL": redis_url,
            "HBCB_STORAGE_ACCESS_KEY": values["HBCB_STORAGE_WORKER_ACCESS_KEY"],
            "HBCB_STORAGE_SECRET_KEY": values["HBCB_STORAGE_WORKER_SECRET_KEY"],
        },
    )
    _write_env(
        secrets / "maintenance.env",
        {
            "HBCB_DATABASE_URL": (
                "postgresql://hbcb_maintenance:"
                + values["HBCB_DATABASE_MAINTENANCE_PASSWORD"]
                + "@postgres:5432/hbcb"
            ),
            "HBCB_REDIS_URL": redis_url,
            "HBCB_STORAGE_ACCESS_KEY": values[
                "HBCB_STORAGE_MAINTENANCE_ACCESS_KEY"
            ],
            "HBCB_STORAGE_SECRET_KEY": values[
                "HBCB_STORAGE_MAINTENANCE_SECRET_KEY"
            ],
        },
    )
    environment_file = root / "render.env"
    _write_env(environment_file, values)
    return environment_file


def _compose_command() -> list[str]:
    override = os.environ.get("HBCB_COMPOSE_BIN")
    if override:
        executable = Path(override)
        if not executable.is_file():
            raise GateFailure("configured Compose binary is unavailable")
        return [str(executable)]
    if shutil.which("docker") is None:
        raise GateFailure("Docker Compose is unavailable")
    return ["docker", "compose"]


def _render(environment_file: Path) -> Mapping[str, Any]:
    command = _compose_command() + [
        "--project-directory",
        str(ROOT),
        "--env-file",
        str(environment_file),
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(VPS_COMPOSE),
        "--profile",
        "*",
        "config",
        "--format",
        "json",
    ]
    process_environment = {
        name: value
        for name, value in os.environ.items()
        if name in {"PATH", "HOME", "DOCKER_CONFIG", "TMPDIR"}
    }
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=process_environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateFailure(
            f"Compose rendering could not complete ({type(exc).__name__})"
        ) from None
    if completed.returncode != 0:
        raise GateFailure("Compose rendering failed")
    try:
        document = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        raise GateFailure("Compose rendering did not return valid JSON") from None
    if not isinstance(document, dict):
        raise GateFailure("Compose rendering returned an invalid model")
    return document


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise GateFailure(f"{label} is missing or invalid")
    return value


def _string_set(value: object, label: str) -> set[str]:
    if isinstance(value, dict):
        candidates = value.keys()
    elif isinstance(value, list):
        candidates = value
    else:
        raise GateFailure(f"{label} is missing or invalid")
    if not all(isinstance(item, str) and item for item in candidates):
        raise GateFailure(f"{label} is invalid")
    return set(candidates)


def _assert_digest_image(service_name: str, service: Mapping[str, Any]) -> None:
    image = service.get("image")
    if not isinstance(image, str):
        raise GateFailure(f"{service_name} image is missing")
    prefix, separator, digest = image.rpartition("@sha256:")
    require(bool(separator) and bool(prefix), f"{service_name} image is not digest-pinned")
    require(
        NONZERO_DIGEST.fullmatch(digest) is not None and set(digest) != {"0"},
        f"{service_name} image digest is invalid",
    )


def _log_bytes(value: str) -> int:
    matched = LOG_SIZE.fullmatch(value)
    if matched is None:
        raise GateFailure("production log size is invalid")
    amount = int(matched.group(1))
    multiplier = {"k": 1024, "m": 1024**2, "g": 1024**3}[matched.group(2)]
    return amount * multiplier


def _assert_bounded_logging(service_name: str, service: Mapping[str, Any]) -> None:
    logging = _mapping(service.get("logging"), f"{service_name} logging")
    require(logging.get("driver") == "json-file", f"{service_name} logging is not JSON")
    options = _mapping(logging.get("options"), f"{service_name} logging options")
    max_size = options.get("max-size")
    max_file = options.get("max-file")
    require(isinstance(max_size, str), f"{service_name} log size is missing")
    require(
        0 < _log_bytes(max_size) <= MAX_LOG_BYTES,
        f"{service_name} log size is not bounded",
    )
    require(
        isinstance(max_file, str)
        and max_file.isascii()
        and max_file.isdigit()
        and 1 <= int(max_file) <= 10,
        f"{service_name} log file count is not bounded",
    )


def _assert_hardened(service_name: str, service: Mapping[str, Any]) -> None:
    require(service.get("init") is True, f"{service_name} init is not enabled")
    require(service.get("read_only") is True, f"{service_name} root is writable")
    require(service.get("privileged") is not True, f"{service_name} is privileged")
    require(
        "ALL" in _string_set(service.get("cap_drop"), f"{service_name} cap_drop"),
        f"{service_name} does not drop all capabilities",
    )
    security = _string_set(service.get("security_opt"), f"{service_name} security_opt")
    require(
        "no-new-privileges:true" in security,
        f"{service_name} permits privilege escalation",
    )
    added = _string_set(service.get("cap_add"), f"{service_name} cap_add") if service.get("cap_add") else set()
    if service_name == "caddy":
        require(
            added == {"NET_BIND_SERVICE"},
            "Caddy must retain only its image-required bind capability",
        )
    else:
        require(not added, f"{service_name} adds capabilities")
    require(not service.get("devices"), f"{service_name} exposes devices")
    require(service.get("network_mode") != "host", f"{service_name} uses host networking")
    require(service.get("pid") != "host", f"{service_name} uses the host PID namespace")

    user = service.get("user")
    require(isinstance(user, str) and user, f"{service_name} user is not pinned")
    require(user.split(":", 1)[0] != "0", f"{service_name} runs as root")
    pids_limit = service.get("pids_limit")
    mem_limit = service.get("mem_limit")
    cpus = service.get("cpus")
    if isinstance(mem_limit, str) and mem_limit.isascii() and mem_limit.isdigit():
        mem_limit = int(mem_limit)
    require(
        isinstance(pids_limit, int) and 1 <= pids_limit <= 1024,
        f"{service_name} PID limit is invalid",
    )
    require(
        isinstance(mem_limit, int) and 1 <= mem_limit <= 8 * 1024**3,
        f"{service_name} memory limit is invalid",
    )
    require(
        isinstance(cpus, (int, float)) and not isinstance(cpus, bool) and 0 < cpus <= 8,
        f"{service_name} CPU limit is invalid",
    )
    require(bool(service.get("tmpfs")), f"{service_name} has no bounded temporary filesystem")


def validate(document: Mapping[str, Any]) -> None:
    services = _mapping(document.get("services"), "services")
    service_names = set(services)
    require(
        service_names == PRODUCTION_SERVICES | LOCAL_SERVICES,
        "merged service set is outside the reviewed policy",
    )

    for name in LOCAL_SERVICES:
        service = _mapping(services[name], f"{name} service")
        profiles = _string_set(service.get("profiles"), f"{name} profiles")
        require(
            profiles and profiles <= LOCAL_PROFILES,
            f"{name} is not isolated behind a local-only profile",
        )
    for name in LOCAL_MINIO_SERVICES:
        profiles = _string_set(services[name].get("profiles"), f"{name} profiles")
        require(profiles == {"local-fixture"}, f"{name} local fixture profile is invalid")

    for name in PRODUCTION_SERVICES:
        service = _mapping(services[name], f"{name} service")
        require("build" not in service, f"{name} retains a production build directive")
        _assert_digest_image(name, service)
        _assert_bounded_logging(name, service)
        profiles = service.get("profiles", [])
        if profiles:
            require(
                not (_string_set(profiles, f"{name} profiles") & LOCAL_PROFILES),
                f"{name} is assigned a local-only profile",
            )

    for name, raw_service in services.items():
        service = _mapping(raw_service, f"{name} service")
        has_ports = bool(service.get("ports"))
        require(has_ports == (name == "caddy"), "only Caddy may publish host ports")

    worker = _mapping(services["worker"], "worker service")
    worker_networks = _string_set(worker.get("networks"), "worker networks")
    require(
        worker_networks == {"db", "queue", "storage-private"},
        "worker networks are outside the private allowlist",
    )
    deploy = _mapping(worker.get("deploy"), "worker deploy policy")
    require(deploy.get("replicas") == 1, "worker replica count must be exactly one")

    runtime_database_roles = set()
    runtime_storage_roles = set()
    for name in ("api", "worker", "maintenance"):
        runtime_environment = _mapping(
            services[name].get("environment"), f"{name} environment"
        )
        database_url = runtime_environment.get("HBCB_DATABASE_URL")
        storage_role = runtime_environment.get("HBCB_STORAGE_ACCESS_KEY")
        require(
            isinstance(database_url, str) and database_url,
            f"{name} database role is missing",
        )
        require(
            isinstance(storage_role, str) and storage_role,
            f"{name} storage role is missing",
        )
        database_role = urlsplit(database_url).username
        require(bool(database_role), f"{name} database role is invalid")
        runtime_database_roles.add(database_role)
        runtime_storage_roles.add(storage_role)
    require(
        len(runtime_database_roles) == 3,
        "API, worker, and maintenance database roles are not distinct",
    )
    require(
        len(runtime_storage_roles) == 3,
        "API, worker, and maintenance storage roles are not distinct",
    )

    api = _mapping(services["api"], "api service")
    api_networks = _string_set(api.get("networks"), "API networks")
    require(
        not ({"edge", "default"} & api_networks),
        "API is attached to a public edge network",
    )
    api_healthcheck = _mapping(api.get("healthcheck"), "API healthcheck")
    api_health_test = api_healthcheck.get("test")
    require(
        isinstance(api_health_test, list)
        and all(isinstance(value, str) for value in api_health_test)
        and api_health_test[:1] == ["CMD"],
        "API healthcheck is not an exec-form command",
    )
    rendered_api_health = " ".join(api_health_test)
    require(
        "/readyz" in rendered_api_health
        and "/healthz" not in rendered_api_health
        and "Authorization" in rendered_api_health
        and "HBCB_API_TOKEN" in rendered_api_health,
        "API healthcheck does not use authenticated private readiness",
    )

    networks = _mapping(document.get("networks"), "networks")
    storage_private = _mapping(networks.get("storage-private"), "storage-private network")
    require(storage_private.get("external") is True, "storage-private is not external")

    for name in HARDENED_SERVICES:
        _assert_hardened(name, _mapping(services[name], f"{name} service"))

    for name in PRODUCTION_SERVICES:
        service = _mapping(services[name], f"{name} service")
        dependencies = service.get("depends_on", {})
        if dependencies:
            dependency_names = _string_set(dependencies, f"{name} dependencies")
            require(
                not (dependency_names & LOCAL_MINIO_SERVICES),
                f"{name} depends on the local MinIO fixture",
            )
        service_networks = service.get("networks", {})
        if service_networks:
            network_names = _string_set(service_networks, f"{name} networks")
            require(
                "storage-local" not in network_names,
                f"{name} uses the local MinIO network",
            )

    try:
        caddyfile = (ROOT / "deploy" / "vps" / "Caddyfile").read_text(
            encoding="utf-8"
        )
    except OSError as exc:
        raise GateFailure("Caddyfile is unavailable") from exc
    require("/healthz /v1/*" in caddyfile, "Caddy public route allowlist is missing")
    require("/readyz" not in caddyfile, "Caddy exposes private readiness")
    require(
        re.search(r"(?m)^\s*log(?:\s|$)", caddyfile) is None,
        "Caddy access logging could disclose signed queries",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hbcb-g8-static-") as temporary:
        environment_file = _fixture_environment(Path(temporary))
        validate(_render(environment_file))
    print(
        json.dumps(
            {
                "gate": "G8_STATIC_GATE",
                "production_services": len(PRODUCTION_SERVICES),
                "result": "PASS",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def cli() -> int:
    try:
        main()
    except GateFailure as exc:
        print(f"G8_STATIC_GATE: FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"G8_STATIC_GATE: FAIL: unexpected {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
