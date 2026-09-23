from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests" / "deployment" / "g8_caddy_gate.py"
SPEC = importlib.util.spec_from_file_location("g8_caddy_gate_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)

EXPECTED_DIGEST = "sha256:" + gate.CADDY_DIGEST
VALID_IDENTITY = (
    gate.CADDY_OCI_VERSION
    + "\n"
    + gate.CADDY_OCI_VERSION
    + " h1:reviewed-runtime-hash\nLinux\nx86_64\n"
).encode("ascii")


def completed(
    returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(("docker",), returncode, stdout, stderr)


class CaddyDigestInspectionTests(unittest.TestCase):
    def inspect(self, document: object) -> list[str]:
        commands: list[list[str]] = []

        def run(
            command: list[str], *, label: str
        ) -> subprocess.CompletedProcess[bytes]:
            self.assertEqual(label, "pinned Caddy digest inspection")
            commands.append(list(command))
            return completed(stdout=json.dumps(document).encode("utf-8"))

        with mock.patch.object(gate, "_run", side_effect=run):
            gate._inspect_digest("docker")
        self.assertEqual(len(commands), 1)
        return commands[0]

    def test_docker_29_oci_index_digest_passes_without_config_metadata(self) -> None:
        command = self.inspect(
            [
                {
                    "Architecture": "",
                    "Config": {},
                    "Descriptor": {
                        "digest": EXPECTED_DIGEST,
                        "mediaType": "application/vnd.oci.image.index.v1+json",
                    },
                    "Id": EXPECTED_DIGEST,
                    "Os": "",
                    "RepoDigests": ["caddy@" + EXPECTED_DIGEST],
                }
            ]
        )
        self.assertEqual(
            command, ["docker", "image", "inspect", gate.CADDY_REFERENCE]
        )
        self.assertNotIn("--platform", command)
        self.assertNotIn("--format", command)

    def test_classic_store_repo_digest_passes_without_descriptor(self) -> None:
        command = self.inspect(
            [
                {
                    "Architecture": "amd64",
                    "Config": {"Labels": {"org.opencontainers.image.version": "ignored"}},
                    "Id": "sha256:" + "a" * 64,
                    "Os": "linux",
                    "RepoDigests": ["caddy@" + EXPECTED_DIGEST],
                }
            ]
        )
        self.assertEqual(command[-1], gate.CADDY_REFERENCE)

    def test_id_and_descriptor_digest_channels_each_pass_independently(self) -> None:
        for document in (
            [{"Id": EXPECTED_DIGEST, "RepoDigests": []}],
            [{"Descriptor": {"digest": EXPECTED_DIGEST}, "RepoDigests": []}],
        ):
            with self.subTest(document=document):
                self.assertEqual(self.inspect(document)[-1], gate.CADDY_REFERENCE)

    def test_invalid_or_unrelated_inspection_payloads_fail_closed(self) -> None:
        wrong_digest = "sha256:" + "0" * 64
        malformed_documents = (
            [],
            [{"Id": wrong_digest, "RepoDigests": ["caddy@" + wrong_digest]}],
            [{"Id": [EXPECTED_DIGEST], "RepoDigests": []}],
            [{"Descriptor": [EXPECTED_DIGEST], "RepoDigests": []}],
            [{"Descriptor": {"digest": [EXPECTED_DIGEST]}, "RepoDigests": []}],
            [{"RepoDigests": "caddy@" + EXPECTED_DIGEST}],
            [{"RepoDigests": [42, "caddy@" + EXPECTED_DIGEST]}],
            [{"RepoDigests": [EXPECTED_DIGEST]}],
            [{"RepoDigests": ["@" + EXPECTED_DIGEST]}],
            [{"RepoDigests": []}, {"RepoDigests": ["caddy@" + EXPECTED_DIGEST]}],
            {"RepoDigests": ["caddy@" + EXPECTED_DIGEST]},
        )
        for document in malformed_documents:
            with self.subTest(document=document), mock.patch.object(
                gate,
                "_run",
                return_value=completed(stdout=json.dumps(document).encode("utf-8")),
            ):
                with self.assertRaisesRegex(gate.GateFailure, "identity is invalid"):
                    gate._inspect_digest("docker")

        for payload in (b"not-json", b"\xff"):
            with self.subTest(payload=payload), mock.patch.object(
                gate, "_run", return_value=completed(stdout=payload)
            ):
                with self.assertRaisesRegex(gate.GateFailure, "identity is invalid"):
                    gate._inspect_digest("docker")


class CaddyRuntimeIdentityTests(unittest.TestCase):
    def test_exact_reference_runs_in_a_hardened_linux_amd64_container(self) -> None:
        calls: list[tuple[list[str], str]] = []

        def run(
            command: list[str], *, label: str
        ) -> subprocess.CompletedProcess[bytes]:
            calls.append((list(command), label))
            return completed(stdout=VALID_IDENTITY)

        with mock.patch.object(gate, "_run", side_effect=run):
            gate._runtime_identity("docker")

        self.assertEqual(len(calls), 1)
        command, label = calls[0]
        self.assertEqual(label, "pinned Caddy runtime identity")
        self.assertEqual(command[0:2], ["docker", "run"])
        self.assertEqual(command[command.index("--platform") + 1], gate.CADDY_PLATFORM)
        self.assertEqual(command[command.index("--network") + 1], "none")
        self.assertIn("--read-only", command)
        self.assertEqual(command[command.index("--cap-drop") + 1], "ALL")
        self.assertEqual(
            command[command.index("--cap-add") + 1], "NET_BIND_SERVICE"
        )
        self.assertEqual(
            command[command.index("--security-opt") + 1],
            "no-new-privileges:true",
        )
        self.assertIn(gate.CADDY_REFERENCE, command)
        self.assertNotIn("inspect", command)
        self.assertEqual(
            command[-5:],
            [
                gate.CADDY_REFERENCE,
                "/bin/sh",
                "-eu",
                "-c",
                'printf \'%s\\n\' "$CADDY_VERSION"\ncaddy version\nuname -s\nuname -m',
            ],
        )

    def test_runtime_identity_mutations_fail_closed(self) -> None:
        invalid = (
            b"v2.11.3\nv2.11.4 h1:ok\nLinux\nx86_64\n",
            b"v2.11.4\nv2.11.3 h1:wrong\nLinux\nx86_64\n",
            b"v2.11.4\n\nLinux\nx86_64\n",
            b"v2.11.4\nv2.11.4 h1:ok\nDarwin\nx86_64\n",
            b"v2.11.4\nv2.11.4 h1:ok\nLinux\naarch64\n",
            b"v2.11.4\nv2.11.4 h1:ok\nLinux\n",
            b"v2.11.4\nv2.11.4 h1:ok\nLinux\nx86_64\nextra\n",
            b"\xff\nv2.11.4 h1:ok\nLinux\nx86_64\n",
        )
        for stdout in invalid:
            with self.subTest(stdout=stdout), mock.patch.object(
                gate, "_run", return_value=completed(stdout=stdout)
            ):
                with self.assertRaisesRegex(gate.GateFailure, "identity is invalid"):
                    gate._runtime_identity("docker")

        with mock.patch.object(
            gate,
            "_run",
            return_value=completed(
                stdout=VALID_IDENTITY, stderr=b"unexpected warning\n"
            ),
        ):
            with self.assertRaisesRegex(gate.GateFailure, "identity is invalid"):
                gate._runtime_identity("docker")


class CaddyCustomBuildTests(unittest.TestCase):
    def test_build_inspects_exact_local_image_and_binds_runtime_to_id(self) -> None:
        image_id = "sha256:" + "a" * 64
        tag = "hbcb-caddy-g8:scan-" + "b" * 24
        payload = [
            {
                "Id": image_id,
                "Os": "linux",
                "Architecture": "amd64",
                "Config": {
                    "Labels": {
                        "org.opencontainers.image.version": gate.CADDY_CUSTOM_VERSION
                    }
                },
            }
        ]
        calls: list[tuple[list[str], str, int]] = []

        def run(command: list[str], *, label: str, timeout: int = 120):
            calls.append((list(command), label, timeout))
            return completed(
                stdout=json.dumps(payload).encode("utf-8")
                if label == "custom Caddy inspection"
                else b""
            )

        with mock.patch.object(gate.secrets, "token_hex", return_value="b" * 24), mock.patch.object(
            gate, "_run", side_effect=run
        ):
            self.assertEqual(gate._build_custom("docker"), (tag, image_id))
        self.assertEqual(len(calls), 2)
        build, label, timeout = calls[0]
        self.assertEqual(label, "custom Caddy build")
        self.assertEqual(timeout, 1800)
        self.assertEqual(build[build.index("--file") + 1], "docker/caddy.Dockerfile")
        self.assertEqual(build[build.index("--target") + 1], "caddy")
        self.assertEqual(build[build.index("--platform") + 1], gate.CADDY_PLATFORM)
        self.assertEqual(build[build.index("--tag") + 1], tag)
        self.assertEqual(calls[1][0], ["docker", "image", "inspect", tag])

        runtime = gate._custom_runtime("docker", image_id, ["caddy", "version"])
        self.assertIn(image_id, runtime)
        self.assertNotIn(tag, runtime)
        self.assertEqual(runtime[runtime.index("--network") + 1], "none")
        self.assertIn("--read-only", runtime)
        self.assertEqual(runtime[runtime.index("--cap-drop") + 1], "ALL")
        self.assertEqual(runtime[runtime.index("--platform") + 1], gate.CADDY_PLATFORM)

    def test_custom_build_rejects_wrong_platform_or_version(self) -> None:
        valid = {
            "Id": "sha256:" + "a" * 64,
            "Os": "linux",
            "Architecture": "amd64",
            "Config": {
                "Labels": {"org.opencontainers.image.version": gate.CADDY_CUSTOM_VERSION}
            },
        }
        for mutation in (
            {"Architecture": "arm64"},
            {"Os": "darwin"},
            {"Id": "latest"},
            {"Config": {"Labels": {"org.opencontainers.image.version": "v2.11.3"}}},
        ):
            with self.subTest(mutation=mutation):
                document = dict(valid, **mutation)

                def run(_command: list[str], *, label: str, timeout: int = 120):
                    return completed(
                        stdout=json.dumps([document]).encode("utf-8")
                        if label == "custom Caddy inspection"
                        else b""
                    )

                with mock.patch.object(gate, "_run", side_effect=run):
                    with self.assertRaisesRegex(gate.GateFailure, "custom Caddy identity"):
                        gate._build_custom("docker")

if __name__ == "__main__":
    unittest.main()
