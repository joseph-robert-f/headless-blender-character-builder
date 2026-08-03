"""Stable process exit codes.

These are part of the public contract: automation is expected to branch on them,
so a value never changes meaning once released. Docker and shell reserve 125-127
and 128+N, which is why nothing here lands in that range.
"""

OK = 0
USAGE = 2
INVALID_REQUEST = 3
FILESYSTEM = 4
BLENDER_FAILED = 10
VERIFY_FAILED = 11
INTERNAL = 12
TIMEOUT = 124

MEANINGS = {
    OK: "build and all required QA succeeded",
    USAGE: "invalid command line or unsupported option",
    INVALID_REQUEST: "invalid or policy-rejected BuildRequest",
    FILESYSTEM: "input, output, or staging filesystem failure",
    BLENDER_FAILED: "Blender generation, render, or export failure",
    VERIFY_FAILED: "fresh-reload, artifact verification, or required QA failure",
    INTERNAL: "unexpected internal failure",
    TIMEOUT: "controlled wall-clock timeout",
}


class BuildError(Exception):
    """Error carrying the exit code the process should terminate with."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message
