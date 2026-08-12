"""Safe launcher-level coverage for exits that black-box geometry cannot force."""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from builder_cli import commands
from builder_cli.__main__ import main
from builder_cli.exit_codes import ExitCode
from shared.json_contract import ContractValidationError


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
            secret_field = "private-field-canary"
            request.write_text(
                json.dumps({secret_field: secret}) + "\n", encoding="utf-8"
            )
            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = main(("validate", "--request", str(request)))
        self.assertEqual(result, int(ExitCode.INVALID_REQUEST))
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(
            stderr.getvalue(),
            "BUILDER: FAIL[3]: BuildRequest was rejected: extra_property at $: "
            "request contains unsupported field(s)\n",
        )
        self.assertNotIn(secret, stderr.getvalue())
        self.assertNotIn(secret_field, stderr.getvalue())

    def test_validate_reports_safe_code_path_and_static_reason(self) -> None:
        original = json.loads(
            (ROOT / "examples" / "requests" / "facet-bot.json").read_text(
                encoding="utf-8"
            )
        )
        cases = (
            (
                "invalid-color",
                ("spec", "palette", 0),
                "private-color-value",
                "invalid_color at $.spec.palette[0]: "
                "palette colors must use uppercase #RRGGBB",
            ),
            (
                "invalid-enum",
                ("spec", "style"),
                "private-style-value",
                "invalid_enum at $.spec.style: value is not one of the supported choices",
            ),
            (
                "out-of-range",
                ("spec", "height_mm"),
                987654321,
                "number_out_of_range at $.spec.height_mm: "
                "number is outside the supported range",
            ),
        )
        with tempfile.TemporaryDirectory(prefix="hbcb-validate-details-") as raw:
            for name, path, submitted_value, expected in cases:
                with self.subTest(name=name):
                    payload = json.loads(json.dumps(original))
                    target = payload
                    for segment in path[:-1]:
                        target = target[segment]
                    target[path[-1]] = submitted_value
                    request = Path(raw) / f"{name}.json"
                    request.write_text(json.dumps(payload), encoding="utf-8")
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        result = main(("validate", "--request", str(request)))
                    self.assertEqual(result, int(ExitCode.INVALID_REQUEST))
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(
                        stderr.getvalue(),
                        f"BUILDER: FAIL[3]: BuildRequest was rejected: {expected}\n",
                    )
                    self.assertNotIn(str(submitted_value), stderr.getvalue())

    def test_rejection_diagnostic_bounds_untrusted_code_and_path_metadata(self) -> None:
        canary = "private-path-canary"
        oversized_path = "$." + ("A" * 1_000_000) + canary
        diagnostic = commands._request_rejection(
            ContractValidationError(
                "attacker_controlled_code", "attacker-controlled reason", oversized_path
            )
        )
        self.assertEqual(
            diagnostic,
            "BuildRequest was rejected: invalid_request at $: "
            "request does not satisfy the supported build contract",
        )
        self.assertLessEqual(len(diagnostic), 160)
        self.assertNotIn(canary, diagnostic)

    def test_dangling_output_symlink_is_no_clobber_failure(self) -> None:
        request = ROOT / "examples" / "requests" / "facet-bot.json"
        with tempfile.TemporaryDirectory(prefix="hbcb-output-symlink-") as raw:
            root = Path(raw)
            missing_target = root / "missing-target"
            output = root / "claimed-output"
            output.symlink_to(missing_target, target_is_directory=True)
            stderr = io.StringIO()
            with mock.patch(
                "builder_cli.commands._blender_binary",
                side_effect=AssertionError("no-clobber must fail before Blender"),
            ), contextlib.redirect_stderr(stderr):
                result = main(
                    (
                        "build",
                        "--request",
                        str(request),
                        "--output",
                        str(output),
                    )
                )
            self.assertEqual(result, int(ExitCode.FILESYSTEM))
            self.assertEqual(
                stderr.getvalue(),
                "BUILDER: FAIL[4]: output must not already exist\n",
            )
            self.assertTrue(output.is_symlink())
            self.assertFalse(missing_target.exists())

    def test_rejected_request_exit_is_stable_for_every_request_command(self) -> None:
        request = ROOT / "tests" / "fixtures" / "rejected" / "unsafe-slug.json"
        with tempfile.TemporaryDirectory(prefix="hbcb-invalid-request-exits-") as raw:
            output = Path(raw) / "output"
            for argv in (
                ("validate", "--request", str(request)),
                ("build", "--request", str(request), "--output", str(output)),
                ("verify", "--request", str(request), "--output", str(output)),
            ):
                with self.subTest(command=argv[0]):
                    stdout = io.StringIO()
                    stderr = io.StringIO()
                    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        result = main(argv)
                    self.assertEqual(result, int(ExitCode.INVALID_REQUEST))
                    self.assertEqual(stdout.getvalue(), "")
                    self.assertEqual(
                        stderr.getvalue(),
                        "BUILDER: FAIL[3]: BuildRequest was rejected: invalid_slug at "
                        "$.spec.slug: slug must be a 1-48 character lowercase safe slug\n",
                    )
                    self.assertFalse(output.exists())

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
