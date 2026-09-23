from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVICE_COMPOSE = ROOT / "scripts" / "service-compose"
INIT_ENV = ROOT / "scripts" / "init-env"
IMAGE_ID = "sha256:" + "a" * 64
ZERO_ID = "sha256:" + "0" * 64


FAKE_DOCKER = f"""#!/bin/sh
set -eu
: "${{FAKE_DOCKER_LOG:?}}"
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [ "${{1:-}}:${{2:-}}" = image:inspect ]; then
  shift 2
  format=
  target=
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --format)
        shift
        format=${{1:-}}
        ;;
      *)
        target=$1
        ;;
    esac
    shift
  done
  if [ -n "${{FAKE_POSTGRES_IMAGE:-}}" ] && [ "$target" = "${{FAKE_POSTGRES_IMAGE:-}}" ]; then
    [ -n "${{FAKE_POSTGRES_IMAGE_PRESENT:-}}" ] || exit 1
    exit 0
  fi
  case "$format" in
    '{{{{.Os}}}}/{{{{.Architecture}}}}|{{{{.Id}}}}')
      printf '%s|%s\n' "${{FAKE_IMAGE_PLATFORM:-linux/amd64}}" \
        "${{FAKE_IMAGE_ID:-{IMAGE_ID}}}"
      ;;
    *) exit 1 ;;
  esac
  exit 0
fi
if [ "${{1:-}}:${{2:-}}" = volume:inspect ]; then
  [ -n "${{FAKE_POSTGRES_VOLUME_PRESENT:-}}" ] || exit 1
  exit 0
fi
case "${{1:-}}" in
  run)
    case "$*" in
      *--pids-limit*) exit "${{FAKE_POSTGRES_PROBE_STATUS:-0}}" ;;
    esac
    exit 0
    ;;
  build) exit 0 ;;
esac
printf '%s\n' 'unexpected fake Docker command' >&2
exit 64
"""


FAKE_COMPOSE = r"""#!/bin/sh
set -eu
: "${FAKE_COMPOSE_LOG:?}"
printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
  "$*" \
  "${COMPOSE_PROJECT_NAME:-}" \
  "${HBCB_API_HOST_PORT:-}" \
  "${HBCB_STORAGE_HOST_PORT:-}" \
  "${HBCB_STORAGE_PUBLIC_ENDPOINT:-}" \
  "${HBCB_MINIO_IMAGE:-}" \
  "${HBCB_SERVICE_API_IMAGE:-}" \
  "${HBCB_SERVICE_WORKER_IMAGE:-}" \
  "${HBCB_SERVICE_TEST_IMAGE:-}" \
  "${HBCB_BUILDER_IMAGE:-}" >> "$FAKE_COMPOSE_LOG"
case "$*" in
  *' port api 8080')
    [ -n "${FAKE_OWN_API_PORT:-}" ] || exit 1
    printf '127.0.0.1:%s\n' "$FAKE_OWN_API_PORT"
    ;;
  *' port minio 9000')
    [ -n "${FAKE_OWN_STORAGE_PORT:-}" ] || exit 1
    printf '127.0.0.1:%s\n' "$FAKE_OWN_STORAGE_PORT"
    ;;
esac
"""


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def parse_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
    )


