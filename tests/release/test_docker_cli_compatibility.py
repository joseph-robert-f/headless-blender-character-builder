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
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"

if [ "${1:-}" = image ] && [ "${2:-}" = inspect ]; then
  shift 2
  format=
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --platform)
        printf '%s\n' 'unknown flag: --platform' >&2
        exit 125
        ;;
      --format)
        shift
        format=${1:-}
        ;;
    esac
    shift
  done
  platform=${FAKE_IMAGE_PLATFORM:-linux/amd64}
  image_id=${FAKE_IMAGE_ID:-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa}
  case "$format" in
    '{{.Os}}/{{.Architecture}}') printf '%s\n' "$platform" ;;
    '{{.Os}}/{{.Architecture}}|{{.Id}}') printf '%s|%s\n' "$platform" "$image_id" ;;
    '{{.Id}}') printf '%s\n' "$image_id" ;;
    *)
      os_name=${platform%/*}
      architecture=${platform#*/}
      printf '[{"Os":"%s","Architecture":"%s","Id":"%s"}]\n' \
        "$os_name" "$architecture" "$image_id"
      ;;
  esac
  exit 0
fi

case "${1:-}" in
  build|run|create|cp|rm|tag|compose) exit 0 ;;
esac
printf '%s\n' "unexpected fake Docker command: $*" >&2
exit 64
"""

FAKE_COMPOSE = r"""#!/bin/sh
set -eu
: "${FAKE_COMPOSE_LOG:?}"
printf '%s|%s|%s|%s\n' \
  "$*" \
  "${HBCB_BUILDER_IMAGE:-}" \
  "${HBCB_BUILDER_IMAGE_REFERENCE:-}" \
  "${HBCB_BUILDER_IMAGE_ID:-}" >> "$FAKE_COMPOSE_LOG"
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


class DockerCliCompatibilityTests(unittest.TestCase):
    def environment(
        self, root: Path, *, platform: str
    ) -> tuple[dict[str, str], Path, Path, Path, Path]:
        binary_dir = root / "bin"
        binary_dir.mkdir()
        docker = binary_dir / "docker"
        compose = binary_dir / "compose"
        write_executable(docker, FAKE_DOCKER)
        write_executable(compose, FAKE_COMPOSE)
        docker_log = root / "docker.log"
        compose_log = root / "compose.log"
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": str(binary_dir) + os.pathsep + environment.get("PATH", ""),
                "FAKE_DOCKER_LOG": str(docker_log),
                "FAKE_COMPOSE_LOG": str(compose_log),
                "FAKE_IMAGE_ID": IMAGE_ID,
                "FAKE_IMAGE_PLATFORM": platform,
                "HBCB_COMPOSE_BIN": str(compose),
                "BUILDER_IMAGE": "fixture-builder:dev",
            }
        )
        return environment, docker, compose, docker_log, compose_log

    def test_legacy_inspect_cli_reuses_amd64_image_and_resolves_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker, _compose, docker_log, compose_log = self.environment(
                root, platform="linux/amd64"
            )
            (root / ".env").write_text("# fixture\n", encoding="utf-8")

            ensured = subprocess.run(
                (
                    "make",
                    "ensure-image",
                    f"DOCKER={docker}",
                    "BUILDER_IMAGE=fixture-builder:dev",
                    "PLATFORM=linux/amd64",
                ),
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(ensured.returncode, 0, ensured.stdout)
            self.assertFalse(
                any(line.startswith("build ") for line in docker_log.read_text().splitlines())
            )

            configured = subprocess.run(
                (str(ROOT / "scripts" / "service-compose"), "config"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout)
            docker_commands = docker_log.read_text(encoding="utf-8")
            self.assertNotIn("image inspect --platform", docker_commands)
            compose_call = compose_log.read_text(encoding="utf-8")
            self.assertIn("--env-file .env config --quiet", compose_call)
            self.assertEqual(compose_call.count(IMAGE_ID), 2)
            self.assertIn("fixture-builder:dev", compose_call)

    def test_arm64_image_is_rebuilt_by_make_and_rejected_by_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker, _compose, docker_log, compose_log = self.environment(
                root, platform="linux/arm64"
            )
            (root / ".env").write_text("# fixture\n", encoding="utf-8")

            ensured = subprocess.run(
                (
                    "make",
                    "ensure-image",
                    f"DOCKER={docker}",
                    "BUILDER_IMAGE=fixture-builder:dev",
                    "PLATFORM=linux/amd64",
                ),
                cwd=ROOT,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(ensured.returncode, 0, ensured.stdout)
            self.assertIn("build ", docker_log.read_text(encoding="utf-8"))
            self.assertIn("--platform linux/amd64", docker_log.read_text(encoding="utf-8"))

            configured = subprocess.run(
                (str(ROOT / "scripts" / "service-compose"), "config"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(configured.returncode, 4, configured.stdout)
            self.assertIn(
                "SERVICE_COMPOSE: builder image platform must be linux/amd64",
                configured.stdout,
            )
            self.assertFalse(compose_log.exists())


if __name__ == "__main__":
    unittest.main()
