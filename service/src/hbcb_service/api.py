"""Narrow FastAPI v1 surface over the durable service repository."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional, Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from shared.json_contract import ContractValidationError, MAX_BUILD_REQUEST_BYTES

from .auth import authorize_bearer
from .errors import (
    AuthorizationError,
    IdempotencyConflict,
    ServiceError,
    StateConflict,
    StorageError,
)
from .models import REQUIRED_PUBLISHED_ARTIFACTS, ArtifactRecord, BuildRecord, BuildStatus
from .state import BuildReservation
from .storage import ArtifactStorage
from .structured_log import StructuredLogger


class ApiRepository(Protocol):
    def submit(self, request: bytes, idempotency_key: Optional[str]) -> BuildReservation:
        ...

    def get_build(self, build_id: UUID) -> BuildRecord:
        ...

    def request_cancel(self, build_id: UUID, expected_version: int) -> BuildRecord:
        ...

    def artifacts_for(self, build_id: UUID) -> Mapping[str, ArtifactRecord]:
        ...


ReadinessProbe = Callable[[], bool]


@dataclass(frozen=True)
class ApiProblem(Exception):
    status_code: int
    code: str
    message: str
    path: Optional[str] = None
    authenticate: bool = False


MALFORMED_JSON_CODES = frozenset(
    {
        "duplicate_key",
        "excessive_nesting",
        "invalid_json",
        "invalid_number",
        "invalid_payload_type",
        "invalid_utf8",
        "invalid_unicode",
        "nonfinite_number",
        "numeric_limit",
    }
)


def _request_id(request: Request) -> UUID:
    candidate = getattr(request.state, "request_id", None)
    return candidate if isinstance(candidate, UUID) else uuid4()


def _timestamp(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _build_document(build: BuildRecord) -> dict[str, object]:
    return {
        "build_id": str(build.build_id),
        "request_sha256": build.request_sha256,
        "spec_sha256": build.spec_sha256,
        "status": build.status.value,
        "state_version": build.state_version,
        "max_attempts": build.max_attempts,
        "cancel_requested_at": _timestamp(build.cancel_requested_at),
        "terminal_code": build.terminal_code,
        "manifest_sha256": build.manifest_sha256,
        "manifest_bytes": build.manifest_bytes,
        "created_at": _timestamp(build.created_at),
        "updated_at": _timestamp(build.updated_at),
        "finished_at": _timestamp(build.finished_at),
        "published_at": _timestamp(build.published_at),
        "artifacts_url": (
            f"/v1/builds/{build.build_id}/artifacts"
            if build.status is BuildStatus.SUCCEEDED
            else None
        ),
    }


def _error_response(request: Request, problem: ApiProblem) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if problem.authenticate else None
    return JSONResponse(
        status_code=problem.status_code,
        headers=headers,
        content={
            "error": {
                "code": problem.code,
                "message": problem.message,
                "path": problem.path,
                "request_id": str(_request_id(request)),
            }
        },
    )


def _raw_header_values(request: Request, name: bytes) -> list[bytes]:
    return [value for key, value in request.scope.get("headers", ()) if key.lower() == name]


def _authorize(request: Request, configured_token: str) -> None:
    values = _raw_header_values(request, b"authorization")
    if len(values) != 1:
        raise ApiProblem(
            401,
            "unauthorized",
            "Bearer authorization is required.",
            authenticate=True,
        )
    try:
        authorize_bearer(values[0], configured_token)
    except AuthorizationError as exc:
        raise ApiProblem(
            401,
            "unauthorized",
            "Bearer authorization is required.",
            authenticate=True,
        ) from exc


def _json_media_type(request: Request) -> None:
    encodings = _raw_header_values(request, b"content-encoding")
    if len(encodings) > 1:
        raise ApiProblem(415, "unsupported_encoding", "Request content encoding is unsupported.")
    if encodings:
        try:
            encoding = encodings[0].decode("ascii", "strict").strip().lower()
        except UnicodeDecodeError as exc:
            raise ApiProblem(415, "unsupported_encoding", "Request content encoding is unsupported.") from exc
        if encoding != "identity":
            raise ApiProblem(415, "unsupported_encoding", "Request content encoding is unsupported.")
    values = _raw_header_values(request, b"content-type")
    if len(values) != 1:
        raise ApiProblem(415, "unsupported_media_type", "Content-Type must be application/json.")
    try:
        supplied = values[0].decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise ApiProblem(415, "unsupported_media_type", "Content-Type must be application/json.") from exc
    parts = [part.strip().lower() for part in supplied.split(";")]
    if not parts or parts[0] != "application/json":
        raise ApiProblem(415, "unsupported_media_type", "Content-Type must be application/json.")
    parameters = parts[1:]
    if any(parameter != "charset=utf-8" for parameter in parameters) or len(parameters) > 1:
        raise ApiProblem(415, "unsupported_media_type", "Content-Type must be application/json.")


async def _bounded_body(request: Request, maximum: int) -> bytes:
    lengths = _raw_header_values(request, b"content-length")
    if len(lengths) > 1:
        raise ApiProblem(400, "invalid_content_length", "Content-Length is malformed.")
    if lengths:
        try:
            text = lengths[0].decode("ascii", "strict")
            if not text.isdigit():
                raise ValueError
            declared = int(text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiProblem(400, "invalid_content_length", "Content-Length is malformed.") from exc
        if declared > maximum:
            raise ApiProblem(413, "payload_too_large", "BuildRequest exceeds 65536 bytes.")
    payload = bytearray()
    async for chunk in request.stream():
        payload.extend(chunk)
        if len(payload) > maximum:
            raise ApiProblem(413, "payload_too_large", "BuildRequest exceeds 65536 bytes.")
    return bytes(payload)


async def _require_empty_body(request: Request) -> None:
    lengths = _raw_header_values(request, b"content-length")
    if len(lengths) > 1:
        raise ApiProblem(400, "invalid_content_length", "Content-Length is malformed.")
    if lengths:
        try:
            text = lengths[0].decode("ascii", "strict")
            if not text.isdigit():
                raise ValueError
            if int(text) != 0:
                raise ApiProblem(400, "unexpected_body", "Cancellation request body must be empty.")
        except ApiProblem:
            raise
        except (UnicodeDecodeError, ValueError) as exc:
            raise ApiProblem(400, "invalid_content_length", "Content-Length is malformed.") from exc
    async for chunk in request.stream():
        if chunk:
            raise ApiProblem(400, "unexpected_body", "Cancellation request body must be empty.")


def _idempotency_key(request: Request) -> Optional[str]:
    values = _raw_header_values(request, b"idempotency-key")
    if not values:
        return None
    if len(values) != 1:
        raise ApiProblem(400, "invalid_idempotency_key", "Idempotency-Key is malformed.")
    try:
        return values[0].decode("ascii", "strict")
    except UnicodeDecodeError as exc:
        raise ApiProblem(400, "invalid_idempotency_key", "Idempotency-Key is malformed.") from exc


def create_app(
    *,
    repository: ApiRepository,
    storage: ArtifactStorage,
    configured_token: str,
    signed_url_ttl_seconds: int,
    readiness: ReadinessProbe,
    logger: Optional[StructuredLogger] = None,
) -> FastAPI:
    if not callable(readiness):
        raise ValueError("readiness probe is invalid")
    log = logger or StructuredLogger()
    app = FastAPI(
        title="Headless Blender Character Builder",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def response_policy(request: Request, call_next: Callable[..., Any]) -> JSONResponse:
        request.state.request_id = uuid4()
        if request.url.path == "/readyz" or request.url.path.startswith("/v1/"):
            try:
                _authorize(request, configured_token)
            except ApiProblem as problem:
                response = _error_response(request, problem)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = str(request.state.request_id)
        return response

    @app.exception_handler(ApiProblem)
    async def api_problem_handler(request: Request, exc: ApiProblem) -> JSONResponse:
        return _error_response(request, exc)

    @app.exception_handler(ContractValidationError)
    async def contract_error_handler(
        request: Request, exc: ContractValidationError
    ) -> JSONResponse:
        status = 400 if exc.code in MALFORMED_JSON_CODES else 422
        return _error_response(
            request,
            ApiProblem(status, exc.code, exc.message, exc.path),
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del exc
        return _error_response(
            request,
            ApiProblem(422, "invalid_path_parameter", "Request path parameter is invalid."),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            problem = ApiProblem(404, "route_not_found", "Route does not exist.")
        elif exc.status_code == 405:
            problem = ApiProblem(405, "method_not_allowed", "Method is not allowed for this route.")
        else:
            problem = ApiProblem(exc.status_code, "http_error", "HTTP request could not be completed.")
        return _error_response(request, problem)

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        if isinstance(exc, IdempotencyConflict):
            problem = ApiProblem(409, "idempotency_conflict", exc.message)
        elif isinstance(exc, StorageError):
            problem = ApiProblem(503, "artifact_service_unavailable", "Artifact service is unavailable.")
        elif isinstance(exc, StateConflict):
            if exc.code in ("build_not_found", "attempt_not_found"):
                problem = ApiProblem(404, "build_not_found", "Build does not exist.")
            elif exc.code in ("database_unavailable",):
                problem = ApiProblem(503, "service_unavailable", "Service dependency is unavailable.")
            else:
                problem = ApiProblem(409, exc.code, exc.message)
        elif exc.code == "invalid_idempotency_key":
            problem = ApiProblem(400, "invalid_idempotency_key", "Idempotency-Key is malformed.")
        else:
            problem = ApiProblem(500, "internal_error", "Internal service error.")
        return _error_response(request, problem)

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        del exc
        log.emit(
            "api_internal_error",
            level="error",
            request_id=_request_id(request),
        )
        return _error_response(
            request,
            ApiProblem(500, "internal_error", "Internal service error."),
        )

    @app.get("/healthz")
    async def health() -> Mapping[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready(request: Request) -> Mapping[str, str]:
        _authorize(request, configured_token)
        try:
            is_ready = bool(await run_in_threadpool(readiness))
        except Exception:
            is_ready = False
        if not is_ready:
            raise ApiProblem(503, "service_not_ready", "Service is not ready.")
        return {"status": "ready"}

    @app.post("/v1/builds")
    async def submit_build(request: Request) -> JSONResponse:
        _authorize(request, configured_token)
        _json_media_type(request)
        idempotency_key = _idempotency_key(request)
        payload = await _bounded_body(request, MAX_BUILD_REQUEST_BYTES)
        reservation = await run_in_threadpool(
            repository.submit,
            payload,
            idempotency_key,
        )
        log.emit(
            "build_submitted" if reservation.created else "build_replayed",
            build_id=reservation.build.build_id,
            request_id=_request_id(request),
        )
        return JSONResponse(
            status_code=202 if reservation.created else 200,
            headers={"Location": f"/v1/builds/{reservation.build.build_id}"},
            content=_build_document(reservation.build),
        )

    @app.get("/v1/builds/{build_id}")
    async def get_build(build_id: UUID, request: Request) -> Mapping[str, object]:
        _authorize(request, configured_token)
        build = await run_in_threadpool(repository.get_build, build_id)
        return _build_document(build)

    @app.get("/v1/builds/{build_id}/artifacts")
    async def get_artifacts(build_id: UUID, request: Request) -> Mapping[str, object]:
        _authorize(request, configured_token)
        build = await run_in_threadpool(repository.get_build, build_id)
        if build.status is not BuildStatus.SUCCEEDED:
            if build.status in (
                BuildStatus.FAILED,
                BuildStatus.CANCELED,
                BuildStatus.NEEDS_REVIEW,
            ):
                raise ApiProblem(409, "artifacts_unavailable", "Build has no published artifacts.")
            raise ApiProblem(409, "artifacts_not_ready", "Build artifacts are not ready.")
        records = await run_in_threadpool(repository.artifacts_for, build_id)
        if set(records) != set(REQUIRED_PUBLISHED_ARTIFACTS) or len(records) != 9:
            raise ApiProblem(500, "artifact_invariant_failed", "Published artifact set is unavailable.")
        if any(record.build_id != build_id for record in records.values()):
            raise ApiProblem(500, "artifact_invariant_failed", "Published artifact set is unavailable.")
        result = []
        for path in REQUIRED_PUBLISHED_ARTIFACTS:
            record = records[path]
            url = await run_in_threadpool(
                storage.presign_get,
                record,
                expires_seconds=signed_url_ttl_seconds,
            )
            result.append(
                {
                    "path": path,
                    "content_type": record.content_type,
                    "bytes": record.bytes,
                    "sha256": record.sha256,
                    "download_url": url,
                }
            )
        return {
            "build_id": str(build_id),
            "published_at": _timestamp(build.published_at),
            "expires_in_seconds": signed_url_ttl_seconds,
            "artifacts": result,
        }

    @app.post("/v1/builds/{build_id}/cancel")
    async def cancel_build(build_id: UUID, request: Request) -> JSONResponse:
        _authorize(request, configured_token)
        await _require_empty_body(request)
        for _attempt in range(2):
            current = await run_in_threadpool(repository.get_build, build_id)
            if current.status is BuildStatus.CANCELED:
                return JSONResponse(status_code=200, content=_build_document(current))
            try:
                updated = await run_in_threadpool(
                    repository.request_cancel,
                    build_id,
                    current.state_version,
                )
                break
            except StateConflict as exc:
                if exc.code != "stale_state_version":
                    raise
        else:
            raise StateConflict("stale_state_version", "build state was updated concurrently")
        log.emit(
            "cancel_requested",
            build_id=build_id,
            request_id=_request_id(request),
        )
        status_code = 200 if updated.status is BuildStatus.CANCELED else 202
        return JSONResponse(status_code=status_code, content=_build_document(updated))

    return app


__all__ = ["ApiProblem", "create_app"]
