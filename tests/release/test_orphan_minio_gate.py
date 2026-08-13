from __future__ import annotations

import ast
import os
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "tests" / "service_integration" / "g8_orphan_minio_gate.py"
COMPOSE = ROOT / "tests" / "service_integration" / "g8_orphan_minio_compose.yaml"
WRAPPER = ROOT / "scripts" / "orphan-minio-gate"


class OrphanMinioGateContractTests(unittest.TestCase):
    def test_gate_is_wired_and_covers_the_live_exact_version_contract(self) -> None:
        source = GATE.read_text(encoding="utf-8")
        ast.parse(source, filename=str(GATE))
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        compose = COMPOSE.read_text(encoding="utf-8")
        wrapper = WRAPPER.read_text(encoding="utf-8")
        release = (ROOT / "scripts" / "release-check").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertRegex(makefile, r"(?m)^orphan-minio-check:\n\t.*orphan-minio-gate")
        service_recipe = makefile[
            makefile.index("service-smoke:") : makefile.index("orphan-minio-check:")
        ]
        self.assertNotIn("orphan-minio-gate", service_recipe)
        self.assertIn("make orphan-minio-check", release)
        self.assertIn('"real-orphan-object-lifecycle"', release)
        self.assertIn("make orphan-minio-check", workflow)
        self.assertIn('HBCB_LIFECYCLE_DESTRUCTIVE_DISPOSABLE: "1"', compose)
        self.assertIn("g8_orphan_minio_gate.py", compose)
        self.assertNotRegex(compose, r"(?m)^name:")
        self.assertIn("--volumes --remove-orphans", wrapper)
        self.assertIn("project_resources", wrapper)
        self.assertIn(") || return 1", wrapper)
        self.assertIn("initial_resources=$(project_resources) ||", wrapper)
        self.assertIn("remaining_resources=$(project_resources 2>/dev/null) ||", wrapper)
        self.assertIn("trap 'record_signal 1' 1", wrapper)
        self.assertIn("trap 'record_signal 2' 2", wrapper)
        self.assertIn("trap 'record_signal 15' 15", wrapper)
        self.assertNotIn("trap '' 1 2 15", wrapper)
        self.assertNotIn("trap 'exit 129' 1", wrapper)
        self.assertNotIn("trap 'exit 130' 2", wrapper)
        self.assertNotIn("trap 'exit 143' 15", wrapper)
        self.assertIn("cleanup_complete=1", wrapper)
        transition = wrapper.index("cleanup_complete=1")
        publication = wrapper.index("printf '%s\\n' \"$gate_output\"")
        self.assertLess(transition, publication)
        self.assertIn(
            'if [ "$pending_signal" -ne 0 ]; then',
            wrapper[transition:publication],
        )
        self.assertIn("scope=disposable", wrapper)
        self.assertIn('--project-name "$project"', wrapper)
        self.assertIn("project=hbcb-orphan-$(random_hex 6)", wrapper)
        self.assertEqual(stat.S_IMODE(WRAPPER.stat().st_mode), 0o755)
        self.assertNotIn("ports:", compose)
        self.assertIn("internal: true", compose)
        for required in (
            "baseline_orphans_present",
            '{"InvalidAccessKeyId", "AccessDenied"}',
            "after_readiness_window",
            "discover-orphans",
            "orphan_preview_mutated_database",
            "durable_queue_",
            "orphan_inventory_modified",
            "delete-artifacts",
            "run_maintenance_cli",
            "exact_version_absent",
            "referenced_version_did_not_survive",
            "cleanup_versions",
            "cleanup_database",
        ):
            self.assertIn(required, source)
        self.assertGreaterEqual(source.count("include_version=True"), 2)
        self.assertGreaterEqual(source.count("version_id="), 5)

    def test_gate_mutation_scope_is_bound_to_one_random_build(self) -> None:
        source = GATE.read_text(encoding="utf-8")
        self.assertIn("build_id = uuid4()", source)
        self.assertIn("WHERE namespace = %s AND build_id = %s", source)
        self.assertIn("if getattr(item, \"object_name\", None) != key", source)
        self.assertNotIn("remove_bucket", source)
        self.assertNotIn("DELETE FROM hbcb.builds WHERE namespace = %s\"", source)

    def _signal_fixture(
        self,
        scenario: str,
    ) -> tuple[subprocess.CompletedProcess[str], Path, list[str]]:
        fixture = tempfile.TemporaryDirectory(prefix="hbcb-orphan-minio-signal-")
        self.addCleanup(fixture.cleanup)
        root = Path(fixture.name)
        checkout = root / "checkout"
        scripts = checkout / "scripts"
        integration = checkout / "tests" / "service_integration"
        tools = root / "tools"
        state = root / "state"
        scripts.mkdir(parents=True)
        integration.mkdir(parents=True)
        tools.mkdir()
        state.mkdir()
        (scripts / "orphan-minio-gate").write_bytes(WRAPPER.read_bytes())
        (scripts / "orphan-minio-gate").chmod(0o755)
        (scripts / "service-common").write_bytes(
            (ROOT / "scripts" / "service-common").read_bytes()
        )
        (integration / "g8_orphan_minio_compose.yaml").write_text(
            "services:\n  gate:\n    image: fixture\n",
            encoding="ascii",
        )
        docker = tools / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            + textwrap.dedent(
                """
                import json
                import os
                import pathlib
                import signal
                import sys
                import time

                args = sys.argv[1:]
                state = pathlib.Path(os.environ["FAKE_DOCKER_STATE"])
                log = state / "commands.log"
                with log.open("a", encoding="utf-8") as stream:
                    stream.write(" ".join(args) + "\\n")
                resource = state / "project-resource"
                scenario = os.environ.get("FAKE_DOCKER_SCENARIO", "")

                if args == ["info"]:
                    raise SystemExit(0)
                if args[:2] == ["image", "inspect"]:
                    print("linux/amd64|sha256:" + "a" * 64)
                    raise SystemExit(0)
                if args and args[0] == "ps":
                    if resource.exists():
                        print("c" * 64)
                    elif scenario == "repeated" and (state / "cleanup-started").exists():
                        os.kill(os.getppid(), signal.SIGHUP)
                        time.sleep(0.05)
                    raise SystemExit(0)
                if args[:2] == ["volume", "ls"]:
                    if resource.exists():
                        print("fixture-volume")
                    elif scenario == "repeated" and (state / "cleanup-started").exists():
                        os.kill(os.getppid(), signal.SIGINT)
                        time.sleep(0.05)
                    raise SystemExit(0)
                if args[:2] == ["network", "ls"]:
                    if resource.exists():
                        print("fixture-network")
                    raise SystemExit(0)
                if args and args[0] == "compose":
                    operation = next(
                        (item for item in ("config", "up", "run", "down") if item in args),
                        None,
                    )
                    if operation == "config":
                        print("services: {}")
                    elif operation == "up":
                        resource.write_text("owned", encoding="ascii")
                    elif operation == "run":
                        print(json.dumps({
                            "deleted_orphan_versions": 1,
                            "dry_run_candidates": 1,
                            "gate": "G8_ORPHAN_MINIO_GATE",
                            "queued_exact_versions": 1,
                            "referenced_versions_survived": 1,
                            "result": "PASS",
                        }, sort_keys=True, separators=(",", ":")))
                    elif operation == "down":
                        (state / "cleanup-started").write_text("1", encoding="ascii")
                        selected = {
                            "hup": (signal.SIGHUP,),
                            "int": (signal.SIGINT,),
                            "term": (signal.SIGTERM,),
                            "repeated": (signal.SIGTERM, signal.SIGTERM),
                        }.get(scenario, ())
                        for signum in selected:
                            os.kill(os.getppid(), signum)
                            time.sleep(0.05)
                        time.sleep(0.1)
                        resource.unlink(missing_ok=True)
                    raise SystemExit(0)
                raise SystemExit("unexpected fake Docker invocation: " + " ".join(args))
                """
            ),
            encoding="utf-8",
        )
        docker.chmod(0o755)
        completed = subprocess.run(
            ("sh", "scripts/orphan-minio-gate"),
            cwd=checkout,
            env={
                **os.environ,
                "DOCKER": str(docker),
                "PYTHON": sys.executable,
                "FAKE_DOCKER_STATE": str(state),
                "FAKE_DOCKER_SCENARIO": scenario,
            },
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
        commands = (state / "commands.log").read_text(encoding="utf-8").splitlines()
        return completed, state, commands

    @unittest.skipUnless(os.name == "posix", "POSIX signal semantics required")
    def test_cleanup_records_each_signal_then_verifies_absence_without_pass(self) -> None:
        for name, expected in (
            ("hup", 128 + signal.SIGHUP),
            ("int", 128 + signal.SIGINT),
            ("term", 128 + signal.SIGTERM),
        ):
            with self.subTest(signal=name):
                completed, state, commands = self._signal_fixture(name)
                self.assertEqual(completed.returncode, expected, completed.stdout)
                self.assertNotIn("ORPHAN_MINIO_GATE: PASS", completed.stdout)
                self.assertNotIn('"result":"PASS"', completed.stdout)
                self.assertFalse((state / "project-resource").exists())
                down = next(index for index, command in enumerate(commands) if " down " in f" {command} ")
                self.assertTrue(any(command.startswith("ps ") for command in commands[down + 1 :]))
                self.assertTrue(
                    any(command.startswith("volume ls ") for command in commands[down + 1 :])
                )
                self.assertTrue(
                    any(command.startswith("network ls ") for command in commands[down + 1 :])
                )

    @unittest.skipUnless(os.name == "posix", "POSIX signal semantics required")
    def test_cleanup_preserves_first_of_repeated_different_signals(self) -> None:
        completed, state, _commands = self._signal_fixture("repeated")
        self.assertEqual(completed.returncode, 128 + signal.SIGTERM, completed.stdout)
        self.assertNotIn("ORPHAN_MINIO_GATE: PASS", completed.stdout)
        self.assertNotIn('"result":"PASS"', completed.stdout)
        self.assertFalse((state / "project-resource").exists())


if __name__ == "__main__":
    unittest.main()
