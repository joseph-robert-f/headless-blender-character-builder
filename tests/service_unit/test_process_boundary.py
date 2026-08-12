from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from uuid import UUID

from hbcb_service.errors import WorkerError
from hbcb_service import process_boundary
from hbcb_service import worker_main
from hbcb_service.launcher import SubprocessBuilderLauncher


class FakePrctl:
    def __init__(self, *, set_result: int = 0, get_result: int = 0) -> None:
        self.set_result = set_result
        self.get_result = get_result
        self.calls: list[int] = []

    def __call__(self, operation: int, *_arguments: int) -> int:
        self.calls.append(operation)
        if operation == 4:
            return self.set_result
        if operation == 3:
            return self.get_result
        raise AssertionError("unexpected prctl operation")


class ProcessBoundaryUnitTests(unittest.TestCase):
    def test_linux_boundary_sets_and_verifies_dump_and_core_controls(self) -> None:
        operation = FakePrctl()
        with (
            mock.patch.object(process_boundary.sys, "platform", "linux"),
            mock.patch.object(process_boundary, "_prctl", return_value=operation),
            mock.patch.object(process_boundary.resource, "setrlimit") as set_limit,
            mock.patch.object(
                process_boundary.resource,
                "getrlimit",
                return_value=(0, 0),
            ),
        ):
            process_boundary.secure_supervisor_process(require_linux=True)
        self.assertEqual(operation.calls, [4, 3])
        set_limit.assert_called_once_with(process_boundary.resource.RLIMIT_CORE, (0, 0))

    def test_linux_boundary_fails_closed_when_dumpable_cannot_be_disabled(self) -> None:
        operation = FakePrctl(get_result=1)
        with (
            mock.patch.object(process_boundary.sys, "platform", "linux"),
            mock.patch.object(process_boundary, "_prctl", return_value=operation),
        ):
            with self.assertRaises(WorkerError) as captured:
                process_boundary.secure_supervisor_process(require_linux=True)
        self.assertEqual(captured.exception.code, "process_boundary_unavailable")

    def test_required_boundary_rejects_non_linux_runtime(self) -> None:
        with mock.patch.object(process_boundary.sys, "platform", "darwin"):
            with self.assertRaises(WorkerError) as captured:
                process_boundary.secure_supervisor_process(require_linux=True)
        self.assertEqual(captured.exception.code, "process_boundary_unsupported")

    def test_launcher_fails_before_scratch_or_child_when_boundary_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            scratch = root / "scratch"
            scratch.mkdir()
            builder = root / "builder"
            builder.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
            builder.chmod(0o700)
            launcher = SubprocessBuilderLauncher(
                builder_executable=builder,
                scratch_root=scratch,
                image_reference="headless-blender-character-builder-worker:test",
            )
            failure = WorkerError(
                "process_boundary_unavailable",
                "worker process-inspection protection is unavailable",
            )
            with (
                mock.patch(
                    "hbcb_service.launcher.secure_supervisor_process",
                    side_effect=failure,
                ) as secure,
                mock.patch("hbcb_service.launcher.tempfile.mkdtemp") as make_scratch,
                mock.patch("hbcb_service.launcher.subprocess.Popen") as spawn,
            ):
                with self.assertRaises(WorkerError) as captured:
                    launcher.execute(
                        b"{}",
                        UUID("503b8cb8-096f-49ce-89bf-08c39726b2fd"),
                        lambda: False,
                    )
            self.assertEqual(captured.exception.code, "process_boundary_unavailable")
            secure.assert_called_once_with()
            make_scratch.assert_not_called()
            spawn.assert_not_called()

    def test_worker_main_hardens_before_constructing_dependencies(self) -> None:
        failure = WorkerError(
            "process_boundary_unavailable",
            "worker process-inspection protection is unavailable",
        )
        with (
            mock.patch.object(
                worker_main,
                "secure_supervisor_process",
                side_effect=failure,
            ) as secure,
            mock.patch.object(worker_main, "create_supervisor") as create,
        ):
            with self.assertRaises(WorkerError):
                worker_main.main()
        secure.assert_called_once_with(require_linux=True)
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
