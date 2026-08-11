from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
IMAGE_ID = "sha256:" + "a" * 64

FAKE_DOCKER = r"""#!/bin/sh
set -eu
: "${FAKE_DOCKER_LOG:?}"
first=1
for argument do
  if [ "$first" = 0 ]; then printf '\t' >> "$FAKE_DOCKER_LOG"; fi
  first=0
  printf '%s' "$argument" >> "$FAKE_DOCKER_LOG"
done
printf '\n' >> "$FAKE_DOCKER_LOG"

if [ "${1:-}" = image ] && [ "${2:-}" = inspect ]; then
  case "$*" in
    *'{{.Os}}/{{.Architecture}}|{{.Id}}'*)
      printf '%s\n' "linux/amd64|${FAKE_IMAGE_ID:?}"
      ;;
    *)
      printf '%s\n' 'linux/amd64'
      ;;
  esac
fi
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


class MakefileBuilderTargetTests(unittest.TestCase):
    def fixture(
        self, temporary: str
    ) -> tuple[dict[str, str], Path, Path, Path, Path]:
        root = Path(temporary)
        docker = root / "docker"
        docker_log = root / "docker.log"
        request = root / "request.json"
        build_parent = root / "artifacts"
        write_executable(docker, FAKE_DOCKER)
        request.write_bytes(
            (ROOT / "examples" / "requests" / "facet-bot.json").read_bytes()
        )
        environment = os.environ.copy()
        environment.pop("OUTPUT_NAME", None)
        environment.update(
            {
                "FAKE_DOCKER_LOG": str(docker_log),
                "FAKE_IMAGE_ID": IMAGE_ID,
            }
        )
        return environment, docker, docker_log, request, build_parent

    def run_make(
        self,
        target: str,
        *,
        environment: dict[str, str],
        docker: Path,
        request: Path,
        build_parent: Path,
        output_name: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            "make",
            target,
            f"DOCKER={docker}",
            "BUILDER_IMAGE=fixture-builder:dev",
            "PLATFORM=linux/amd64",
            f"REQUEST={request}",
            f"BUILD_PARENT={build_parent}",
        ]
        if output_name is not None:
            command.append(f"OUTPUT_NAME={output_name}")
        return subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_build_and_verify_use_validated_named_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-make-output-") as temporary:
            environment, docker, docker_log, request, build_parent = self.fixture(
                temporary
            )
            built = self.run_make(
                "build",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
                output_name="custom-model",
            )
            self.assertEqual(built.returncode, 0, built.stdout)
            records = [
                line.split("\t")
                for line in docker_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record[0] for record in records], ["build", "image", "run"])
            run = records[-1]
            self.assertIn(
                f"type=bind,source={request},target=/input/request.json,readonly", run
            )
            self.assertIn(f"type=bind,source={build_parent},target=/output", run)
            self.assertEqual(run[-2:], ["--output", "/output/custom-model"])

            (build_parent / "custom-model").mkdir()
            docker_log.unlink()
            verified = self.run_make(
                "verify",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
                output_name="custom-model",
            )
            self.assertEqual(verified.returncode, 0, verified.stdout)
            records = [
                line.split("\t")
                for line in docker_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record[0] for record in records], ["image", "run"])
            run = records[-1]
            self.assertIn(
                f"type=bind,source={build_parent},target=/output,readonly", run
            )
            self.assertEqual(run[-2:], ["--output", "/output/custom-model"])

    def test_demo_targets_remain_aliases_for_demo_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-make-demo-") as temporary:
            environment, docker, docker_log, request, build_parent = self.fixture(
                temporary
            )
            built = self.run_make(
                "demo",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
                output_name="caller-value-must-not-win",
            )
            self.assertEqual(built.returncode, 0, built.stdout)
            records = [
                line.split("\t")
                for line in docker_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[-1][-2:], ["--output", "/output/demo"])

            (build_parent / "demo").mkdir()
            docker_log.unlink()
            verified = self.run_make(
                "verify-demo",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
                output_name="caller-value-must-not-win",
            )
            self.assertEqual(verified.returncode, 0, verified.stdout)
            records = [
                line.split("\t")
                for line in docker_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[-1][-2:], ["--output", "/output/demo"])

    def test_unsafe_output_names_fail_before_docker_or_filesystem_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-make-reject-") as temporary:
            environment, docker, docker_log, request, build_parent = self.fixture(
                temporary
            )
            canary = Path(temporary) / "injected"
            unsafe = (
                "",
                "Uppercase",
                "two--parts",
                "-leading",
                "trailing-",
                "../escape",
                "a" * 49,
                f'bad"; touch {canary}; #',
            )
            for output_name in unsafe:
                with self.subTest(output_name=output_name):
                    rejected = self.run_make(
                        "build",
                        environment=environment,
                        docker=docker,
                        request=request,
                        build_parent=build_parent,
                        output_name=output_name,
                    )
                    self.assertNotEqual(rejected.returncode, 0, rejected.stdout)
                    self.assertIn("OUTPUT_NAME must be", rejected.stdout)
                    self.assertFalse(build_parent.exists())
                    self.assertFalse(docker_log.exists())
                    self.assertFalse(canary.exists())

            accepted = self.run_make(
                "_validate-output-name",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
                output_name="a" * 48,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_make_validate_uses_hardened_keyless_container_with_request_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-make-validate-") as temporary:
            environment, docker, docker_log, request, build_parent = self.fixture(
                temporary
            )
            secrets = ("make-validate-provider-canary", "validate-secret-canary")
            environment.update(
                {
                    "OPENAI_API_KEY": secrets[0],
                    "HBCB_CANARY_SECRET": secrets[1],
                }
            )
            valid = self.run_make(
                "validate",
                environment=environment,
                docker=docker,
                request=request,
                build_parent=build_parent,
            )
            self.assertEqual(valid.returncode, 0, valid.stdout)
            records = [
                line.split("\t")
                for line in docker_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([record[0] for record in records], ["image", "run"])
            run = records[-1]
            self.assertEqual(run[-3:], ["validate", "--request", "/input/request.json"])
            self.assertEqual(
                [run[index + 1] for index, value in enumerate(run) if value == "--mount"],
                [f"type=bind,source={request},target=/input/request.json,readonly"],
            )
            for required in (
                "--rm",
                "--init",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--network",
                "none",
                "--pids-limit",
                "64",
                "--cpus",
                "1",
                "--memory",
                "512m",
                "--tmpfs",
                "/work:rw,nosuid,nodev,noexec,size=64m,mode=1777",
            ):
                self.assertIn(required, run)
            runtime_user = run[run.index("--user") + 1]
            self.assertNotEqual(runtime_user.split(":", 1)[0], "0")
            self.assertNotIn("--output", run)
            self.assertNotIn("--env", run)
            self.assertFalse(any("target=/output" in value for value in run))
            self.assertNotIn("blender", run)
            self.assertFalse(any(value.endswith("/blender") for value in run))
            logged = docker_log.read_text(encoding="utf-8")
            for secret in secrets:
                self.assertNotIn(secret, logged)
            self.assertFalse(build_parent.exists())


if __name__ == "__main__":
    unittest.main()