class ServiceComposeTests(unittest.TestCase):
    def test_checkout_identity_has_a_deterministic_no_git_sha256_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tools = root / "tools"
            tools.mkdir()
            write_executable(
                tools / "sha256sum",
                "#!/bin/sh\n"
                "set -eu\n"
                "while IFS= read -r _line; do :; done\n"
                f"printf '%s  -\\n' '{'a' * 64}'\n",
            )
            completed = subprocess.run(
                (
                    "/bin/sh",
                    "-c",
                    '. "$HBCB_TEST_SERVICE_COMMON"; hbcb_service_default_project_name',
                ),
                cwd=root,
                env={
                    "PATH": str(tools),
                    "HBCB_TEST_SERVICE_COMMON": str(ROOT / "scripts" / "service-common"),
                },
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(completed.stdout, "hbcb-local-aaaaaaaaaaaa\n")

    def fixture(self, root: Path) -> tuple[dict[str, str], Path, Path]:
        tools = root / "tools"
        tools.mkdir()
        docker = tools / "selected-docker"
        compose = tools / "selected-compose"
        python = tools / "selected-python"
        write_executable(docker, FAKE_DOCKER)
        write_executable(compose, FAKE_COMPOSE)
        write_executable(
            python,
            "#!/bin/sh\n"
            "set -eu\n"
            "case \"${1:-}\" in\n"
            "  */minio-recipe-id) printf '%s\\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; exit 0 ;;\n"
            "  -c) ;;\n"
            "  *) exit 64 ;;\n"
            "esac\n"
            "if [ \"$#\" -eq 2 ]; then exit 0; fi\n"
            "exit \"${FAKE_PORT_STATUS:-0}\"\n",
        )
        (root / "docker").mkdir()
        (root / "docker" / "minio.Dockerfile").write_text(
            "FROM scratch\n", encoding="utf-8"
        )
        (root / "docker" / "builder.Dockerfile").write_text(
            "FROM scratch\n", encoding="utf-8"
        )
        environment = os.environ.copy()
        for name in (
            "BUILDER_IMAGE",
            "COMPOSE_PROJECT_NAME",
            "DOCKER",
            "HBCB_API_HOST_PORT",
            "HBCB_COMPOSE_BIN",
            "HBCB_REBUILD_MINIO",
            "HBCB_STORAGE_HOST_PORT",
            "PYTHON",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "DOCKER": str(docker),
                "PYTHON": str(python),
                "HBCB_COMPOSE_BIN": str(compose),
                "HBCB_REBUILD_MINIO": "1",
                "FAKE_DOCKER_LOG": str(root / "docker.log"),
                "FAKE_COMPOSE_LOG": str(root / "compose.log"),
            }
        )
        return environment, root / "docker.log", root / "compose.log"

    def write_env(
        self,
        root: Path,
        *,
        project: str = "hbcb-test-checkout",
        api_port: int | None = None,
        storage_port: int | None = None,
    ) -> tuple[int, int]:
        if api_port is None:
            api_port = 18080
        if storage_port is None:
            storage_port = 19000
        output = root / ".env"
        output.write_text(
            f"HBCB_COMPOSE_PROJECT_NAME={project}\n"
            f"HBCB_API_HOST_PORT={api_port}\n"
            f"HBCB_STORAGE_HOST_PORT={storage_port}\n",
            encoding="utf-8",
        )
        output.chmod(0o600)
        return api_port, storage_port

    def invoke(
        self,
        root: Path,
        environment: dict[str, str],
        action: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (str(SERVICE_COMPOSE), action),
            cwd=root,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_scripts_and_compose_surface_have_safe_modes_and_wiring(self) -> None:
        wrapper_mode = stat.S_IMODE(SERVICE_COMPOSE.stat().st_mode)
        common_mode = stat.S_IMODE((ROOT / "scripts" / "service-common").stat().st_mode)
        self.assertEqual(wrapper_mode & 0o111, 0o111)
        self.assertEqual(wrapper_mode & 0o022, 0)
        self.assertEqual(common_mode & 0o111, 0)
        self.assertEqual(common_mode & 0o022, 0)
        checked = subprocess.run(
            (
                "sh",
                "-n",
                str(ROOT / "scripts" / "service-common"),
                str(SERVICE_COMPOSE),
                str(INIT_ENV),
            ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stdout)

        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertNotIn("name: hbcb-local", compose)
        for variable in (
            "HBCB_API_HOST_PORT",
            "HBCB_STORAGE_HOST_PORT",
            "HBCB_POSTGRES_IMAGE",
            "HBCB_MINIO_IMAGE",
            "HBCB_SERVICE_API_IMAGE",
            "HBCB_SERVICE_WORKER_IMAGE",
            "HBCB_SERVICE_TEST_IMAGE",
        ):
            self.assertIn("${" + variable, compose)
        self.assertIn(
            "HBCB_STORAGE_PUBLIC_ENDPOINT:-localhost:9000", compose
        )
        self.assertIn(
            "redis:8.2.10-alpine3.22@sha256:"
            "8d02c1dc547ea659066d2ca18fce4e80f0a84cfe56a61af2ced2c2a48de3597c",
            compose,
        )
        postgres_dockerfile = (ROOT / "docker" / "postgres.Dockerfile").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "postgres:16.15-alpine3.24@sha256:"
            "721873c34ceb9f8d8fc265984940dc982404c105f19ad51be9fdc5970a6080ea",
            postgres_dockerfile,
        )
        self.assertIn("dockerfile: docker/postgres.Dockerfile", compose)
        self.assertRegex(
            compose,
            r"(?ms)^  postgres:\n.*?^    user: \"70:70\"$",
        )
        for redis_policy in (
            "appendonly yes",
            "appendfsync everysec",
            "auto-aof-rewrite-percentage 100",
            "auto-aof-rewrite-min-size 64mb",
            "maxmemory 384mb",
            "maxmemory-policy noeviction",
        ):
            self.assertIn(redis_policy, compose)
        self.assertEqual(
            compose.count(
                "io.hbcb.release-service-owner: ${HBCB_RELEASE_OWNER:-local}"
            ),
            8,
        )

    def test_init_env_persists_distinct_stable_checkout_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            first = parent / "first"
            second = parent / "second"
            first.mkdir()
            second.mkdir()
            for checkout in (first, second):
                completed = subprocess.run(
                    (str(INIT_ENV),),
                    cwd=checkout,
                    env={"PATH": os.environ.get("PATH", "")},
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)
            first_values = parse_env(first / ".env")
            second_values = parse_env(second / ".env")
            self.assertNotEqual(
                first_values["HBCB_COMPOSE_PROJECT_NAME"],
                second_values["HBCB_COMPOSE_PROJECT_NAME"],
            )
            original_project = first_values["HBCB_COMPOSE_PROJECT_NAME"]
            moved = parent / "moved"
            first.rename(moved)
            self.assertEqual(
                parse_env(moved / ".env")["HBCB_COMPOSE_PROJECT_NAME"],
                original_project,
            )

    def test_status_actions_are_bounded_and_do_not_touch_builder_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            api_port, storage_port = self.write_env(root)
            cases = (
                ("config", "config --quiet"),
                ("ps", "ps --all"),
                ("logs", "logs --tail 100 api worker"),
            )
            for action, suffix in cases:
                with self.subTest(action=action):
                    completed = self.invoke(root, environment, action)
                    self.assertEqual(completed.returncode, 0, completed.stdout)
                    self.assertIn("project=hbcb-test-checkout", completed.stdout)
                    last = compose_log.read_text(encoding="utf-8").splitlines()[-1]
                    fields = last.split("|")
                    self.assertEqual(
                        fields[0],
                        "--project-name hbcb-test-checkout --env-file .env " + suffix,
                    )
                    self.assertEqual(fields[1:5], [
                        "hbcb-test-checkout",
                        str(api_port),
                        str(storage_port),
                        f"localhost:{storage_port}",
                    ])
                    self.assertEqual(
                        fields[-1], "headless-blender-character-builder:unavailable"
                    )
            self.assertFalse(docker_log.exists())

    def test_down_works_without_env_and_never_removes_volumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            completed = self.invoke(root, environment, "down")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            invocation = compose_log.read_text(encoding="utf-8").split("|", 1)[0]
            self.assertRegex(
                invocation,
                r"^--project-name hbcb-local-[0-9a-f]{12} down --remove-orphans$",
            )
            self.assertNotIn("--volumes", invocation)
            self.assertFalse(docker_log.exists())

    def test_legacy_env_and_validated_external_override_choose_expected_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, _docker_log, compose_log = self.fixture(root)
            output = root / ".env"
            output.write_text("HBCB_DEPLOYMENT_NAMESPACE=local\n", encoding="utf-8")
            output.chmod(0o600)

            legacy = self.invoke(root, environment, "config")
            self.assertEqual(legacy.returncode, 0, legacy.stdout)
            fields = compose_log.read_text(encoding="utf-8").splitlines()[-1].split("|")
            self.assertEqual(fields[1:9], [
                "hbcb-local",
                "8080",
                "9000",
                "localhost:9000",
                "hbcb-minio-local:final-community-20260212-hbcb.1",
                "hbcb-service-api:dev",
                "hbcb-service-worker:dev",
                "hbcb-service-test:dev",
            ])

            overridden = environment.copy()
            overridden.update(
                {
                    "COMPOSE_PROJECT_NAME": "hbcb-external",
                    "HBCB_API_HOST_PORT": "18080",
                    "HBCB_STORAGE_HOST_PORT": "19000",
                }
            )
            selected = self.invoke(root, overridden, "config")
            self.assertEqual(selected.returncode, 0, selected.stdout)
            fields = compose_log.read_text(encoding="utf-8").splitlines()[-1].split("|")
            self.assertEqual(fields[1:9], [
                "hbcb-external",
                "18080",
                "19000",
                "localhost:19000",
                "hbcb-external-minio:final-community-20260212-hbcb.1",
                "hbcb-external-api:dev",
                "hbcb-external-worker:dev",
                "hbcb-external-test:dev",
            ])

    def test_invalid_settings_fail_before_tools_without_echoing_inputs(self) -> None:
        cases = (
            (
                "invalid project",
                "HBCB_COMPOSE_PROJECT_NAME=DoNotEchoInvalidProject\n"
                "HBCB_API_HOST_PORT=18080\nHBCB_STORAGE_HOST_PORT=19000\n",
                {},
                "DoNotEchoInvalidProject",
            ),
            (
                "duplicate project",
                "HBCB_COMPOSE_PROJECT_NAME=first-secret-value\n"
                "HBCB_COMPOSE_PROJECT_NAME=second-secret-value\n",
                {},
                "second-secret-value",
            ),
            (
                "invalid external port",
                "HBCB_COMPOSE_PROJECT_NAME=hbcb-safe\n",
                {"HBCB_API_HOST_PORT": "DoNotEchoInvalidPort"},
                "DoNotEchoInvalidPort",
            ),
            (
                "equal ports",
                "HBCB_COMPOSE_PROJECT_NAME=hbcb-safe\n"
                "HBCB_API_HOST_PORT=18080\nHBCB_STORAGE_HOST_PORT=18080\n",
                {},
                "project=hbcb-safe",
            ),
        )
        for label, payload, overrides, rejected in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                environment, docker_log, compose_log = self.fixture(root)
                environment.update(overrides)
                output = root / ".env"
                output.write_text(payload, encoding="utf-8")
                output.chmod(0o600)
                completed = self.invoke(root, environment, "config")
                self.assertNotEqual(completed.returncode, 0, completed.stdout)
                self.assertNotIn(rejected, completed.stdout)
                self.assertFalse(docker_log.exists())
                self.assertFalse(compose_log.exists())

    def test_nonprivate_env_fails_before_compose_or_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            self.write_env(root)
            (root / ".env").chmod(0o644)
            completed = self.invoke(root, environment, "config")
            self.assertEqual(completed.returncode, 3, completed.stdout)
            self.assertIn("owned mode-0600 regular file", completed.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse(compose_log.exists())

    def test_env_symlink_and_hostile_tool_strings_are_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            target = root / "private-settings"
            target.write_text(
                "HBCB_COMPOSE_PROJECT_NAME=hbcb-safe\n", encoding="utf-8"
            )
            target.chmod(0o600)
            (root / ".env").symlink_to(target)
            linked = self.invoke(root, environment, "config")
            self.assertNotEqual(linked.returncode, 0, linked.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse(compose_log.exists())

            (root / ".env").unlink()
            self.write_env(root)
            marker = root / "unexpected-command"
            hostile_compose = environment.copy()
            hostile_compose["HBCB_COMPOSE_BIN"] = (
                environment["HBCB_COMPOSE_BIN"] + ";touch " + str(marker)
            )
            attempted = self.invoke(root, hostile_compose, "config")
            self.assertNotEqual(attempted.returncode, 0, attempted.stdout)
            self.assertFalse(marker.exists())
            self.assertFalse(docker_log.exists())

            hostile_docker = environment.copy()
            hostile_docker["DOCKER"] = "missing;touch " + str(marker)
            rejected = self.invoke(root, hostile_docker, "up")
            self.assertEqual(rejected.returncode, 3, rejected.stdout)
            self.assertNotIn(str(marker), rejected.stdout)
            self.assertFalse(marker.exists())

    def test_option_like_tools_and_builder_fail_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            self.write_env(root)
            for name in ("DOCKER", "PYTHON"):
                with self.subTest(selector=name):
                    selected = environment.copy()
                    selected[name] = "--DoNotEchoToolSelector"
                    completed = self.invoke(root, selected, "config")
                    self.assertEqual(completed.returncode, 3, completed.stdout)
                    self.assertIn("one safe executable", completed.stdout)
                    self.assertNotIn("DoNotEchoToolSelector", completed.stdout)
            selected = environment.copy()
            selected["BUILDER_IMAGE"] = "--DoNotEchoBuilderImage"
            completed = self.invoke(root, selected, "up")
            self.assertEqual(completed.returncode, 4, completed.stdout)
            self.assertIn("builder image reference is invalid", completed.stdout)
            self.assertNotIn("DoNotEchoBuilderImage", completed.stdout)
            self.assertFalse(docker_log.exists())
            self.assertFalse(compose_log.exists())

    def test_up_builds_current_source_into_project_scoped_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            self.write_env(root, project="hbcb-exact-source")
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            docker_commands = docker_log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                docker_commands[0],
                "build --file docker/builder.Dockerfile --target builder "
                "--tag hbcb-exact-source-builder:dev --platform linux/amd64 .",
            )
            self.assertIn(
                "image inspect --format {{.Os}}/{{.Architecture}}|{{.Id}} "
                "hbcb-exact-source-builder:dev",
                docker_commands,
            )
            compose_commands = [
                line.split("|", 1)[0]
                for line in compose_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(compose_commands, [
                "--project-name hbcb-exact-source --env-file .env build postgres",
                "--project-name hbcb-exact-source --env-file .env build minio",
                "--project-name hbcb-exact-source --env-file .env build api",
                "--project-name hbcb-exact-source --env-file .env build worker",
                "--project-name hbcb-exact-source --env-file .env up --detach --wait --wait-timeout 360",
            ])
            self.assertTrue(
                all(
                    line.split("|")[-1] == "hbcb-exact-source-builder:dev"
                    for line in compose_log.read_text(encoding="utf-8").splitlines()
                )
            )

    def test_up_honors_custom_builder_without_rebuilding_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, _compose_log = self.fixture(root)
            self.write_env(root)
            environment["BUILDER_IMAGE"] = "fixture-builder:release-check"
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            docker_commands = docker_log.read_text(encoding="utf-8").splitlines()
            self.assertFalse(any(command.startswith("build ") for command in docker_commands))
            self.assertEqual(
                docker_commands[0],
                "image inspect --format {{.Os}}/{{.Architecture}}|{{.Id}} "
                "fixture-builder:release-check",
            )

    def test_python_and_occupied_port_preflights_run_before_docker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            api_port, storage_port = 28080, 29000
            self.write_env(
                root, api_port=api_port, storage_port=storage_port
            )
            python_log = root / "python.log"
            old_python = root / "tools" / "python-3.10"
            write_executable(
                old_python,
                "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$FAKE_PYTHON_LOG\"\nexit 1\n",
            )
            old_environment = environment.copy()
            old_environment.update(
                {"PYTHON": str(old_python), "FAKE_PYTHON_LOG": str(python_log)}
            )
            old = self.invoke(root, old_environment, "up")
            self.assertEqual(old.returncode, 3, old.stdout)
            self.assertIn("Python 3.11+ is required", old.stdout)
            self.assertTrue(python_log.exists())
            self.assertFalse(docker_log.exists())
            self.assertFalse(compose_log.exists())

            blocked_environment = environment.copy()
            blocked_environment["FAKE_PORT_STATUS"] = "1"
            blocked = self.invoke(root, blocked_environment, "up")
            self.assertEqual(blocked.returncode, 5, blocked.stdout)
            self.assertIn("API loopback port is unavailable", blocked.stdout)
            self.assertFalse(docker_log.exists())
            self.assertIn(" port api 8080", compose_log.read_text(encoding="utf-8"))

    def postgres_probe_fixture(
        self, root: Path, environment: dict[str, str], *, project: str = "hbcb-test-checkout"
    ) -> dict[str, str]:
        self.write_env(root, project=project)
        selected = environment.copy()
        selected["FAKE_POSTGRES_IMAGE"] = project + "-postgres:16.15-alpine3.24-hbcb.1"
        return selected

    def test_incompatible_postgres_volume_blocks_up_before_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            project = "hbcb-test-checkout"
            environment = self.postgres_probe_fixture(root, environment, project=project)
            environment.update(
                {
                    "FAKE_POSTGRES_IMAGE_PRESENT": "1",
                    "FAKE_POSTGRES_VOLUME_PRESENT": "1",
                    "FAKE_POSTGRES_PROBE_STATUS": "3",
                }
            )
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 7, completed.stdout)
            self.assertIn(project + "_postgres-data", completed.stdout)
            self.assertIn(
                "troubleshooting.md#postgresql-image-upgrade-and-existing-volumes",
                completed.stdout,
            )
            self.assertFalse(compose_log.exists())

    def test_compatible_postgres_volume_lets_up_proceed_to_compose(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            environment = self.postgres_probe_fixture(root, environment)
            environment.update(
                {
                    "FAKE_POSTGRES_IMAGE_PRESENT": "1",
                    "FAKE_POSTGRES_VOLUME_PRESENT": "1",
                    "FAKE_POSTGRES_PROBE_STATUS": "0",
                }
            )
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue(compose_log.exists())

    def test_absent_postgres_volume_skips_probe_and_proceeds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            environment = self.postgres_probe_fixture(root, environment)
            environment.update(
                {
                    "FAKE_POSTGRES_IMAGE_PRESENT": "1",
                    # FAKE_POSTGRES_VOLUME_PRESENT intentionally unset.
                    "FAKE_POSTGRES_PROBE_STATUS": "3",
                }
            )
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            docker_commands = docker_log.read_text(encoding="utf-8").splitlines()
            self.assertFalse(any("--pids-limit" in command for command in docker_commands))
            self.assertTrue(compose_log.exists())

    def test_postgres_probe_infrastructure_error_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment, docker_log, compose_log = self.fixture(root)
            environment = self.postgres_probe_fixture(root, environment)
            environment.update(
                {
                    "FAKE_POSTGRES_IMAGE_PRESENT": "1",
                    "FAKE_POSTGRES_VOLUME_PRESENT": "1",
                    "FAKE_POSTGRES_PROBE_STATUS": "125",
                }
            )
            completed = self.invoke(root, environment, "up")
            self.assertEqual(completed.returncode, 0, completed.stdout)
            self.assertTrue(compose_log.exists())


if __name__ == "__main__":
    unittest.main()
