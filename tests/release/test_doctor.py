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
    def service_checkout(self, root: Path) -> None:
        (root / "scripts").mkdir()
        (root / "docker").mkdir()
        (root / "Makefile").write_text("help:\n\t@true\n", encoding="utf-8")
        (root / "docker" / "builder.Dockerfile").write_text(
            "FROM scratch\n", encoding="utf-8"
        )
        (root / "scripts" / "service-common").write_text(
            """
hbcb_service_settings() {
  HBCB_COMPOSE_PROJECT_NAME=hbcb-test-project
  COMPOSE_PROJECT_NAME=$HBCB_COMPOSE_PROJECT_NAME
  HBCB_API_HOST_PORT=18080
  HBCB_STORAGE_HOST_PORT=19000
  export HBCB_COMPOSE_PROJECT_NAME COMPOSE_PROJECT_NAME
  export HBCB_API_HOST_PORT HBCB_STORAGE_HOST_PORT
}
hbcb_service_ports_available() {
  if [ -n "${HBCB_TEST_PORT_STATUS:-}" ]; then
    return "$HBCB_TEST_PORT_STATUS"
  fi
  "$1" -c 'raise SystemExit(0)'
}
""",
            encoding="utf-8",
        )

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
        self.assertNotIn("http://", text)
        self.assertNotIn("https://", text)

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
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|12884901888' ;;
      *) exit 9 ;;
    esac
    ;;
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
            curl = write_tool(
                tools,
                "curl",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'curl 8.16.0 fixture' ;;
  --help:all) printf '%s\n' '    --fail-with-body    --noproxy' ;;
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
                "HBCB_DOCTOR_CURL": str(curl),
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
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') exit 1 ;;
      *) exit 9 ;;
    esac
    ;;
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

    def test_service_rejects_clear_remote_endpoints_but_tolerates_local_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
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
            curl = write_tool(
                tools,
                "curl",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'curl 8.16.0 fixture' ;;
  --help:all) printf '%s\n' '    --fail-with-body    --noproxy' ;;
  *) exit 9 ;;
esac
""",
            )
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  context:inspect)
    if [ "${HBCB_TEST_DOCKER_ENDPOINT+x}" = x ]; then
      printf '%s\n' "$HBCB_TEST_DOCKER_ENDPOINT"
    else
      exit 1
    fi
    ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|8589934592' ;;
      *) exit 9 ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            base = {
                "PATH": os.environ.get("PATH", ""),
                "HBCB_DOCTOR_GIT": str(git),
                "HBCB_DOCTOR_MAKE": str(make),
                "HBCB_DOCTOR_DOCKER": str(docker),
                "HBCB_DOCTOR_PYTHON": str(python),
                "HBCB_DOCTOR_CURL": str(curl),
            }
            for endpoint in (
                "ssh://remote.example/run/docker.sock",
                "tcp://remote.example:2376",
                "http://remote.example:2375",
                "https://remote.example:2376",
            ):
                with self.subTest(endpoint=endpoint):
                    remote = subprocess.run(
                        (str(DOCTOR), "--service"),
                        cwd=root,
                        env={**base, "HBCB_TEST_DOCKER_ENDPOINT": endpoint},
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertEqual(remote.returncode, 1, remote.stdout)
                    message = "local service requires a local Docker daemon/context"
                    self.assertIn(message, remote.stdout)
                    self.assertLess(
                        remote.stdout.index(message),
                        remote.stdout.index("Docker version"),
                    )
                    self.assertNotIn("remote.example", remote.stdout)
                    self.assertNotIn("API loopback port", remote.stdout)

            for endpoint in (
                "unix:///var/run/docker.sock",
                "npipe:////./pipe/docker_engine",
                "default",
                "fd://3",
            ):
                with self.subTest(endpoint=endpoint):
                    accepted = subprocess.run(
                        (str(DOCTOR), "--service"),
                        cwd=root,
                        env={**base, "HBCB_TEST_DOCKER_ENDPOINT": endpoint},
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertEqual(accepted.returncode, 0, accepted.stdout)
                    self.assertIn("HBCB_DOCTOR: PASS", accepted.stdout)

            unavailable = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env=base,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(unavailable.returncode, 0, unavailable.stdout)
        self.assertIn("HBCB_DOCTOR: PASS", unavailable.stdout)

    def test_python_selector_precedence_and_single_executable_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary)
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            blender = write_tool(
                tools, "blender", "printf '%s\\n' 'Blender 4.5.12 LTS'\n"
            )
            preferred = write_tool(
                tools,
                "preferred-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.12.4 preferred' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            make_python = write_tool(
                tools,
                "make-python",
                """
