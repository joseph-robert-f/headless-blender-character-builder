from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Callable, Optional
from uuid import UUID

from hbcb_service.errors import WorkerError
from hbcb_service.launcher import (
    LaunchResult,
    LaunchTermination,
    SubprocessBuilderLauncher,
)
from hbcb_service.models import BuildStatus
from hbcb_service.queue import InMemoryBuildQueue
from hbcb_service.state import InMemoryStateStore
from hbcb_service.storage import InMemoryArtifactStorage
from hbcb_service.structured_log import StructuredLogger
from hbcb_service.worker import WorkerSupervisor, exit_policy

try:
    from .g6_support import (
        corrupt_file,
        facet_request_bytes,
        write_valid_builder_output,
    )
except ImportError:
    from g6_support import corrupt_file, facet_request_bytes, write_valid_builder_output


class FakeLauncher:
    def __init__(
        self,
        root: Path,
        results: list[tuple[int, LaunchTermination]],
        *,
        before_return: Optional[Callable[[UUID], None]] = None,
        corrupt: Optional[str] = None,
    ) -> None:
        self.root = root
        self.results = list(results)
        self.before_return = before_return
        self.corrupt = corrupt
        self.calls = []
        self.cleaned = []

    def execute(self, request_canonical: bytes, attempt_id: UUID, heartbeat: object) -> LaunchResult:
        self.calls.append((request_canonical, attempt_id, heartbeat))
        scratch = self.root / f"attempt-{attempt_id}"
        scratch.mkdir()
        output = scratch / "output"
        exit_code, termination = self.results.pop(0)
        if exit_code == 0 and termination is LaunchTermination.COMPLETED:
            write_valid_builder_output(output, request_canonical)
            if self.corrupt is not None:
                corrupt_file(output, self.corrupt)
        if self.before_return is not None:
            self.before_return(attempt_id)
        return LaunchResult(
            attempt_id=attempt_id,
            scratch_dir=scratch,
            output_dir=output,
            exit_code=exit_code,
            termination=termination,
            log_tail=b"secret-looking child output is intentionally not logged",
        )

    def cleanup(self, scratch: Path) -> None:
        self.cleaned.append(scratch)
        shutil.rmtree(scratch)


class WorkerFixture(unittest.TestCase):
    def make_worker(
        self,
        root: Path,
        launcher: FakeLauncher,
        *,
        max_attempts: int = 2,
    ) -> tuple[WorkerSupervisor, InMemoryStateStore, InMemoryBuildQueue, InMemoryArtifactStorage, io.StringIO]:
        state = InMemoryStateStore(
            idempotency_secret=b"s" * 32,
            max_attempts=max_attempts,
        )
        queue = InMemoryBuildQueue()
        storage = InMemoryArtifactStorage(
            namespace="local",
            bucket="hbcb-artifacts",
            public_base_url="http://localhost:9000",
        )
        log = io.StringIO()
        worker = WorkerSupervisor(
            repository=state,
            queue=queue,
            storage=storage,
            launcher=launcher,
            deployment_namespace="local",
            storage_bucket="hbcb-artifacts",
            worker_id="worker-1",
            lease_seconds=30,
            retry_delay_seconds=0,
            logger=StructuredLogger(log),
        )
        return worker, state, queue, storage, log


