from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_SMOKE = ROOT / "scripts" / "service-smoke"
SERVICE_COMMON = ROOT / "scripts" / "service-common"
IMAGE_ID = "sha256:" + "a" * 64


def write_executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    return path


class ServiceSmokeRuntimeTests(unittest.TestCase):
    def checkout(self, root: Path) -> Path:
        (root / "scripts").mkdir()
        copied = root / "scripts" / "service-smoke"
        shutil.copyfile(SERVICE_SMOKE, copied)
        copied.chmod(0o700)
        (root / "scripts" / "service-common").write_text(
            """
hbcb_service_settings() {
  HBCB_COMPOSE_PROJECT_NAME=hbcb-test-project
  COMPOSE_PROJECT_NAME=$HBCB_COMPOSE_PROJECT_NAME
  HBCB_API_HOST_PORT=18080
  HBCB_STORAGE_HOST_PORT=19000
  HBCB_STORAGE_PUBLIC_ENDPOINT=localhost:19000
  HBCB_MINIO_IMAGE=hbcb-test-minio:dev
  HBCB_SERVICE_API_IMAGE=hbcb-test-api:dev
  HBCB_SERVICE_WORKER_IMAGE=hbcb-test-worker:dev
  HBCB_SERVICE_TEST_IMAGE=hbcb-test-service-test:dev
  HBCB_BUILDER_PROJECT_IMAGE=hbcb-test-builder:dev
  export HBCB_COMPOSE_PROJECT_NAME COMPOSE_PROJECT_NAME
  export HBCB_API_HOST_PORT HBCB_STORAGE_HOST_PORT
  export HBCB_STORAGE_PUBLIC_ENDPOINT HBCB_MINIO_IMAGE
  export HBCB_SERVICE_API_IMAGE HBCB_SERVICE_WORKER_IMAGE
  export HBCB_SERVICE_TEST_IMAGE HBCB_BUILDER_PROJECT_IMAGE
}
hbcb_service_env_private() {
  return 0
}
hbcb_service_identity() {
  printf 'SERVICE_COMPOSE: project=%s api=127.0.0.1:%s storage=127.0.0.1:%s\n' \
    "$HBCB_COMPOSE_PROJECT_NAME" "$HBCB_API_HOST_PORT" "$HBCB_STORAGE_HOST_PORT"
}
""",
            encoding="utf-8",
        )
        environment = root / ".env"
        environment.write_text("HBCB_API_TOKEN=fixture\n", encoding="utf-8")
        environment.chmod(0o600)
        return copied

    def test_nonprivate_env_fails_before_docker_or_output_creation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-env-") as raw:
            root = Path(raw)
            script = self.checkout_with_real_settings(root)
            (root / ".env").chmod(0o644)
            tools = root / "tools"
            tools.mkdir()
            python = write_executable(
                tools / "selected-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            docker_log = root / "docker.log"
            docker = write_executable(
                tools / "selected-docker",
                f"printf '%s\\n' \"$*\" >> {docker_log}\nexit 88\n",
            )
            completed = subprocess.run(
                (str(script),),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 3, completed.stdout)
            self.assertIn("owned mode-0600 regular file", completed.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse((root / "build").exists())

    def checkout_with_real_settings(self, root: Path) -> Path:
        (root / "scripts").mkdir()
        copied = root / "scripts" / "service-smoke"
        shutil.copyfile(SERVICE_SMOKE, copied)
        copied.chmod(0o700)
        shutil.copyfile(SERVICE_COMMON, root / "scripts" / "service-common")
        environment = root / ".env"
        environment.write_text(
            "HBCB_COMPOSE_PROJECT_NAME=hbcb-persisted\n"
            "HBCB_API_HOST_PORT=18080\n"
            "HBCB_STORAGE_HOST_PORT=19000\n"
            "HBCB_API_TOKEN=fixture\n",
            encoding="utf-8",
        )
        environment.chmod(0o600)
        return copied

    def test_python_below_311_fails_before_docker_or_output_creation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-python-") as raw:
            root = Path(raw)
            script = self.checkout(root)
            tools = root / "tools"
            tools.mkdir()
            python = write_executable(
                tools / "selected-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.10.14' ;;
  -c) exit 1 ;;
  *) exit 9 ;;
esac
""",
            )
            docker_log = root / "docker.log"
            docker = write_executable(
                tools / "selected-docker",
                f"printf '%s\\n' \"$*\" >> {docker_log}\nexit 88\n",
            )
            completed = subprocess.run(
                (str(script),),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 3, completed.stdout)
            self.assertIn("Python 3.11+ is required", completed.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse((root / "build").exists())

    def test_option_like_tools_and_builder_fail_before_docker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-options-") as raw:
            root = Path(raw)
            script = self.checkout(root)
            tools = root / "tools"
            tools.mkdir()
            python = write_executable(
                tools / "selected-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            docker_log = root / "docker.log"
            docker = write_executable(
                tools / "selected-docker",
                f"printf '%s\\n' \"$*\" >> {docker_log}\nexit 88\n",
            )
            for overrides in (
                {"PYTHON": "--DoNotEchoPython", "DOCKER": str(docker)},
                {"PYTHON": str(python), "DOCKER": "--DoNotEchoDocker"},
                {
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                    "BUILDER_IMAGE": "--DoNotEchoBuilder",
                },
            ):
                with self.subTest(overrides=tuple(sorted(overrides))):
                    completed = subprocess.run(
                        (str(script),),
                        cwd=root,
                        env={"PATH": os.environ.get("PATH", ""), **overrides},
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
                    self.assertNotIn("DoNotEcho", completed.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse((root / "build").exists())

    def test_selected_python_docker_project_and_ports_flow_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-runtime-") as raw:
            root = Path(raw)
            script = self.checkout(root)
            tools = root / "tools"
            tools.mkdir()
            python_log = root / "python.log"
            docker_log = root / "docker.log"
            compose_log = root / "compose.log"
            python = write_executable(
                tools / "selected-python",
                f"""
printf '%s\n' "$*" >> {python_log}
case "${{1:-}}" in
  --version) printf '%s\n' 'Python 3.11.9 selected' ;;
  -c) exit 0 ;;
  tests/service_integration/g7_service_smoke.py)
    printf 'DOCKER=%s\n' "${{DOCKER:-}}" >> {python_log}
    printf 'PYTHON=%s\n' "${{PYTHON:-}}" >> {python_log}
    exit 0
    ;;
  *) exit 9 ;;