case "${1:-}" in
  --version) printf '%s\n' 'Python 3.11.9 make-selector' ;;
  -c) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            base = {
                "PATH": os.environ.get("PATH", ""),
                "HBCB_DOCTOR_GIT": str(git),
                "BLENDER": str(blender),
                "PYTHON": str(make_python),
            }
            preferred_run = subprocess.run(
                (str(DOCTOR), "--native"),
                cwd=ROOT,
                env={**base, "HBCB_DOCTOR_PYTHON": str(preferred)},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(preferred_run.returncode, 0, preferred_run.stdout)
            self.assertIn("Python 3.12.4 preferred", preferred_run.stdout)
            self.assertNotIn("make-selector", preferred_run.stdout)

            make_selected = subprocess.run(
                (str(DOCTOR), "--native"),
                cwd=ROOT,
                env=base,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(make_selected.returncode, 0, make_selected.stdout)
            self.assertIn("Python 3.11.9 make-selector", make_selected.stdout)

            rejected = subprocess.run(
                (str(DOCTOR), "--native"),
                cwd=ROOT,
                env={**base, "PYTHON": f"{make_python} -I"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(rejected.returncode, 1, rejected.stdout)
            self.assertIn("Python 3.11+ is unavailable", rejected.stdout)

    def test_service_capacity_is_advisory_and_valid_response_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
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
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|12884901888' ;;
      *) exit 9 ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            completed = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
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
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("Docker reports 8 CPU(s) and 12 GiB RAM", completed.stdout)
        self.assertIn("meets the advisory 8 GiB", completed.stdout)
        self.assertIn("service-smoke path recommends at least 12 GiB", completed.stdout)
        self.assertRegex(
            completed.stdout,
            r"checkout has about [0-9]+ GiB free(?:; the advisory service "
            r"baseline is 20 GiB| \(20 GiB service baseline\))",
        )

    def test_demo_reports_advisory_one_shot_capacity_without_failing(self) -> None:
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
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '4|3221225472' ;;
      *) exit 9 ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  *) exit 9 ;;
esac
""",
            )
            completed = subprocess.run(
                (str(DOCTOR), "--demo"),
                cwd=ROOT,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HBCB_DOCTOR_GIT": str(git),
                    "HBCB_DOCTOR_MAKE": str(make),
                    "HBCB_DOCTOR_DOCKER": str(docker),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertIn("builder is capped at 4 CPUs and 4 GiB", completed.stdout)
        self.assertIn("less than the advisory 8 GiB one-shot", completed.stdout)
        self.assertRegex(
            completed.stdout,
            r"checkout has about [0-9]+ GiB free(?:; the advisory one-shot "
            r"baseline is 10 GiB| \(10 GiB one-shot baseline\))",
        )

    def test_missing_python_does_not_misreport_supported_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|8589934592' ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            missing_python = tools / "missing-python"
            completed = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "HBCB_DOCTOR_GIT": str(git),
                    "HBCB_DOCTOR_MAKE": str(make),
                    "HBCB_DOCTOR_DOCKER": str(docker),
                    "HBCB_DOCTOR_PYTHON": str(missing_python),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(completed.returncode, 1, completed.stdout)
        self.assertIn("Python 3.11+ is unavailable", completed.stdout)
        self.assertIn("Docker Compose reports Docker Compose version v2.24.4", completed.stdout)
        self.assertNotIn("Docker Compose 2.24.4+ is required", completed.stdout)
        self.assertIn("FAIL (1 prerequisite check(s) failed)", completed.stdout)

    def test_service_curl_selector_is_advisory_and_never_contacts_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
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
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|8589934592' ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            curl_log = root / "curl.log"
            curl = write_tool(
                tools,
                "selected-curl",
                f"""
printf '%s\n' "$*" >> {curl_log}
case "${{1:-}}:${{2:-}}" in
  --version:) printf '%s\n' 'curl 7.75.0 fixture' ;;
  --help:all)
    if [ "${{HBCB_TEST_CURL_SUPPORTED:-0}}" = 1 ]; then
      printf '%s\n' '    --fail-with-body    --noproxy'
    else
      printf '%s\n' '    --fail'
    fi
    ;;
  *) exit 88 ;;
