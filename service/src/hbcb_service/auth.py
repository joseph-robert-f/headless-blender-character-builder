"""Strict single-operator bearer authentication."""

from __future__ import annotations

import hmac
import re
from typing import Optional, Union

from .errors import AuthorizationError


MAX_AUTHORIZATION_HEADER_BYTES = 1024
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,256}$")


def validate_service_token(token: str) -> str:
    if not isinstance(token, str) or TOKEN_PATTERN.fullmatch(token) is None:
        raise AuthorizationError("invalid_service_token", "configured service token is outside policy")
    return token


def authorize_bearer(
    authorization: Optional[Union[str, bytes]], configured_token: str
) -> None:
    expected = validate_service_token(configured_token)
    if authorization is None:
        raise AuthorizationError("missing_authorization", "bearer authorization is required")
    if isinstance(authorization, bytes):
        raw = authorization
        try:
            header = raw.decode("ascii", "strict")
        except UnicodeDecodeError as exc:
            raise AuthorizationError("invalid_authorization", "authorization header is malformed") from exc
    elif isinstance(authorization, str):
        try:
            raw = authorization.encode("ascii", "strict")
        except UnicodeEncodeError as exc:
            raise AuthorizationError("invalid_authorization", "authorization header is malformed") from exc
        header = authorization
    else:
        raise AuthorizationError("invalid_authorization", "authorization header is malformed")
    if len(raw) > MAX_AUTHORIZATION_HEADER_BYTES:
        raise AuthorizationError("invalid_authorization", "authorization header is malformed")
    prefix = "Bearer "
    if not header.startswith(prefix) or header.count(" ") != 1:
        raise AuthorizationError("invalid_authorization", "authorization header is malformed")
    candidate = header[len(prefix) :]
    if TOKEN_PATTERN.fullmatch(candidate) is None or not hmac.compare_digest(candidate, expected):
        raise AuthorizationError("invalid_token", "bearer token is invalid")