esac
""",
            )
            docker = write_executable(
                tools / "selected-docker",
                f"""
printf '%s\n' "$*" >> {docker_log}
case "${{1:-}}:${{2:-}}" in
  image:inspect) printf '%s\n' 'linux/amd64|{IMAGE_ID}' ;;
  run:*) exit 0 ;;
  *) exit 89 ;;
esac
""",
            )
            compose = write_executable(
                tools / "selected-compose",
                f"printf '%s\\n' \"$*\" >> {compose_log}\n",
            )
            completed = subprocess.run(
                (str(script),),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                    "HBCB_COMPOSE_BIN": str(compose),
                    "BUILDER_IMAGE": "headless-blender-character-builder:dev",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn(
                "SERVICE_SMOKE: PASS project=hbcb-test-project", completed.stdout
            )
            python_calls = python_log.read_text(encoding="utf-8")
            for expected in (
                "--base-url http://127.0.0.1:18080",
                "--api-port 18080",
                "--storage-port 19000",
                "--compose-project hbcb-test-project",
                f"DOCKER={docker}",
                f"PYTHON={python}",
            ):
                self.assertIn(expected, python_calls)
            docker_calls = docker_log.read_text(encoding="utf-8")
            self.assertIn("image inspect", docker_calls)
            self.assertIn("hbcb-test-builder:dev", docker_calls)
            compose_calls = compose_log.read_text(encoding="utf-8")
            self.assertEqual(compose_calls.count("--project-name hbcb-test-project"), 3)
            self.assertIn("tests/service_integration/g8_lifecycle_gate.py", compose_calls)

    def test_explicit_custom_builder_reference_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-builder-") as raw:
            root = Path(raw)
            script = self.checkout(root)
            tools = root / "tools"
            tools.mkdir()
            python = write_executable(
                tools / "selected-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c|tests/service_integration/g7_service_smoke.py) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            docker_log = root / "docker.log"
            docker = write_executable(
                tools / "selected-docker",
                f"""
printf '%s\n' "$*" >> {docker_log}
case "${{1:-}}:${{2:-}}" in
  image:inspect) printf '%s\n' 'linux/amd64|{IMAGE_ID}' ;;
  run:*) exit 0 ;;
  *) exit 89 ;;
esac
""",
            )
            compose = write_executable(tools / "selected-compose", "exit 0\n")
            custom = "registry.example/hbcb-builder@sha256:" + "b" * 64
            completed = subprocess.run(
                (str(script),),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                    "HBCB_COMPOSE_BIN": str(compose),
                    "BUILDER_IMAGE": custom,
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            calls = docker_log.read_text(encoding="utf-8")
            self.assertIn(f"image inspect --format {{{{.Os}}}}/{{{{.Architecture}}}}|{{{{.Id}}}} {custom}", calls)
            self.assertIn(custom, calls)
            self.assertNotIn("hbcb-test-builder:dev", calls)

    def test_release_project_override_keeps_ports_persisted_in_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-smoke-release-") as raw:
            root = Path(raw)
            script = self.checkout_with_real_settings(root)
            tools = root / "tools"
            tools.mkdir()
            python_log = root / "python.log"
            docker_log = root / "docker.log"
            compose_log = root / "compose.log"
            python = write_executable(
                tools / "selected-python",
                f"""
printf '%s\n' "$*" >> {python_log}
case "${{1:-}}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c|tests/service_integration/g7_service_smoke.py) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            docker = write_executable(
                tools / "selected-docker",
                f"""
printf '%s\n' "$*" >> {docker_log}
case "${{1:-}}:${{2:-}}" in
  image:inspect) printf '%s\n' 'linux/amd64|{IMAGE_ID}' ;;
  run:*) exit 0 ;;
  *) exit 89 ;;
esac
""",
            )
            compose = write_executable(
                tools / "selected-compose",
                f"printf '%s\\n' \"$*\" >> {compose_log}\n",
            )
            completed = subprocess.run(
                (str(script),),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHON": str(python),
                    "DOCKER": str(docker),
                    "HBCB_COMPOSE_BIN": str(compose),
                    "COMPOSE_PROJECT_NAME": "hbcb-release-fixture",
                    "BUILDER_IMAGE": "headless-blender-character-builder:dev",
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertIn(
                "SERVICE_SMOKE: PASS project=hbcb-release-fixture",
                completed.stdout,
            )
            python_calls = python_log.read_text(encoding="utf-8")
            for expected in (
                "--base-url http://127.0.0.1:18080",
                "--api-port 18080",
                "--storage-port 19000",
                "--compose-project hbcb-release-fixture",
            ):
                self.assertIn(expected, python_calls)
            self.assertIn(
                "hbcb-release-fixture-builder:dev",
                docker_log.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                compose_log.read_text(encoding="utf-8").count(
                    "--project-name hbcb-release-fixture"
                ),
                3,
            )


if __name__ == "__main__":
    unittest.main()
