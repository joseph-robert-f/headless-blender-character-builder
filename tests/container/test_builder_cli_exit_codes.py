"""Safe launcher-level coverage for exits that black-box geometry cannot force."""

from __future__ import annotations

import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from builder_cli import commands
from builder_cli.__main__ import main
from builder_cli.exit_codes import ExitCode
from shared.json_contract import ContractValidationError


ROOT = Path(__file__).resolve().parents[2]


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        return True
    return True


def _wait_for_path(path: Path, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_file():
            return
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {path.name}")


def _wait_for_group_exit(process_group: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_group_exists(process_group):
            return True
        time.sleep(0.02)
    return not _process_group_exists(process_group)


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
        ) as terminate, mock.patch.object(
            commands.time,
            "monotonic",
            side_effect=(0.0, 0.0, float(commands.BUILD_TIMEOUT_SECONDS) + 1.0),
        ):
            with self.assertRaises(commands.BuilderCliFailure) as captured:
                commands._run(("blender",), {})
        self.assertEqual(captured.exception.exit_code, int(ExitCode.TIMEOUT))
        terminate.assert_called_once_with(process)

    def test_interrupt_or_unexpected_wait_failure_terminates_owned_blender(self) -> None:
        for failure in (KeyboardInterrupt(), RuntimeError("trusted wait failure")):
            with self.subTest(exception=type(failure).__name__):
                process = mock.Mock()
                process.wait.side_effect = failure
                with mock.patch.object(
                    commands.subprocess, "Popen", return_value=process
                ), mock.patch.object(commands, "_terminate") as terminate:
                    with self.assertRaises(type(failure)):
                        commands._run(("blender",), {})
                terminate.assert_called_once_with(process)

    @unittest.skipUnless(
        hasattr(os, "killpg"),
        "requires POSIX process groups",
    )
    def test_signal_during_popen_publication_reaps_owned_group(self) -> None:
        child = (
            "import signal,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(getattr(signal,'SIGHUP',signal.SIGTERM),signal.SIG_IGN);"
            "time.sleep(30)"
        )
        selected_signals = [signal.SIGINT, signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            selected_signals.append(signal.SIGHUP)
        real_popen = subprocess.Popen
        real_terminate = commands._terminate
        for selected_signal in selected_signals:
            with self.subTest(signal=selected_signal):
                previous_handler = signal.getsignal(selected_signal)
                process_groups: list[int] = []
                repeated_signals: list[int] = []

                def inject_signal(command, *args, **kwargs):
                    process = real_popen(command, *args, **kwargs)
                    process_groups.append(process.pid)
                    os.kill(os.getpid(), selected_signal)
                    return process

                def terminate_after_repeated_signal(process):
                    handler = signal.getsignal(selected_signal)
                    self.assertIs(
                        getattr(handler, "__func__", None),
                        commands._TerminationGuard._record,
                    )
                    handler(selected_signal, None)
                    repeated_signals.append(selected_signal)
                    real_terminate(process)

                try:
                    expected = (
                        KeyboardInterrupt
                        if selected_signal == signal.SIGINT
                        else SystemExit
                    )
                    with mock.patch.object(
                        commands.subprocess,
                        "Popen",
                        side_effect=inject_signal,
                    ), mock.patch.object(
                        commands,
                        "PROCESS_TERM_GRACE_SECONDS",
                        0.1,
                    ), mock.patch.object(
                        commands,
                        "PROCESS_KILL_GRACE_SECONDS",
                        0.5,
                    ), mock.patch.object(
                        commands,
                        "_terminate",
                        side_effect=terminate_after_repeated_signal,
                    ), self.assertRaises(expected) as captured:
                        commands._run([sys.executable, "-c", child], os.environ)
                    if selected_signal != signal.SIGINT:
                        self.assertEqual(captured.exception.code, 128 + selected_signal)
                    self.assertEqual(len(process_groups), 1)
                    self.assertEqual(repeated_signals, [selected_signal])
                    self.assertTrue(_wait_for_group_exit(process_groups[0]))
                    self.assertEqual(
                        signal.getsignal(selected_signal),
                        previous_handler,
                    )
                finally:
                    for process_group in process_groups:
                        if (
                            process_group != os.getpgrp()
                            and _process_group_exists(process_group)
                        ):
                            os.killpg(process_group, signal.SIGKILL)

    def test_custom_and_ignored_embedding_handlers_are_preserved(self) -> None:
        def custom_handler(_signum, _frame):
            return None

        for selected_signal in commands._TERMINATION_SIGNALS:
            original = signal.getsignal(selected_signal)
            try:
                for handler in (custom_handler, signal.SIG_IGN):
                    with self.subTest(signal=selected_signal, handler=handler):
                        signal.signal(selected_signal, handler)
                        process = mock.Mock()
                        process.pid = 987654321
                        process.wait.return_value = 0
                        with mock.patch.object(
                            commands.subprocess,
                            "Popen",
                            return_value=process,
                        ), mock.patch.object(
                            commands,
                            "_process_group_exists",
                            return_value=False,
                        ):
                            self.assertEqual(commands._run(("blender",), {}), 0)
                        self.assertIs(signal.getsignal(selected_signal), handler)
            finally:
                signal.signal(selected_signal, original)

    @unittest.skipUnless(
        hasattr(os, "killpg") and hasattr(signal, "SIGHUP"),
        "requires POSIX process groups and SIGHUP",
    )
    def test_live_cli_signals_reap_term_resistant_descendants_before_exit(self) -> None:
        descendant = (
            "import os,signal,sys,time;"
            "from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(signal.SIGHUP,signal.SIG_IGN);"
            "Path(sys.argv[1]).write_text("
            "str(os.getpid())+' '+str(os.getpgrp()),encoding='ascii');"
            "time.sleep(30)"
        )
        leader = (
            "import signal,subprocess,sys,time;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "signal.signal(signal.SIGHUP,signal.SIG_IGN);"
            "subprocess.Popen([sys.executable,'-c',%r,sys.argv[1]]);"
            "time.sleep(30)"
        ) % descendant
        for selected_signal in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=selected_signal), tempfile.TemporaryDirectory(
                prefix="hbcb-builder-signal-"
            ) as raw:
                marker = Path(raw) / "descendant.pid"
                owned_group_marker = Path(raw) / "owned-group.pid"
                cleanup_marker = Path(raw) / "cleanup-started"
                controller: subprocess.Popen[bytes] | None = None
                child_group: int | None = None
                controller_code = (
                    "import os,signal,sys,time\n"
                    "from pathlib import Path\n"
                    "from builder_cli import commands\n"
                    "commands.PROCESS_TERM_GRACE_SECONDS=0.2\n"
                    "commands.PROCESS_KILL_GRACE_SECONDS=0.7\n"
                    "cleanup_marker=Path(%r)\n"
                    "owned_group_marker=Path(%r)\n"
                    "real_popen=commands.subprocess.Popen\n"
                    "real_signal=commands._signal_process_group\n"
                    "def observed_popen(*args, **kwargs):\n"
                    "    process=real_popen(*args, **kwargs)\n"
                    "    owned_group_marker.write_text(str(process.pid),encoding='ascii')\n"
                    "    return process\n"
                    "def observed_signal(process, selected_signal):\n"
                    "    real_signal(process, selected_signal)\n"
                    "    if selected_signal == signal.SIGTERM and not cleanup_marker.exists():\n"
                    "        cleanup_marker.write_text('started',encoding='ascii')\n"
                    "        time.sleep(0.2)\n"
                    "commands.subprocess.Popen=observed_popen\n"
                    "commands._signal_process_group=observed_signal\n"
                    "raise SystemExit(commands._run("
                    "[sys.executable,'-c',%r,%r],dict(os.environ)))\n"
                ) % (
                    str(cleanup_marker),
                    str(owned_group_marker),
                    leader,
                    str(marker),
                )
                try:
                    controller = subprocess.Popen(
                        [sys.executable, "-c", controller_code],
                        cwd=str(ROOT),
                        env=dict(
                            os.environ,
                            LC_ALL="C",
                            PYTHONDONTWRITEBYTECODE="1",
                        ),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    _wait_for_path(marker)
                    _descendant_pid, rendered_group = marker.read_text(
                        encoding="ascii"
                    ).split()
                    child_group = int(rendered_group)
                    self.assertGreater(child_group, 1)
                    self.assertNotEqual(child_group, os.getpgrp())
                    controller.send_signal(selected_signal)
                    _wait_for_path(cleanup_marker)
                    controller.send_signal(selected_signal)
                    controller.wait(timeout=5)
                    # CPython preserves an uncaught KeyboardInterrupt by
                    # terminating with SIGINT; a shell renders that as 130.
                    expected = (
                        -signal.SIGINT
                        if selected_signal == signal.SIGINT
                        else 128 + selected_signal
                    )
                    self.assertEqual(controller.returncode, expected)
                    self.assertTrue(_wait_for_group_exit(child_group))
                finally:
                    if controller is not None and controller.poll() is None:
                        os.killpg(controller.pid, signal.SIGKILL)
                        controller.wait(timeout=2)
                    if child_group is None and owned_group_marker.is_file():
                        child_group = int(
                            owned_group_marker.read_text(encoding="ascii")
                        )
                    if (
                        child_group is not None
                        and child_group != os.getpgrp()
                        and _process_group_exists(child_group)
                    ):
                        os.killpg(child_group, signal.SIGKILL)

    def test_unexpected_trusted_wrapper_failure_maps_to_12(self) -> None:
        stderr = io.StringIO()
        with mock.patch("builder_cli.__main__.build_artifacts", side_effect=RuntimeError("canary")), contextlib.redirect_stderr(stderr):
            result = main(("build", "--request", "unused", "--output", "unused"))
        self.assertEqual(result, int(ExitCode.INTERNAL))
        self.assertIn("FAIL[12]", stderr.getvalue())
        self.assertNotIn("canary", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
