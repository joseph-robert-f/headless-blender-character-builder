from __future__ import annotations

import os
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ReleaseCleanupRuntimeTests(unittest.TestCase):
    def _write_executable(self, path: Path, source: str) -> None:
        payload = textwrap.dedent(source).lstrip()
        payload = payload.replace("#!/usr/bin/python3\n", f"#!{sys.executable}\n", 1)
        path.write_text(payload, encoding="utf-8")
        path.chmod(0o700)

    def _fixture(self, parent: Path) -> tuple[Path, Path, Path, Path]:
        checkout = parent / "checkout"
        tools = parent / "tools"
        state = parent / "state"
        temporary = parent / "tmp"
        for directory in (checkout, tools, state, temporary):
            directory.mkdir()

        for relative in (
            ".github/workflows/ci.yml",
            ".github/workflows/dependency-audit.yml",
            ".github/workflows/release-candidate.yml",
            "release/corresponding-source-policy.json",
        ):
            target = checkout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n", encoding="ascii")

        scripts = checkout / "scripts"
        scripts.mkdir()
        shutil.copyfile(ROOT / "scripts" / "release-check", scripts / "release-check")
        (scripts / "release-check").chmod(0o700)
        (checkout / "VERSION").write_text("0.1.0\n", encoding="ascii")
        for name in (
            "dependency-audit",
            "fetch-corresponding-source",
            "minio-recipe-id",
            "release-artifacts",
            "release-audit",
            "service-sbom",
        ):
            (scripts / name).write_text("fixture\n", encoding="ascii")

        self._write_executable(
            scripts / "service-common",
            """
            #!/bin/sh
            hbcb_service_valid_project_name() { return 0; }
            hbcb_service_settings() {
              HBCB_MINIO_IMAGE=fixture-minio:latest
              export HBCB_MINIO_IMAGE
            }
            """,
        )
        self._write_executable(
            scripts / "service-compose",
            """
            #!/bin/sh
            printf 'service-compose' >> "$HBCB_FAKE_LOG"
            printf ' %s' "$@" >> "$HBCB_FAKE_LOG"
            printf '\n' >> "$HBCB_FAKE_LOG"
            if [ "${HBCB_FAKE_SCENARIO:-}" = automatic-exit-signal ]; then
              kill -TERM "$PPID"
              exit 49
            fi
            if [ "${HBCB_FAKE_SCENARIO:-}" = cleanup-down-failure ]; then
              exit 41
            fi
            exit 0
            """,
        )

        self._write_executable(
            tools / "python",
            r"""
            #!/usr/bin/python3
            import json
            import os
            import shlex
            import sys
            from pathlib import Path

            args = sys.argv[1:]
            with Path(os.environ["HBCB_FAKE_LOG"]).open("a", encoding="utf-8") as stream:
                stream.write("python " + shlex.join(args) + "\n")

            if args and args[0] == "-c":
                if "json.load" in args[1]:
                    print("a" * 40)
                elif "secrets.token_hex" in args[1]:
                    print("d" * 32)
                raise SystemExit(0)
            if args[:2] == ["-m", "unittest"] or args[:2] == ["-m", "json.tool"]:
                raise SystemExit(0)
            if args and args[0] == "-":
                output = os.environ.get("HBCB_RELEASE_SUMMARY")
                if output:
                    Path(output).write_text('{"result":"PASS"}\n', encoding="utf-8")
                raise SystemExit(0)
            if not args:
                raise SystemExit(0)

            command = Path(args[0]).name
            def option(name: str) -> Path:
                return Path(args[args.index(name) + 1])

            if command == "release-audit":
                option("--report").write_text(
                    json.dumps({"git_head": "a" * 40}) + "\n", encoding="utf-8"
                )
            elif command in {"fetch-corresponding-source", "service-sbom"}:
                option("--output-dir").mkdir(parents=True, exist_ok=True)
            elif command == "release-artifacts":
                output = option("--output-dir")
                output.mkdir(parents=True, exist_ok=True)
                (output / "release-metadata.json").write_text("{}\n", encoding="utf-8")
            elif command == "minio-recipe-id":
                print("b" * 64)
            raise SystemExit(0)
            """,
        )
        self._write_executable(
            tools / "make",
            r"""
            #!/bin/sh
            printf 'make' >> "$HBCB_FAKE_LOG"
            printf ' %s' "$@" >> "$HBCB_FAKE_LOG"
            printf '\n' >> "$HBCB_FAKE_LOG"
            case "${1:-}" in
              init-env)
                : > .env
                ;;
              service-up)
                if [ "${HBCB_FAKE_FAIL_POINT:-}" = service-up ]; then
                  exit 42
                fi
                ;;
              service-smoke)
                mkdir -p build/service-smoke/fixture
                printf '{"result":"PASS"}\n' > \
                  build/service-smoke/fixture/g7-service-summary.json
                ;;
              g8-recovery)
                mkdir -p build/g8-recovery/fixture
                printf '{"result":"PASS"}\n' > \
                  build/g8-recovery/fixture/g8-recovery-summary.json
                ;;
            esac
            exit 0
            """,
        )
        real_ln = shutil.which("ln")
        if real_ln is None:
            self.fail("ln is unavailable")
        self._write_executable(
            tools / "ln",
            f"""
            #!/bin/sh
            if [ "${{HBCB_FAKE_SCENARIO:-}}" = summary-target-interloper ]; then
              printf '%s\n' foreign > "$2"
            fi
            {shlex.quote(real_ln)} "$@"
            status=$?
            if [ "$status" -eq 0 ] && \
               [ "${{HBCB_FAKE_SCENARIO:-}}" = summary-publish-signal ]; then
              kill -TERM "$PPID"
            fi
            exit "$status"
            """,
        )
        self._write_executable(
            tools / "docker",
            r"""
            #!/usr/bin/python3
            import os
            import signal
            import shlex
            import sys
            import time
            from pathlib import Path

            args = sys.argv[1:]
            scenario = os.environ.get("HBCB_FAKE_SCENARIO", "clean")
            state = Path(os.environ["HBCB_FAKE_STATE"])
            log = Path(os.environ["HBCB_FAKE_LOG"])
            with log.open("a", encoding="utf-8") as stream:
                stream.write("docker " + shlex.join(args) + "\n")

            def count(name: str) -> int:
                path = state / name
                value = int(path.read_text(encoding="ascii")) + 1 if path.exists() else 1
                path.write_text(str(value), encoding="ascii")
                return value

            if args == ["info"]:
                raise SystemExit(0)
            if args and args[0] == "ps" and any(
                item.startswith("label=com.docker.compose.project=") for item in args
            ):
                query = count("project-ps-count")
                if scenario == "initial-query-failure" and query == 1:
                    raise SystemExit(43)
                if scenario == "cleanup-query-failure" and query == 3:
                    raise SystemExit(44)
                if scenario == "pre-existing-project" and query == 1:
                    print("pre-existing-container")
                if scenario == "lingering-project" and query == 3:
                    print("lingering-container")
                raise SystemExit(0)
            if args and args[0] == "ps" and any(
                item.startswith("label=io.hbcb.release-service-owner=") for item in args
            ):
                query = int((state / "project-ps-count").read_text(encoding="ascii"))
                if scenario == "lingering-project" and query == 3:
                    print("different-container")
                raise SystemExit(0)
            if args[:2] == ["volume", "create"]:
                if scenario == "pre-existing-claim":
                    (state / "claim-interloper").write_text("1", encoding="ascii")
                    print("hbcb-release-check-claim")
                    raise SystemExit(0)
                (state / "claim-owned").write_text("1", encoding="ascii")
                print("hbcb-release-check-claim")
                raise SystemExit(0)
            if args[:3] == ["volume", "ls", "--quiet"]:
                if any(item.startswith("label=io.hbcb.release-claim-owner=") for item in args):
                    if (state / "claim-owned").exists():
                        print("hbcb-release-check-claim")
                    elif scenario == "final-signals-repeated" and (
                        state / "repeated-signals-started"
                    ).exists():
                        deadline = time.monotonic() + 5
                        while not (state / "repeated-signals-sent").exists():
                            if time.monotonic() >= deadline:
                                raise SystemExit("timed out sending repeated cleanup signals")
                            time.sleep(0.01)
                elif any(
                    item.startswith("label=io.hbcb.release-service-owner=")
                    for item in args
                ):
                    pass
                raise SystemExit(0)
            if args[:2] == ["volume", "inspect"]:
                if (state / "claim-owned").exists():
                    print("hbcb-release-check-claim|" + "d" * 32)
                elif (state / "claim-interloper").exists():
                    print("hbcb-release-check-claim|foreign-owner")
                else:
                    raise SystemExit(47)
                raise SystemExit(0)
            if args[:2] == ["volume", "rm"]:
                if scenario == "final-cleanup-failure":
                    raise SystemExit(48)
                cleanup_signals = {
                    "final-signal-hup": (signal.SIGHUP,),
                    "final-signal-int": (signal.SIGINT,),
                    "final-signal-term": (signal.SIGTERM,),
                    "final-signals-repeated": (signal.SIGTERM,),
                }.get(scenario, ())
                release_check_pid = os.getppid()
                for selected_signal in cleanup_signals:
                    try:
                        os.kill(release_check_pid, selected_signal)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                (state / "claim-owned").unlink(missing_ok=True)
                if scenario == "final-signals-repeated":
                    (state / "repeated-signals-started").write_text("1", encoding="ascii")
                    if os.fork() == 0:
                        time.sleep(0.2)
                        for selected_signal in (
                            signal.SIGHUP,
                            signal.SIGINT,
                            signal.SIGTERM,
                        ):
                            try:
                                os.kill(release_check_pid, selected_signal)
                            except ProcessLookupError:
                                break
                            time.sleep(0.05)
                        (state / "repeated-signals-sent").write_text(
                            "1", encoding="ascii"
                        )
                        os._exit(0)
                raise SystemExit(0)
            if args[:3] == ["network", "ls", "--quiet"]:
                raise SystemExit(0)
            if args and args[0] == "ps" and any(
                item.startswith("name=^/hbcb-release-runtime-sbom$") for item in args
            ):
                owner_query = any(
                    item.startswith("label=io.hbcb.release-builder-owner=") for item in args
                )
                if owner_query and (state / "builder-owned").exists():
                    print("b" * 64)
                elif not owner_query and (
                    (state / "builder-owned").exists()
                    or (state / "builder-interloper").exists()
                ):
                    print("b" * 64)
                raise SystemExit(0)
            if args[:2] == ["compose", "--project-name"]:
                raise SystemExit(0)
            if args and args[0] in {"tag", "build"}:
                raise SystemExit(0)
            if args[:2] == ["image", "inspect"]:
                print("[{}]")
                raise SystemExit(0)
            if args and args[0] == "create":
                if scenario == "create-interloper-failure":
                    (state / "builder-interloper").write_text("1", encoding="ascii")
                    raise SystemExit(45)
                (state / "builder-owned").write_text("1", encoding="ascii")
                if scenario == "create-owned-failure":
                    raise SystemExit(45)
                print("b" * 64)
                raise SystemExit(0)
            if args and args[0] == "cp":
                Path(args[-1]).write_text("{}\n", encoding="utf-8")
                raise SystemExit(0)
            if args and args[0] == "rm":
                (state / "builder-owned").unlink(missing_ok=True)
                raise SystemExit(0)
            raise SystemExit("unexpected fake Docker invocation: " + shlex.join(args))
            """,
        )

        subprocess.run(("git", "init", "-q"), cwd=checkout, check=True)
        subprocess.run(("git", "add", "."), cwd=checkout, check=True)
        subprocess.run(
            (
                "git",
                "-c",
                "user.name=Release Cleanup Test",
                "-c",
                "user.email=release-cleanup@example.invalid",
                "-c",
                "commit.gpgsign=false",
                "-c",
                "core.hooksPath=/dev/null",
                "commit",
                "-qm",
                "fixture",
            ),
            cwd=checkout,
            check=True,
        )
        return checkout, tools, state, temporary

    def _run(
        self,
        *,
        scenario: str,
        fail_point: str = "",
    ) -> tuple[subprocess.CompletedProcess[str], list[str], Path, list[Path]]:
        fixture = tempfile.TemporaryDirectory(prefix="hbcb-release-cleanup-")
        self.addCleanup(fixture.cleanup)
        parent = Path(fixture.name)
        checkout, tools, state, temporary = self._fixture(parent)
        log = state / "commands.log"
        completed = subprocess.run(
            ("sh", "scripts/release-check"),
            cwd=checkout,
            env={
                **os.environ,
                "DOCKER": str(tools / "docker"),
                "HBCB_FAKE_FAIL_POINT": fail_point,
                "HBCB_FAKE_LOG": str(log),
                "HBCB_FAKE_SCENARIO": scenario,
                "HBCB_FAKE_STATE": str(state),
                "HBCB_RELEASE_RUN_ID": "runtime",
                "PATH": str(tools) + os.pathsep + os.environ.get("PATH", ""),
                "PYTHON": str(tools / "python"),
                "TMPDIR": str(temporary),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        commands = log.read_text(encoding="utf-8").splitlines()
        scratch = list(temporary.glob("hbcb-release-check.*"))
        return completed, commands, state, scratch

    def test_refuses_pre_existing_exact_compose_project_without_cleanup(self) -> None:
        completed, commands, _state, scratch = self._run(
            scenario="pre-existing-project"
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("release Compose project already exists", completed.stdout)
        self.assertFalse(any(line.startswith("service-compose ") for line in commands))
        self.assertFalse(any(line.startswith("docker compose ") for line in commands))
        self.assertFalse(any(line.startswith("docker rm ") for line in commands))
        self.assertEqual(scratch, [])

    def test_initial_project_inventory_failure_is_fail_closed(self) -> None:
        completed, commands, _state, scratch = self._run(
            scenario="initial-query-failure"
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("project resources could not be inspected", completed.stdout)
        self.assertNotIn("isolated resource cleanup failed", completed.stdout)
        self.assertFalse(any(line.startswith("docker compose ") for line in commands))
        self.assertEqual(scratch, [])

    def test_cleanup_reports_down_failure(self) -> None:
        completed, commands, _state, scratch = self._run(
            scenario="cleanup-down-failure", fail_point="service-up"
        )
        self.assertEqual(completed.returncode, 42, completed.stdout)
        self.assertIn("isolated resource cleanup failed", completed.stdout)
        self.assertIn("service-compose down", commands)
        self.assertTrue(
            any(
                line.startswith("docker compose --project-name hbcb-release-runtime")
                and line.endswith("down --volumes --remove-orphans")
                for line in commands
            ),
            commands,
        )
        self.assertEqual(scratch, [])

    def test_cleanup_reports_lingering_exact_project_resource(self) -> None:
        completed, commands, _state, scratch = self._run(
            scenario="lingering-project", fail_point="service-up"
        )
        self.assertEqual(completed.returncode, 42, completed.stdout)
        self.assertIn("isolated resource cleanup failed", completed.stdout)
        project_queries = [
            line
            for line in commands
            if line.startswith("docker ps ")
            and "label=com.docker.compose.project=hbcb-release-runtime" in line
        ]
        self.assertEqual(len(project_queries), 4, commands)
        self.assertFalse(any(line.startswith("docker compose ") for line in commands))
        self.assertNotIn("service-compose down", commands)
        self.assertEqual(scratch, [])

    def test_cleanup_inventory_failure_is_fail_closed(self) -> None:
        completed, _commands, _state, scratch = self._run(
            scenario="cleanup-query-failure", fail_point="service-up"
        )
        self.assertEqual(completed.returncode, 42, completed.stdout)
        self.assertIn("isolated resource cleanup failed", completed.stdout)
        self.assertEqual(scratch, [])

    def test_failed_create_does_not_remove_an_exact_name_interloper(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="create-interloper-failure"
        )
        self.assertEqual(completed.returncode, 45, completed.stdout)
        self.assertNotIn("isolated resource cleanup failed", completed.stdout)
        create = next(line for line in commands if line.startswith("docker create "))
        self.assertIn("--name hbcb-release-runtime-sbom", create)
        self.assertIn("--label io.hbcb.release-builder-owner=", create)
        self.assertFalse(any(line.startswith("docker rm ") for line in commands))
        self.assertTrue(
            any(
                line.startswith("docker ps --all --no-trunc --quiet")
                and "name=^/hbcb-release-runtime-sbom$" in line
                and "label=io.hbcb.release-builder-owner=" in line
                for line in commands
            ),
            commands,
        )
        self.assertTrue((state / "builder-interloper").exists())
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_failed_create_removes_only_a_labeled_owned_container(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="create-owned-failure"
        )
        self.assertEqual(completed.returncode, 45, completed.stdout)
        self.assertIn("docker rm --force " + "b" * 64, commands)
        self.assertFalse((state / "builder-owned").exists())
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_pre_existing_global_claim_is_not_removed(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="pre-existing-claim"
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("another full release check owns this Docker daemon", completed.stdout)
        self.assertFalse(any(line.startswith("docker volume rm ") for line in commands))
        self.assertTrue((state / "claim-interloper").exists())
        self.assertEqual(scratch, [])

    def test_clean_fake_release_succeeds_and_cleanup_is_verified(self) -> None:
        completed, commands, state, scratch = self._run(scenario="clean")
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("RELEASE_CHECK: PASS", completed.stdout)
        self.assertNotIn("isolated resource cleanup failed", completed.stdout)
        self.assertIn("docker rm " + "b" * 64, commands)
        self.assertIn("docker volume rm hbcb-release-check-claim", commands)
        self.assertIn("service-compose down", commands)
        self.assertFalse((state / "builder-owned").exists())
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_final_cleanup_failure_never_publishes_pass_summary_or_marker(self) -> None:
        completed, _commands, state, scratch = self._run(
            scenario="final-cleanup-failure"
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("isolated resource cleanup failed", completed.stdout)
        self.assertNotIn("RELEASE_CHECK: PASS", completed.stdout)
        checkout = state.parent / "checkout"
        evidence = checkout / "build" / "release-check" / "runtime"
        self.assertFalse((evidence / "release-check-summary.json").exists())
        self.assertFalse((evidence / "release-check-summary.pending").exists())
        self.assertEqual(scratch, [])

    def test_final_cleanup_defers_each_signal_and_never_publishes_pass(self) -> None:
        for name, expected in (
            ("hup", 128 + signal.SIGHUP),
            ("int", 128 + signal.SIGINT),
            ("term", 128 + signal.SIGTERM),
        ):
            with self.subTest(signal=name):
                completed, commands, state, scratch = self._run(
                    scenario=f"final-signal-{name}"
                )
                self.assertEqual(completed.returncode, expected, completed.stdout)
                self.assertNotIn("RELEASE_CHECK: PASS", completed.stdout)
                checkout = state.parent / "checkout"
                evidence = checkout / "build" / "release-check" / "runtime"
                self.assertFalse((evidence / "release-check-summary.json").exists())
                self.assertFalse((evidence / "release-check-summary.pending").exists())
                self.assertIn("service-compose down", commands)
                self.assertIn("docker volume rm hbcb-release-check-claim", commands)
                self.assertFalse((state / "claim-owned").exists())
                self.assertEqual(scratch, [])

    def test_final_cleanup_preserves_first_of_repeated_different_signals(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="final-signals-repeated"
        )
        self.assertEqual(completed.returncode, 128 + signal.SIGTERM, completed.stdout)
        self.assertNotIn("RELEASE_CHECK: PASS", completed.stdout)
        checkout = state.parent / "checkout"
        evidence = checkout / "build" / "release-check" / "runtime"
        self.assertFalse((evidence / "release-check-summary.json").exists())
        self.assertFalse((evidence / "release-check-summary.pending").exists())
        self.assertIn("service-compose down", commands)
        self.assertIn("docker volume rm hbcb-release-check-claim", commands)
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_signal_during_summary_promotion_invalidates_both_summary_forms(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="summary-publish-signal"
        )
        self.assertEqual(completed.returncode, 128 + signal.SIGTERM, completed.stdout)
        self.assertNotIn("RELEASE_CHECK: PASS", completed.stdout)
        checkout = state.parent / "checkout"
        evidence = checkout / "build" / "release-check" / "runtime"
        self.assertFalse((evidence / "release-check-summary.json").exists())
        self.assertFalse((evidence / "release-check-summary.pending").exists())
        self.assertIn("service-compose down", commands)
        self.assertIn("docker volume rm hbcb-release-check-claim", commands)
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_summary_promotion_never_clobbers_an_interloper(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="summary-target-interloper"
        )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertNotIn("RELEASE_CHECK: PASS", completed.stdout)
        checkout = state.parent / "checkout"
        evidence = checkout / "build" / "release-check" / "runtime"
        target = evidence / "release-check-summary.json"
        self.assertEqual(target.read_text(encoding="utf-8"), "foreign\n")
        self.assertFalse((evidence / "release-check-summary.pending").exists())
        self.assertIn("service-compose down", commands)
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])

    def test_automatic_exit_cleanup_defers_a_signal_until_teardown_finishes(self) -> None:
        completed, commands, state, scratch = self._run(
            scenario="automatic-exit-signal", fail_point="service-up"
        )
        self.assertEqual(completed.returncode, 42, completed.stdout)
        self.assertIn("service-compose down", commands)
        self.assertIn("docker volume rm hbcb-release-check-claim", commands)
        self.assertFalse((state / "claim-owned").exists())
        self.assertEqual(scratch, [])


if __name__ == "__main__":
    unittest.main()
