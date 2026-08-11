from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCTOR = ROOT / "scripts" / "doctor"


def write_tool(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\nset -eu\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


class DoctorTests(unittest.TestCase):
    def test_script_is_safe_executable_and_syntax_valid(self) -> None:
        mode = stat.S_IMODE(DOCTOR.stat().st_mode)
        self.assertEqual(mode & 0o111, 0o111)
        self.assertEqual(mode & 0o022, 0)
        checked = subprocess.run(
            ("sh", "-n", str(DOCTOR)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout)
        text = DOCTOR.read_text(encoding="utf-8")
        for forbidden in (
            "curl ",
            "wget ",
            "brew ",
            "apt ",
            "sudo ",
            '"$doctor_docker" pull ',
            '"$doctor_docker" run ',
            '"$doctor_docker" build ',
            "rm ",
        ):
            self.assertNotIn(forbidden, text)

    def test_help_and_invalid_usage_are_stable(self) -> None:
        helped = subprocess.run(
            (str(DOCTOR), "--help"),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(helped.returncode, 0, helped.stdout)
        self.assertIn("--demo", helped.stdout)
        self.assertIn("--service", helped.stdout)
        self.assertIn("--native", helped.stdout)
        rejected = subprocess.run(
            (str(DOCTOR), "--surprise"),
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(rejected.returncode, 2, rejected.stdout)
        self.assertIn("usage:", rejected.stdout)

    def test_all_three_modes_pass_with_supported_toolchain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format) printf '%s\n' '29.4.0' ;;
  buildx:version) printf '%s\n' 'github.com/docker/buildx v0.30.1' ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            python = write_tool(
                tools,
                "python3",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            blender = write_tool(
                tools,
                "blender",
                "printf '%s\\n' 'Blender 4.5.12 LTS'\n",
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HBCB_DOCTOR_GIT": str(git),
                "HBCB_DOCTOR_MAKE": str(make),
                "HBCB_DOCTOR_DOCKER": str(docker),
                "HBCB_DOCTOR_PYTHON": str(python),
                "BLENDER": str(blender),
            }
            for mode in ("--demo", "--service", "--native"):
                with self.subTest(mode=mode):
                    completed = subprocess.run(
                        (str(DOCTOR), mode),
                        cwd=ROOT,
                        env=environment,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertEqual(completed.returncode, 0, completed.stdout)
                    self.assertIn("HBCB_DOCTOR: PASS", completed.stdout)

    def test_unreachable_daemon_and_old_compose_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format) exit 1 ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.23.0' ;;
  *) exit 9 ;;
esac
""",
            )
            python = write_tool(
                tools,
                "python3",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c)
    if [ "${3:-}" = 'Docker Compose version v2.23.0' ]; then exit 1; fi
    exit 0
    ;;
  *) exit 9 ;;
esac
""",
            )
            completed = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=ROOT,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HBCB_DOCTOR_GIT": str(git),
                    "HBCB_DOCTOR_MAKE": str(make),
                    "HBCB_DOCTOR_DOCKER": str(docker),
                    "HBCB_DOCTOR_PYTHON": str(python),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("Docker daemon is not reachable", completed.stdout)
        self.assertIn("Docker Compose 2.24.4+ is required", completed.stdout)
        self.assertIn("HBCB_DOCTOR: FAIL (2 prerequisite check(s) failed)", completed.stdout)

    def test_native_mode_does_not_require_make_or_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            python = write_tool(
                tools,
                "python3",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            blender = write_tool(
                tools,
                "blender",
                "printf '%s\\n' 'Blender 4.5.12 LTS'\n",
            )
            completed = subprocess.run(
                (str(DOCTOR), "--native"),
                cwd=ROOT,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HBCB_DOCTOR_GIT": str(git),
                    "HBCB_DOCTOR_MAKE": str(tools / "missing-make"),
                    "HBCB_DOCTOR_DOCKER": str(tools / "missing-docker"),
                    "HBCB_DOCTOR_PYTHON": str(python),
                    "BLENDER": str(blender),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("HBCB_DOCTOR: PASS (native prerequisites are ready)", completed.stdout)
        self.assertNotIn("GNU Make is unavailable", completed.stdout)
        self.assertNotIn("Docker is unavailable", completed.stdout)


if __name__ == "__main__":
    unittest.main()
