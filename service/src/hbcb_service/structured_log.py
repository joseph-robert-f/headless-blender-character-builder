"""Small JSON-lines logger with an intentionally narrow, secret-safe schema."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from threading import Lock
from typing import Mapping, Optional, TextIO
from uuid import UUID


EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
WORKER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SAFE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StructuredLogger:
    """Emit bounded lifecycle metadata, never payloads, URLs, or credentials."""

    def __init__(self, stream: TextIO = sys.stdout) -> None:
        self._stream = stream
        self._lock = Lock()

    def emit(
        self,
        event: str,
        *,
        level: str = "info",
        build_id: Optional[UUID] = None,
        attempt_id: Optional[UUID] = None,
        request_id: Optional[UUID] = None,
        worker_id: Optional[str] = None,
        code: Optional[str] = None,
        details: Optional[Mapping[str, object]] = None,
    ) -> None:
        if EVENT_PATTERN.fullmatch(event) is None or level not in ("debug", "info", "warning", "error"):
            raise ValueError("structured log event is outside policy")
        record: dict[str, object] = {
            "timestamp": _timestamp(),
            "level": level,
            "event": event,
        }
        for name, value in (
            ("build_id", build_id),
            ("attempt_id", attempt_id),
            ("request_id", request_id),
        ):
            if value is not None:
                if not isinstance(value, UUID):
                    raise ValueError("structured log identifier is invalid")
                record[name] = str(value)
        if worker_id is not None:
            if WORKER_PATTERN.fullmatch(worker_id) is None:
                raise ValueError("structured log worker identifier is invalid")
            record["worker_id"] = worker_id
        if code is not None:
            if EVENT_PATTERN.fullmatch(code) is None:
                raise ValueError("structured log code is invalid")
            record["code"] = code
        if details:
            safe_details: dict[str, object] = {}
            for key, value in details.items():
                if EVENT_PATTERN.fullmatch(key) is None:
                    raise ValueError("structured log detail key is invalid")
                if isinstance(value, bool):
                    safe_details[key] = value
                elif isinstance(value, int) and not isinstance(value, bool) and -(2**63) <= value < 2**63:
                    safe_details[key] = value
                elif isinstance(value, str) and SAFE_VALUE_PATTERN.fullmatch(value) is not None:
                    safe_details[key] = value
                else:
                    raise ValueError("structured log detail value is outside policy")
            record["details"] = safe_details
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        with self._lock:
            self._stream.write(encoded + "\n")
            self._stream.flush()


__all__ = ["StructuredLogger"]