esac
""",
            )
            environment = {
                "PATH": os.environ.get("PATH", ""),
                "HBCB_DOCTOR_GIT": str(git),
                "HBCB_DOCTOR_MAKE": str(make),
                "HBCB_DOCTOR_DOCKER": str(docker),
                "HBCB_DOCTOR_PYTHON": str(python),
                "HBCB_DOCTOR_CURL": str(curl),
            }
            unsupported = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            supported = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env={**environment, "HBCB_TEST_CURL_SUPPORTED": "1"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            curl_calls = curl_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(unsupported.returncode, 0, unsupported.stdout)
        self.assertIn(
            "curl lacks --fail-with-body or --noproxy; use the stdlib lightweight client",
            unsupported.stdout,
        )
        self.assertEqual(supported.returncode, 0, supported.stdout)
        self.assertIn("supports the optional manual API protocol example", supported.stdout)
        self.assertEqual(
            curl_calls,
            ["--version", "--help all", "--version", "--help all"],
        )

    def test_service_rejects_unsafe_env_metadata_without_printing_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
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
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|8589934592' ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  *) exit 9 ;;
esac
""",
            )
            canary = "private-service-env-canary"
            secret = root / "secret.env"
            secret.write_text(f"HBCB_API_TOKEN={canary}\n", encoding="utf-8")
            (root / ".env").symlink_to(secret)
            completed = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
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
            (root / ".env").unlink()
            (root / ".env").write_text(
                f"HBCB_API_TOKEN={canary}\n", encoding="utf-8"
            )
            (root / ".env").chmod(0o644)
            permissive = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
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
        self.assertIn("regular non-symlink", completed.stdout)
        self.assertNotIn(canary, completed.stdout)
        self.assertEqual(permissive.returncode, 1, permissive.stdout)
        self.assertIn("owned by the current user with mode 0600", permissive.stdout)
        self.assertNotIn(canary, permissive.stdout)

    def test_occupied_ports_are_allowed_only_for_the_selected_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.service_checkout(root)
            tools = root / "tools"
            tools.mkdir()
            git = write_tool(tools, "git", "printf '%s\\n' 'git version 2.50.1'\n")
            make = write_tool(tools, "make", "printf '%s\\n' 'GNU Make 4.4.1'\n")
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
            docker = write_tool(
                tools,
                "docker",
                """
case "${1:-}:${2:-}" in
  --version:) printf '%s\n' 'Docker version 29.4.0, build example' ;;
  info:--format)
    case "${3:-}" in
      '{{.ServerVersion}}') printf '%s\n' '29.4.0' ;;
      '{{.NCPU}}|{{.MemTotal}}') printf '%s\n' '8|8589934592' ;;
    esac
    ;;
  buildx:version) exit 0 ;;
  compose:version) printf '%s\n' 'Docker Compose version v2.24.4' ;;
  ps:--quiet)
    if [ "${HBCB_TEST_PROJECT_OWNS_PORT:-0}" = 1 ]; then
      printf '%s\n' 'selected-project-container'
    fi
    ;;
  *) exit 9 ;;
esac
""",
            )
            base = {
                "PATH": os.environ.get("PATH", ""),
                "HBCB_DOCTOR_GIT": str(git),
                "HBCB_DOCTOR_MAKE": str(make),
                "HBCB_DOCTOR_DOCKER": str(docker),
                "HBCB_DOCTOR_PYTHON": str(python),
                "HBCB_TEST_PORT_STATUS": "3",
            }
            owned = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env={**base, "HBCB_TEST_PROJECT_OWNS_PORT": "1"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            foreign = subprocess.run(
                (str(DOCTOR), "--service"),
                cwd=root,
                env=base,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        self.assertEqual(owned.returncode, 0, owned.stdout)
        self.assertEqual(owned.stdout.count("already owned by selected project"), 2)
        self.assertEqual(foreign.returncode, 1, foreign.stdout)
        self.assertIn("API loopback port 127.0.0.1:18080", foreign.stdout)
        self.assertIn("artifact storage loopback port 127.0.0.1:19000", foreign.stdout)
        self.assertIn("outside selected project hbcb-test-project", foreign.stdout)

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
                    "HBCB_DOCTOR_CURL": str(tools / "missing-curl"),
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
        self.assertNotIn("curl is unavailable", completed.stdout)


if __name__ == "__main__":
    unittest.main()
