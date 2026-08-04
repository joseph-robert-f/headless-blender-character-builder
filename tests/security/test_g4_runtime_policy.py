"""Fast regression tests for the independent G4 Docker-policy parser."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import List, Tuple

from tests.security.g4_runtime_policy import (
    RuntimePolicyFailure,
    assert_hardened_run,
    assert_image_policy,
)


class G4RuntimePolicyTests(unittest.TestCase):
    def _fixture(self, command: str = "build", output_readonly: bool = False) -> Tuple[tempfile.TemporaryDirectory, Path, Path, Path, List[str]]:
        temporary = tempfile.TemporaryDirectory(prefix="hbcb-g4-policy-")
        root = Path(temporary.name)
        source = root / "source"
        workspace = root / "workspace"
        request = source / "examples" / "requests" / "facet-bot.json"
        output = source / "build"
        request.parent.mkdir(parents=True)
        workspace.mkdir()
        output.mkdir()
        request.write_text("{}\n", encoding="utf-8")
        output_mount = "type=bind,source=%s,target=/output" % output
        if output_readonly:
            output_mount += ",readonly"
        argv = [
            "run",
            "--rm",
            "--platform",
            "linux/amd64",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            "512",
            "--cpus",
            "4",
            "--memory",
            "8g",
            "--user",
            "65532:65532",
            "--tmpfs",
            "/work:rw,nosuid,nodev,noexec,size=2g,mode=1777",
            "--mount",
            "type=bind,source=%s,target=/input/request.json,readonly" % request,
            "--mount",
            output_mount,
            "--env",
            "HBCB_EXECUTION_MODE=container",
            "--env",
            "HBCB_WORKER_IMAGE_REFERENCE=example:gate",
            "--env",
            "HBCB_WORKER_IMAGE_ID=sha256:" + "a" * 64,
            "example:gate",
            command,
            "--request",
            "/input/request.json",
            "--output",
            "/output/demo",
        ]
        return temporary, source, workspace, request, argv

    def test_accepts_exact_build_contract(self) -> None:
        temporary, source, workspace, request, argv = self._fixture()
        with temporary:
            evidence = assert_hardened_run(
                argv,
                clean_source=source,
                workspace=workspace,
                expected_image="example:gate",
                expected_request=request,
                expected_output=source / "build",
                expected_platform="linux/amd64",
                expected_user="65532:65532",
            )
        self.assertEqual(evidence["network"], "none")
        self.assertTrue(evidence["no_new_privileges"])

    def test_accepts_read_only_verifier_contract(self) -> None:
        temporary, source, workspace, request, argv = self._fixture("verify", True)
        with temporary:
            evidence = assert_hardened_run(
                argv,
                clean_source=source,
                workspace=workspace,
                expected_image="example:gate",
                expected_request=request,
                expected_output=source / "build",
                expected_platform="linux/amd64",
                expected_user="65532:65532",
                expected_command="verify",
                output_readonly=True,
            )
        self.assertEqual(evidence["verified_command"], "verify")

    def test_rejects_runtime_network(self) -> None:
        temporary, source, workspace, request, argv = self._fixture()
        with temporary:
            argv[argv.index("none")] = "bridge"
            with self.assertRaises(RuntimePolicyFailure):
                assert_hardened_run(
                    argv,
                    clean_source=source,
                    workspace=workspace,
                    expected_image="example:gate",
                    expected_request=request,
                    expected_output=source / "build",
                    expected_platform="linux/amd64",
                    expected_user="65532:65532",
                )

    def test_rejects_extra_socket_mount(self) -> None:
        temporary, source, workspace, request, argv = self._fixture()
        with temporary:
            image_index = argv.index("example:gate")
            argv[image_index:image_index] = [
                "--mount",
                "type=bind,source=/var/run/docker.sock,target=/docker.sock",
            ]
            with self.assertRaises(RuntimePolicyFailure):
                assert_hardened_run(
                    argv,
                    clean_source=source,
                    workspace=workspace,
                    expected_image="example:gate",
                    expected_request=request,
                    expected_output=source / "build",
                    expected_platform="linux/amd64",
                    expected_user="65532:65532",
                )

    def test_rejects_mismatched_host_user_and_provenance(self) -> None:
        temporary, source, workspace, request, argv = self._fixture()
        with temporary:
            with self.assertRaises(RuntimePolicyFailure):
                assert_hardened_run(
                    argv,
                    clean_source=source,
                    workspace=workspace,
                    expected_image="example:gate",
                    expected_request=request,
                    expected_output=source / "build",
                    expected_platform="linux/amd64",
                    expected_user="501:20",
                )
            assignment = "HBCB_WORKER_IMAGE_REFERENCE=example:gate"
            argv[argv.index(assignment)] = "HBCB_WORKER_IMAGE_REFERENCE=other:tag"
            with self.assertRaises(RuntimePolicyFailure):
                assert_hardened_run(
                    argv,
                    clean_source=source,
                    workspace=workspace,
                    expected_image="example:gate",
                    expected_request=request,
                    expected_output=source / "build",
                    expected_platform="linux/amd64",
                    expected_user="65532:65532",
                )

    def test_rejects_root_and_missing_noexec(self) -> None:
        temporary, source, workspace, request, argv = self._fixture()
        with temporary:
            argv[argv.index("65532:65532")] = "0:0"
            argv[argv.index("/work:rw,nosuid,nodev,noexec,size=2g,mode=1777")] = (
                "/work:rw,nosuid,nodev,size=2g,mode=1777"
            )
            with self.assertRaises(RuntimePolicyFailure):
                assert_hardened_run(
                    argv,
                    clean_source=source,
                    workspace=workspace,
                    expected_image="example:gate",
                    expected_request=request,
                    expected_output=source / "build",
                    expected_platform="linux/amd64",
                    expected_user="65532:65532",
                )

    def test_image_policy_rejects_secret_environment(self) -> None:
        image = {
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": ["/usr/local/bin/builder"],
                "Env": ["OPENAI_API_KEY=forbidden"],
                "Labels": {
                    "org.blender.download.sha256": "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25",
                    "org.blender.version": "4.5.12 LTS",
                    "org.opencontainers.image.licenses": "GPL-3.0-or-later",
                },
                "User": "65532:65532",
            },
            "Id": "sha256:" + "a" * 64,
            "Os": "linux",
            "RepoDigests": [],
        }
        with self.assertRaises(RuntimePolicyFailure):
            assert_image_policy(
                image,
                expected_platform="linux/amd64",
                forbidden_values=("forbidden",),
            )

    def test_image_policy_rejects_canary_outside_environment(self) -> None:
        image = {
            "Architecture": "amd64",
            "Config": {
                "Entrypoint": ["/usr/local/bin/builder"],
                "Env": [],
                "Labels": {
                    "g4.audit": "embedded-canary",
                    "org.blender.download.sha256": "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25",
                    "org.blender.version": "4.5.12 LTS",
                    "org.opencontainers.image.licenses": "GPL-3.0-or-later",
                },
                "User": "65532:65532",
            },
            "Id": "sha256:" + "a" * 64,
            "Os": "linux",
            "RepoDigests": [],
        }
        with self.assertRaises(RuntimePolicyFailure):
            assert_image_policy(
                image,
                expected_platform="linux/amd64",
                forbidden_values=("embedded-canary",),
            )


if __name__ == "__main__":
    unittest.main()
