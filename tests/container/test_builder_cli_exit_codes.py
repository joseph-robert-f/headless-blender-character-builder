"""Safe launcher-level coverage for exits that black-box geometry cannot force."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from builder_cli import commands
from builder_cli.__main__ import main
from builder_cli.exit_codes import ExitCode


ROOT = Path(__file__).resolve().parents[2]


class _TimeoutProcess:
    pid = 987654321

    def wait(self, timeout: int) -> int:
        raise subprocess.TimeoutExpired(cmd="blender", timeout=timeout)


class BuilderCliExitCodeTests(unittest.TestCase):
    def test_validate_accepts_request_without_blender_or_output(self) -> None:
        stdout = io.StringIO()
        request = ROOT / "examples" / "requests" / "facet-bot.json"
        with mock.patch(
            "builder_cli.commands._blender_binary",
            side_effect=AssertionError("validate must not inspect Blender"),
        ), mock.patch(
            "builder_cli.commands._new_output",
            side_effect=AssertionError("validate must not prepare output"),
        ), contextlib.redirect_stdout(stdout):
            result = main(("validate", "--request", str(request)))
        self.assertEqual(result, int(ExitCode.SUCCESS))
        self.assertEqual(stdout.getvalue(), "BUILDER_VALIDATE: PASS\n")

    def test_validate_rejects_invalid_request_without_leaking_contents(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-validate-") as raw:
            request = Path(raw) / "request.json"
            secret = "validate-canary-secret"
            request.write_text('{"unexpected":"' + secret + '"}\n', encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main(("validate", "--request", str(request)))
        self.assertEqual(result, int(ExitCode.INVALID_REQUEST))
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("BUILDER: FAIL[3]: BuildRequest was rejected", stderr.getvalue())
        self.assertNotIn(secret, stderr.getvalue())

    def test_validate_rejects_output_option_as_invalid_cli(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        request = ROOT / "examples" / "requests" / "facet-bot.json"
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(
                ("validate", "--request", str(request), "--output", "must-not-exist")
            )
        self.assertEqual(result, int(ExitCode.INVALID_CLI))
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("FAIL[2]", stderr.getvalue())

    def test_missing_native_blender_maps_to_10_without_publishing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-g4-exit10-") as raw:
            root = Path(raw)
            output = root / "output"
            environment = {
                "HBCB_BLENDER_BINARY": str(root / "does-not-exist"),
                "PATH": os.environ.get("PATH", ""),
            }
            stderr = io.StringIO()
            with mock.patch.dict(os.environ, environment, clear=True), contextlib.redirect_stderr(stderr):
                result = main(
                    (
                        "build",
                        "--request",
                        str(ROOT / "examples" / "requests" / "facet-bot.json"),
                        "--output",
                        str(output),
                    )
                )
            self.assertEqual(result, int(ExitCode.BLENDER))
            self.assertFalse(output.exists())
        self.assertIn("FAIL[10]", stderr.getvalue())

    def test_controlled_wait_timeout_maps_to_124_and_terminates(self) -> None:
        process = _TimeoutProcess()
        with mock.patch.object(commands.subprocess, "Popen", return_value=process), mock.patch.object(
            commands, "_terminate"
        ) as terminate:
            with self.assertRaises(commands.BuilderCliFailure) as captured:
                commands._run(("blender",), {})
        self.assertEqual(captured.exception.exit_code, int(ExitCode.TIMEOUT))
        terminate.assert_called_once_with(process)

    def test_unexpected_trusted_wrapper_failure_maps_to_12(self) -> None:
        stderr = io.StringIO()
        with mock.patch("builder_cli.__main__.build_artifacts", side_effect=RuntimeError("canary")), contextlib.redirect_stderr(stderr):
            result = main(("build", "--request", "unused", "--output", "unused"))
        self.assertEqual(result, int(ExitCode.INTERNAL))
        self.assertIn("FAIL[12]", stderr.getvalue())
        self.assertNotIn("canary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
