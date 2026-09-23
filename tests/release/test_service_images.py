from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "service-images"


class ServiceImagesTests(unittest.TestCase):
    def test_list_and_remove_are_exact_and_never_prune_or_touch_volumes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hbcb-service-images-") as raw:
            root = Path(raw)
            (root / "scripts").mkdir()
            (root / "scripts" / "service-common").write_bytes(
                (ROOT / "scripts" / "service-common").read_bytes()
            )
            script = root / "scripts" / "service-images"
            script.write_bytes(SCRIPT.read_bytes())
            script.chmod(0o755)
            env_file = root / ".env"
            env_file.write_text(
                "HBCB_COMPOSE_PROJECT_NAME=hbcb-cleanup-fixture\n",
                encoding="ascii",
            )
            env_file.chmod(0o600)
            docker_log = root / "docker.log"
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                "set -eu\n"
                'printf \'%s\\n\' "$*" >> "$DOCKER_LOG"\n'
                'case "${1:-}:${2:-}" in\n'
                '  info:--format)\n'
                '    test "${DOCKER_FAIL:-}" != info || exit 90\n'
                "    printf '%s\\n' '29.4.0'\n"
                '    ;;\n'
                '  image:ls)\n'
                '    test "${DOCKER_FAIL:-}" != query || exit 89\n'
                '    case "${4:-}" in reference=*) printf \'%s\\n\' "${4#reference=}" ;; *) exit 88 ;; esac\n'
                '    ;;\n'
                '  image:inspect|image:rm) exit 0 ;;\n'
                '  *) exit 91 ;;\n'
                'esac\n',
                encoding="ascii",
            )
            docker.chmod(0o700)
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "DOCKER": str(docker),
                "DOCKER_LOG": str(docker_log),
            }
            listed = subprocess.run(
                (str(script), "list"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(listed.returncode, 0, listed.stdout)
            expected = (
                "hbcb-cleanup-fixture-builder:dev",
                "hbcb-cleanup-fixture-postgres:16.15-alpine3.24-hbcb.1",
                "hbcb-cleanup-fixture-api:dev",
                "hbcb-cleanup-fixture-worker:dev",
                "hbcb-cleanup-fixture-minio:final-community-20260212-hbcb.1",
                "hbcb-cleanup-fixture-test:dev",
            )
            for reference in expected:
                self.assertIn(reference, listed.stdout)
            self.assertFalse(docker_log.exists())

            removed = subprocess.run(
                (str(script), "remove"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(removed.returncode, 0, removed.stdout)
            calls = docker_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(calls), 1 + len(expected) * 3)
            self.assertEqual(calls[0], "info --format {{.ServerVersion}}")
            for reference in expected:
                self.assertIn(
                    "image ls --filter reference=" + reference
                    + " --format {{.Repository}}:{{.Tag}}",
                    calls,
                )
                self.assertIn("image inspect " + reference, calls)
                self.assertIn("image rm " + reference, calls)
            combined = "\n".join(calls).lower()
            for forbidden in ("prune", "volume", "container", "network", "--force"):
                self.assertNotIn(forbidden, combined)
            self.assertIn("shared Docker build cache were retained", removed.stdout)

            for failure in ("info", "query"):
                with self.subTest(failure=failure):
                    docker_log.unlink()
                    failed = subprocess.run(
                        (str(script), "remove"),
                        cwd=root,
                        env={**environment, "DOCKER_FAIL": failure},
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertEqual(failed.returncode, 4, failed.stdout)
                    self.assertIn("SERVICE_IMAGES: FAIL:", failed.stdout)
                    self.assertNotIn("SERVICE_IMAGE_ABSENT", failed.stdout)
                    self.assertNotIn("cleanup complete", failed.stdout)

            docker_log.unlink()
            env_file.write_text("HBCB_API_HOST_PORT=8080\n", encoding="ascii")
            legacy = subprocess.run(
                (str(script), "remove"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(legacy.returncode, 4, legacy.stdout)
            self.assertIn("legacy hbcb-local tags may be shared", legacy.stdout)
            self.assertNotIn("cleanup complete", legacy.stdout)
            self.assertFalse(docker_log.exists())

    def test_script_mode_and_usage_are_safe(self) -> None:
        mode = stat.S_IMODE(SCRIPT.stat().st_mode)
        self.assertEqual(mode & 0o111, 0o111)
        self.assertEqual(mode & 0o022, 0)
        help_result = subprocess.run(
            (str(SCRIPT), "--help"),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stdout)
        self.assertEqual(
            help_result.stdout,
            "usage: scripts/service-images list|remove\n",
        )
        rejected = subprocess.run(
            (str(SCRIPT), "surprise"),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2, rejected.stdout)


if __name__ == "__main__":
    unittest.main()
