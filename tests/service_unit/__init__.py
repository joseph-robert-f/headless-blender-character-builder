"""G5 service tests with the isolated service source tree on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path


SERVICE_SOURCE = Path(__file__).resolve().parents[2] / "service" / "src"
if str(SERVICE_SOURCE) not in sys.path:
    sys.path.insert(0, str(SERVICE_SOURCE))