class WorkerLifecycleTests(WorkerFixture):
    def test_success_uploads_exact_versions_then_atomically_publishes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = FakeLauncher(root, [(0, LaunchTermination.COMPLETED)])
            worker, state, queue, storage, log = self.make_worker(root, launcher)
            reservation = state.submit(facet_request_bytes(), "facet-request-0001")
            self.assertTrue(worker.process_once(block_ms=0))
            build = state.get_build(reservation.build.build_id)
            self.assertEqual(build.status, BuildStatus.SUCCEEDED)
            artifacts = state.artifacts_for(build.build_id)
            self.assertEqual(len(artifacts), 9)
            self.assertTrue(all(record.version_id for record in artifacts.values()))
            self.assertEqual(queue.dead_messages, ())
            self.assertFalse(launcher.cleaned[0].exists())
            self.assertNotIn("secret-looking child output", log.getvalue())
            self.assertNotIn(facet_request_bytes().decode("utf-8"), log.getvalue())

    def test_retry_then_dead_letter_after_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = FakeLauncher(
                root,
                [
                    (10, LaunchTermination.COMPLETED),
                    (10, LaunchTermination.COMPLETED),
                ],
            )
            worker, state, queue, _storage, _log = self.make_worker(root, launcher)
            build_id = state.submit(facet_request_bytes(), "facet-request-0001").build.build_id
            self.assertTrue(worker.process_once(block_ms=0))
            self.assertEqual(state.get_build(build_id).status, BuildStatus.QUEUED)
            self.assertTrue(worker.process_once(block_ms=0))
            self.assertEqual(state.get_build(build_id).status, BuildStatus.FAILED)
            self.assertEqual(len(queue.dead_messages), 1)
            self.assertEqual(len(state.attempts_for(build_id)), 2)

    def test_timeout_is_retryable_and_exhaustion_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = FakeLauncher(root, [(143, LaunchTermination.TIMED_OUT)])
            worker, state, queue, _storage, _log = self.make_worker(
                root,
                launcher,
                max_attempts=1,
            )
            build_id = state.submit(facet_request_bytes(), "facet-request-0001").build.build_id
            worker.process_once(block_ms=0)
            self.assertEqual(state.get_build(build_id).status, BuildStatus.FAILED)
            self.assertEqual(state.attempts_for(build_id)[0].exit_code, 124)
            self.assertEqual(len(queue.dead_messages), 1)

    def test_running_cancellation_terminates_without_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state_holder: dict[str, InMemoryStateStore] = {}

            def cancel(attempt_id: UUID) -> None:
                state = state_holder["state"]
                attempt = state.attempt_for(attempt_id)
                build = state.get_build(attempt.build_id)
                state.request_cancel(build.build_id, build.state_version)

            launcher = FakeLauncher(
                root,
                [(143, LaunchTermination.CANCELED)],
                before_return=cancel,
            )
            worker, state, queue, _storage, _log = self.make_worker(root, launcher)
            state_holder["state"] = state
            build_id = state.submit(facet_request_bytes(), "facet-request-0001").build.build_id
            worker.process_once(block_ms=0)
            self.assertEqual(state.get_build(build_id).status, BuildStatus.CANCELED)
            self.assertEqual(state.artifacts_for(build_id), {})
            self.assertEqual(queue.dead_messages, ())

    def test_corrupt_success_output_is_never_published(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            launcher = FakeLauncher(
                root,
                [(0, LaunchTermination.COMPLETED)],
                corrupt="model.stl",
            )
            worker, state, queue, _storage, _log = self.make_worker(
                root,
                launcher,
                max_attempts=1,
            )
            build_id = state.submit(facet_request_bytes(), "facet-request-0001").build.build_id
            worker.process_once(block_ms=0)
            self.assertEqual(state.get_build(build_id).status, BuildStatus.FAILED)
            self.assertEqual(state.artifacts_for(build_id), {})
            self.assertEqual(len(queue.dead_messages), 1)

    def test_exit_code_policy_is_fixed_and_bounded(self) -> None:
        self.assertFalse(exit_policy(3).retryable)
        self.assertFalse(exit_policy(11).retryable)
        self.assertTrue(exit_policy(4).retryable)
        self.assertTrue(exit_policy(10).retryable)
        self.assertTrue(exit_policy(12).retryable)
        self.assertTrue(exit_policy(137).retryable)


@unittest.skipIf(os.name == "nt", "POSIX process-group semantics")
class FreshSubprocessLauncherTests(unittest.TestCase):
    def _script(self, root: Path, body: str) -> Path:
        script = root / "builder-fixture"
        script.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
        script.chmod(0o700)
        return script

    def test_each_call_uses_a_fresh_pid_and_scrubbed_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch_root = root / "scratch"
            scratch_root.mkdir()
            script = self._script(
                root,
                'mkdir "$5"\nprintf "%s\\n" "$$" > "$5/pid"\nenv > "$5/environment"\n',
            )
            launcher = SubprocessBuilderLauncher(
                builder_executable=script,
                scratch_root=scratch_root,
                image_reference="headless-blender-character-builder-supervisor:test",
                timeout_seconds=5,
                poll_seconds=0.05,
                system_path="/usr/bin:/bin",
            )
            previous = os.environ.get("HBCB_API_TOKEN")
            os.environ["HBCB_API_TOKEN"] = "canary-secret-that-must-not-reach-child"
            try:
                first = launcher.execute(
                    b"{}",
                    UUID("22222222-2222-4222-8222-222222222222"),
                    lambda: False,
                )
                second = launcher.execute(
                    b"{}",
                    UUID("33333333-3333-4333-8333-333333333333"),
                    lambda: False,
                )
            finally:
                if previous is None:
                    os.environ.pop("HBCB_API_TOKEN", None)
                else:
                    os.environ["HBCB_API_TOKEN"] = previous
            self.assertEqual(first.termination, LaunchTermination.COMPLETED)
            self.assertEqual(second.termination, LaunchTermination.COMPLETED)
            self.assertNotEqual(
                (first.output_dir / "pid").read_text(),
                (second.output_dir / "pid").read_text(),
            )
            for result in (first, second):
                environment = (result.output_dir / "environment").read_text()
                self.assertNotIn("HBCB_API_TOKEN", environment)
                self.assertNotIn("canary-secret", environment)
                self.assertIn("HBCB_EXECUTION_MODE=container", environment)
                launcher.cleanup(result.scratch_dir)

    @unittest.skipUnless(Path("/proc").is_dir(), "Linux /proc process-tree gate")
    def test_cancellation_terminates_nested_builder_group_and_cleanup_is_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scratch_root = root / "scratch"
            scratch_root.mkdir()
            script = root / "builder-fixture"
            script.write_text(
                f"#!{sys.executable}\n"
                "import os\n"
                "from pathlib import Path\n"
                "import subprocess\n"
                "import sys\n"
                "output = Path(sys.argv[5])\n"
                "ready = output / 'child-ready'\n"
                "output.mkdir()\n"
                "child = subprocess.Popen(\n"
                "    [\n"
                "        sys.executable,\n"
                "        '-c',\n"
                "        \"import signal,sys,time; from pathlib import Path; \"\n"
                "        \"signal.signal(signal.SIGTERM, signal.SIG_IGN); \"\n"
                "        \"Path(sys.argv[1]).write_text('ready'); time.sleep(30)\",\n"
                "        str(ready),\n"
                "    ],\n"
                "    start_new_session=True,\n"
                ")\n"
                "while not ready.exists():\n"
                "    import time\n"
                "    time.sleep(0.01)\n"
                "(output / 'processes').write_text(\n"
                "    f'{os.getpid()} {os.getpgrp()} {child.pid} {os.getpgid(child.pid)}\\n',\n"
                "    encoding='ascii',\n"
                ")\n"
                "(output / 'processes-ready').touch()\n"
                "child.wait()\n",
                encoding="utf-8",
            )
            script.chmod(0o700)
            launcher = SubprocessBuilderLauncher(
                builder_executable=script,
                scratch_root=scratch_root,
                image_reference="headless-blender-character-builder-supervisor:test",
                timeout_seconds=5,
                poll_seconds=0.05,
                system_path="/usr/bin:/bin",
            )
            started = time.monotonic()
            result = launcher.execute(
                b"{}",
                UUID("22222222-2222-4222-8222-222222222222"),
                lambda: any(scratch_root.glob("attempt-*/output/processes-ready")),
            )
            elapsed = time.monotonic() - started
            self.assertEqual(result.termination, LaunchTermination.CANCELED)
            self.assertLess(elapsed, 6, "cancellation waited for the orphan sleep")
            root_pid, root_group, child_pid, child_group = (
                int(value)
                for value in (result.output_dir / "processes").read_text().split()
            )
            self.assertNotEqual(root_pid, child_pid)
            self.assertNotEqual(root_group, child_group)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                stat_path = Path("/proc") / str(child_pid) / "stat"
                try:
                    state = stat_path.read_text(encoding="ascii")
                    state = state[state.rfind(")") + 2 :].split()[0]
                    if state == "Z":
                        break
                    os.kill(child_pid, 0)
                except (OSError, UnicodeDecodeError, IndexError):
                    break
                time.sleep(0.02)
            else:
                self.fail("nested Blender fixture survived supervisor cancellation")
            launcher.cleanup(result.scratch_dir)
            with self.assertRaises(WorkerError):
                launcher.cleanup(root)


if __name__ == "__main__":
    unittest.main()
