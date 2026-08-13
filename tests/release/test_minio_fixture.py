from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

SERVER_REVISION = "7aac2a2c5b7c882e68c1ce017d8256be2feea27f"
SERVER_ARCHIVE_SHA256 = "71794c2df26aad0cc99e8421c58b7aa2dd55969f979b0e7d1e931042e9fabcd6"
CLIENT_REVISION = "77f82e18b5401a65958f1619df6ebb994634bd88"
CLIENT_ARCHIVE_SHA256 = "167415edd21bc29f5360943dac64272aa5cda0a39f3070b15cfeca671c43d975"
GO_VERSION = "1.25.12"
GO_SHA256 = "234828b7a89e0e303d2556310ee549fbcf253d28de937bac3da13d6294262ac1"
FIXTURE_VERSION = "final-community-20260212-hbcb.1"

SERVER_MODULES = {
    "github.com/apache/thrift": "v0.23.0",
    "github.com/buger/jsonparser": "v1.1.2",
    "github.com/go-jose/go-jose/v4": "v4.1.4",
    "github.com/prometheus/prometheus": "v0.311.3",
    "go.opentelemetry.io/otel": "v1.43.0",
    "go.opentelemetry.io/otel/metric": "v1.43.0",
    "go.opentelemetry.io/otel/trace": "v1.43.0",
    "go.opentelemetry.io/otel/sdk": "v1.43.0",
    "go.opentelemetry.io/otel/sdk/metric": "v1.43.0",
    "golang.org/x/crypto": "v0.53.0",
    "golang.org/x/net": "v0.56.0",
    "golang.org/x/sys": "v0.46.0",
    "golang.org/x/text": "v0.39.0",
    "google.golang.org/grpc": "v1.82.1",
}


def assert_contract(
    test: unittest.TestCase,
    dockerfile: str,
    server_modules: str,
    client_modules: str,
) -> None:
    test.assertIn(f"go{GO_VERSION}.linux-amd64.tar.gz", dockerfile)
    test.assertIn(f"--checksum=sha256:{GO_SHA256}", dockerfile)
    test.assertIn(f"minio/archive/{SERVER_REVISION}.tar.gz", dockerfile)
    test.assertIn(f"--checksum=sha256:{SERVER_ARCHIVE_SHA256}", dockerfile)
    test.assertIn(f"mc/archive/{CLIENT_REVISION}.tar.gz", dockerfile)
    test.assertIn(f"--checksum=sha256:{CLIENT_ARCHIVE_SHA256}", dockerfile)
    test.assertNotIn("dl.min.io/client/mc", dockerfile)

    for module, version in SERVER_MODULES.items():
        test.assertRegex(server_modules, rf"(?m)^\s*{re.escape(module)} {re.escape(version)}(?:\s|$)", module)
    for module in (
        "github.com/prometheus/prometheus",
        "golang.org/x/crypto",
        "golang.org/x/net",
        "golang.org/x/sys",
        "golang.org/x/text",
        "google.golang.org/grpc",
    ):
        test.assertRegex(
            client_modules,
            rf"(?m)^\s*{re.escape(module)} {re.escape(SERVER_MODULES[module])}(?:\s|$)",
            module,
        )

    test.assertEqual(dockerfile.count("-mod=readonly"), 2)
    for overlay in ("minio.go.mod", "minio.go.sum", "mc.go.mod", "mc.go.sum"):
        test.assertIn("docker/minio-modules/" + overlay, dockerfile)
    test.assertIn(f'org.opencontainers.image.version="{FIXTURE_VERSION}"', dockerfile)
    test.assertIn(f'org.opencontainers.image.revision="{SERVER_REVISION}"', dockerfile)
    test.assertIn(f'io.hbcb.mc-revision="{CLIENT_REVISION}"', dockerfile)
    test.assertIn(f"commit-id={SERVER_REVISION}", dockerfile)
    test.assertIn(f"commit-id={CLIENT_REVISION}", dockerfile)
    for name in ("MINIO-LICENSE", "MINIO-CREDITS", "MC-LICENSE", "MC-CREDITS"):
        test.assertIn(name, dockerfile)


class MinioFixturePolicyTests(unittest.TestCase):
    def test_final_source_and_security_module_contract_is_exact(self) -> None:
        dockerfile = (ROOT / "docker" / "minio.Dockerfile").read_text(encoding="utf-8")
        server_modules = (ROOT / "docker" / "minio-modules" / "minio.go.mod").read_text(encoding="utf-8")
        client_modules = (ROOT / "docker" / "minio-modules" / "mc.go.mod").read_text(encoding="utf-8")
        assert_contract(self, dockerfile, server_modules, client_modules)

        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        common = (ROOT / "scripts" / "service-common").read_text(encoding="utf-8")
        wrapper = (ROOT / "scripts" / "service-compose").read_text(encoding="utf-8")
        recovery = (ROOT / "scripts" / "g8-recovery-drill").read_text(encoding="utf-8")
        for source in (compose, common, wrapper, recovery):
            self.assertIn(FIXTURE_VERSION, source)
        self.assertIn(SERVER_REVISION, wrapper)

        # The local fixture is a single-node, loopback-published compatibility
        # service. Identity-provider configuration must not enter Compose.
        self.assertNotRegex(compose, r"MINIO_IDENTITY_(?:OPENID|LDAP)")
        self.assertIn('command: ["server", "/data", "--address", ":9000"]', compose)
        self.assertIn('"127.0.0.1:${HBCB_STORAGE_HOST_PORT:-9000}:9000"', compose)

    def test_security_contract_mutations_fail(self) -> None:
        original = (ROOT / "docker" / "minio.Dockerfile").read_text(encoding="utf-8")
        original_server = (ROOT / "docker" / "minio-modules" / "minio.go.mod").read_text(encoding="utf-8")
        original_client = (ROOT / "docker" / "minio-modules" / "mc.go.mod").read_text(encoding="utf-8")
        mutations = {
            "server revision": (SERVER_REVISION, "0" * 40),
            "server archive checksum": (SERVER_ARCHIVE_SHA256, "1" * 64),
            "client revision": (CLIENT_REVISION, "2" * 40),
            "Go checksum": (GO_SHA256, "3" * 64),
            "read-only module build": ("-mod=readonly", "-mod=mod"),
        }
        for label, (before, after) in mutations.items():
            with self.subTest(label=label):
                mutated = original.replace(before, after, 1)
                self.assertNotEqual(mutated, original)
                with self.assertRaises(AssertionError):
                    assert_contract(self, mutated, original_server, original_client)

        for label, source, before, after in (
            ("server crypto module", original_server, "golang.org/x/crypto v0.53.0", "golang.org/x/crypto v0.52.0"),
            ("server gRPC module", original_server, "google.golang.org/grpc v1.82.1", "google.golang.org/grpc v1.81.0"),
            ("client crypto module", original_client, "golang.org/x/crypto v0.53.0", "golang.org/x/crypto v0.52.0"),
        ):
            with self.subTest(label=label):
                mutated = source.replace(before, after, 1)
                with self.assertRaises(AssertionError):
                    assert_contract(
                        self,
                        original,
                        mutated if source is original_server else original_server,
                        mutated if source is original_client else original_client,
                    )


if __name__ == "__main__":
    unittest.main()
