from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ServiceOnboardingTests(unittest.TestCase):
    def test_make_exposes_wrapper_backed_service_lifecycle(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        for target, action in (
            ("service-config", "config"),
            ("service-up", "up"),
            ("service-ps", "ps"),
            ("service-logs", "logs"),
            ("service-down", "down"),
        ):
            self.assertRegex(makefile, rf"(?m)^{target}:\s*$")
            recipe = re.search(
                rf"(?ms)^{target}:\s*\n(.*?)(?=^[A-Za-z0-9_.-]+:|\Z)",
                makefile,
            )
            self.assertIsNotNone(recipe, target)
            assert recipe is not None
            self.assertIn(f"./scripts/service-compose {action}", recipe.group(1))
            self.assertIn('DOCKER="$(DOCKER)"', recipe.group(1))
            self.assertIn('PYTHON="$(PYTHON)"', recipe.group(1))

        self.assertNotRegex(makefile, r"(?m)^service-(?:config|up):\s+ensure-image")
        smoke = re.search(
            r"(?ms)^service-smoke:\s*\n(.*?)(?=^[A-Za-z0-9_.-]+:|\Z)",
            makefile,
        )
        self.assertIsNotNone(smoke)
        assert smoke is not None
        self.assertIn('DOCKER="$(DOCKER)"', smoke.group(1))
        self.assertIn('PYTHON="$(PYTHON)"', smoke.group(1))
        self.assertRegex(makefile, r"(?m)^service-client:\s*$")
        self.assertIn("./scripts/service-client --request", makefile)
        self.assertTrue((ROOT / "scripts" / "service-client").is_file())

    def test_public_service_docs_use_project_wrappers_not_raw_compose(self) -> None:
        documents = (
            "README.md",
            "SUPPORT.md",
            "docs/installation.md",
            "docs/configuration.md",
            "docs/troubleshooting.md",
            "docs/api.md",
            "docs/compatibility.md",
        )
        for relative in documents:
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(document=relative):
                self.assertIsNone(re.search(r"(?m)^\s*docker compose\b", text))

        combined = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8") for relative in documents
        )
        for marker in (
            "make service-config",
            "make service-up",
            "make service-ps",
            "make service-logs",
            "make service-down",
            "HBCB_COMPOSE_PROJECT_NAME",
            "COMPOSE_PROJECT_NAME",
            "HBCB_API_HOST_PORT",
            "HBCB_STORAGE_HOST_PORT",
            "PYTHON=python3.11",
        ):
            self.assertIn(marker, combined, marker)

    def test_api_journey_is_customizable_and_preserves_a_result(self) -> None:
        api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")

        for marker in (
            "HBCB_PYTHON=${PYTHON:-python3}",
            ". ./scripts/service-common",
            "hbcb_service_settings",
            "HBCB_REQUEST=${HBCB_REQUEST:-examples/requests/facet-bot.json}",
            '--data-binary @"$HBCB_REQUEST"',
            "HBCB_RESULT_CANDIDATE=$PWD/build/service-client/$HBCB_BUILD_ID",
            "HBCB_RESERVED_RESULT=$HBCB_RESULT_CANDIDATE",
            "HBCB_RESULT=$HBCB_RESERVED_RESULT/artifacts",
            'cp "$HBCB_API_TMP/status.json" "$HBCB_STAGE/build.json"',
            '"model.blend", "model.glb", "model.stl", "preview.png"',
            "digest.hexdigest() != expected_hash",
            'if test "$HBCB_BUILD_STATUS" != succeeded',
            "class RejectRedirects(urllib.request.HTTPRedirectHandler)",
            "urllib.request.ProxyHandler({})",
            "os.rename(stage, result)",
            "hbcb_service_env_private",
            "HBCB_CANCEL_ON_EXIT=1",
            "terminal_code",
            "1200",
        ):
            self.assertIn(marker, api, marker)
        self.assertNotIn("facet-request-0001", api)
        self.assertIn("Omitting `Idempotency-Key`", api)
        self.assertIn("## Lightweight local client", api)
        self.assertIn("make service-client", api)
        self.assertNotIn(
            'cp "$HBCB_API_TMP/artifacts.json" "$HBCB_STAGE/artifacts.json"',
            api,
        )

    def test_api_cleanup_never_owns_a_preexisting_result_candidate(self) -> None:
        api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
        candidate = api.index(
            "HBCB_RESULT_CANDIDATE=$PWD/build/service-client/$HBCB_BUILD_ID"
        )
        reservation = api.index('os.mkdir(reservation, 0o700)', candidate)
        ownership = api.index(
            "HBCB_RESERVED_RESULT=$HBCB_RESULT_CANDIDATE", reservation
        )
        cleanup = api.index('test -n "$HBCB_RESERVED_RESULT"')
        self.assertLess(cleanup, candidate)
        self.assertLess(candidate, reservation)
        self.assertLess(reservation, ownership)
        self.assertNotIn(
            "HBCB_RESERVED_RESULT=$PWD/build/service-client/$HBCB_BUILD_ID",
            api,
        )

    def test_api_reservation_preserves_existing_file_directory_and_symlink(self) -> None:
        api = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
        match = re.search(
            r'"\$HBCB_PYTHON" - "\$HBCB_RESULT_CANDIDATE" <<\'PY\'\n'
            r"(.*?)\nPY\nHBCB_RESERVED_RESULT=",
            api,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        reservation_script = match.group(1)
        with tempfile.TemporaryDirectory(prefix="hbcb-api-reservation-") as raw:
            root = Path(raw)
            targets = []
            existing_file = root / "existing-file"
            existing_file.write_bytes(b"file-sentinel")
            targets.append(("file", existing_file))
            existing_directory = root / "existing-directory"
            existing_directory.mkdir()
            (existing_directory / "sentinel").write_bytes(b"directory-sentinel")
            targets.append(("directory", existing_directory))
            link_target = root / "link-target"
            link_target.write_bytes(b"symlink-sentinel")
            existing_symlink = root / "existing-symlink"
            existing_symlink.symlink_to(link_target)
            targets.append(("symlink", existing_symlink))

            for label, target in targets:
                with self.subTest(label=label):
                    completed = subprocess.run(
                        (sys.executable, "-", str(target)),
                        input=reservation_script,
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    self.assertNotEqual(completed.returncode, 0, completed.stdout)
            self.assertEqual(existing_file.read_bytes(), b"file-sentinel")
            self.assertEqual(
                (existing_directory / "sentinel").read_bytes(),
                b"directory-sentinel",
            )
            self.assertTrue(existing_symlink.is_symlink())
            self.assertEqual(existing_symlink.resolve(), link_target.resolve())
            self.assertEqual(link_target.read_bytes(), b"symlink-sentinel")

    def test_service_resource_and_smoke_scope_are_explicit(self) -> None:
        installation = (ROOT / "docs" / "installation.md").read_text(
            encoding="utf-8"
        )
        compatibility = (ROOT / "docs" / "compatibility.md").read_text(
            encoding="utf-8"
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        combined = "\n".join((installation, compatibility, readme))

        for marker in (
            "7 GiB RAM and 7.5 CPUs",
            "7.375 GiB and 8.25 CPUs",
            "20 GB free disk",
            "at least 12 GiB Docker memory",
            "maintainer/integration confidence gate",
        ):
            self.assertIn(marker, combined, marker)
        self.assertNotRegex(
            readme,
            r"(?s)make init-env\s+make service-up\s+make service-smoke",
        )


if __name__ == "__main__":
    unittest.main()
