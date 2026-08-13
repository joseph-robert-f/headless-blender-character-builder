from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import ModuleType
from typing import Dict, Mapping


ROOT = Path(__file__).resolve().parents[2]


def load_script(module_name: str, script_name: str) -> ModuleType:
    script = ROOT / "scripts" / script_name
    if not script.is_file():
        raise unittest.SkipTest(
            "release tooling is intentionally outside the immutable G4 test image; "
            "run tests/release with the host release gate"
        )
    loader = importlib.machinery.SourceFileLoader(module_name, str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def write(path: Path, payload: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(mode)


def git(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository)] + list(arguments),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0"),
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", "replace"))
    return completed.stdout


def make_audit_repository(root: Path) -> Path:
    repository = root / "repository"
    repository.mkdir(mode=0o755)
    license_payload = (ROOT / "LICENSE").read_bytes()
    policy = {
        "asset_license": "CC0-1.0",
        "asset_policy_path": "ASSET_LICENSE.md",
        "format": "hbcb-license-policy/v1",
        "metadata_requirements": {
            "docker/builder.Dockerfile": [
                'org.opencontainers.image.licenses="GPL-3.0-or-later"'
            ],
            "docker/service.Dockerfile": [
                'org.opencontainers.image.licenses="GPL-3.0-or-later"'
            ],
            "pyproject.toml": ['license = "GPL-3.0-or-later"'],
            "service/pyproject.toml": ['license = "GPL-3.0-or-later"'],
        },
        "root_license_path": "LICENSE",
        "root_license_sha256": hashlib.sha256(license_payload).hexdigest(),
        "source_license": "GPL-3.0-or-later",
    }
    files = {
        "ASSET_LICENSE.md": b"Original samples use CC0 1.0 Universal.\n",
        "LICENSE": license_payload,
        "README.md": b"# Safe fixture\n",
        "docker/builder.Dockerfile": b'LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"\n',
        "docker/service.Dockerfile": b'LABEL org.opencontainers.image.licenses="GPL-3.0-or-later"\n',
        "docs/assets/preview.png": b"\x89PNG\r\n\x1a\nfixture\x00",
        "pyproject.toml": b'[project]\nlicense = "GPL-3.0-or-later"\n',
        "release/license-policy.json": (
            json.dumps(policy, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8"),
        "scripts/example": b"#!/bin/sh\nexit 0\n",
        "service/pyproject.toml": b'[project]\nlicense = "GPL-3.0-or-later"\n',
    }
    for name, payload in files.items():
        write(repository / name, payload, 0o755 if name == "scripts/example" else 0o644)
    git(repository, "init", "-q")
    git(repository, "config", "user.name", "Release Test")
    git(repository, "config", "user.email", "release-test@example.invalid")
    git(repository, "add", "--all")
    git(repository, "commit", "-qm", "fixture")
    return repository


def export_index(repository: Path, destination: Path) -> None:
    destination.mkdir(mode=0o755)
    git(
        repository,
        "checkout-index",
        "--all",
        "--force",
        "--prefix=" + str(destination) + os.sep,
    )


def spdx_document(package_name: str) -> bytes:
    document = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": "1970-01-01T00:00:00Z",
            "creators": ["Tool: release-test/1"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": "https://example.invalid/sbom/" + package_name,
        "name": package_name,
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-HBCB",
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": "a" * 64}
                ],
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "GPL-3.0-or-later",
                "licenseDeclared": "GPL-3.0-or-later",
                "name": package_name,
                "versionInfo": "0.1.0",
            },
            {
                "SPDXID": "SPDXRef-Package-Blender",
                "checksums": [
                    {"algorithm": "SHA256", "checksumValue": "b" * 64}
                ],
                "copyrightText": "NOASSERTION",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "GPL-3.0-or-later",
                "licenseDeclared": "GPL-3.0-or-later",
                "name": "Blender",
                "versionInfo": "4.5.12 LTS",
            },
        ],
        "relationships": [
            {
                "relatedSpdxElement": "SPDXRef-Package-HBCB",
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            }
        ],
        "spdxVersion": "SPDX-2.3",
    }
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def audit_report(files: Mapping[str, bytes]) -> Dict[str, object]:
    rows = []
    tree = hashlib.sha256()
    total = 0
    for path in sorted(files, key=lambda item: item.encode("utf-8")):
        payload = files[path]
        mode = "100755" if path.startswith("scripts/") else "100644"
        digest = hashlib.sha256(payload).hexdigest()
        tree.update(
            mode.encode("ascii")
            + b"\0"
            + path.encode("utf-8")
            + b"\0"
            + str(len(payload)).encode("ascii")
            + b"\0"
            + digest.encode("ascii")
            + b"\n"
        )
        rows.append(
            {"bytes": len(payload), "git_mode": mode, "path": path, "sha256": digest}
        )
        total += len(payload)
    return {
        "asset_license": "CC0-1.0",
        "file_count": len(rows),
        "files": rows,
        "format": "hbcb-release-audit/v1",
        "git_head": "a" * 40,
        "git_index_sha256": "b" * 64,
        "source_license": "GPL-3.0-or-later",
        "source_tree_sha256": tree.hexdigest(),
        "total_bytes": total,
    }


def image_inspect(
    role: str,
    number: int,
    version: str = "0.1.0-rc.1",
    revision: str = "a" * 40,
) -> bytes:
    title = {
        "api": "Headless Blender Character Builder service",
        "builder": "Headless Blender Character Builder",
        "worker": "Headless Blender Character Builder supervisor",
    }[role]
    document = [
        {
            "Architecture": "amd64",
            "Config": {
                "Env": ["IGNORED_CANARY=value"],
                "Labels": {
                    "org.opencontainers.image.licenses": "GPL-3.0-or-later",
                    "org.opencontainers.image.revision": revision,
                    "org.opencontainers.image.source": "https://github.com/joseph-robert-f/headless-blender-character-builder",
                    "org.opencontainers.image.title": title,
                    "org.opencontainers.image.version": version,
                    **(
                        {
                            "org.blender.download.sha256": "95e3a2dfedba3bd32ca54fc355eac6b15a11986954ccb02815a07535d0120a25",
                            "org.blender.version": "4.5.12 LTS",
                        }
                        if role in {"builder", "worker"}
                        else {}
                    ),
                },
            },
            "Id": "sha256:" + str(number) * 64,
            "Os": "linux",
            "RepoDigests": [],
            "RepoTags": [
                {
                    "api": "headless-blender-character-builder-api",
                    "builder": "headless-blender-character-builder",
                    "worker": "headless-blender-character-builder-worker",
                }[role]
                + ":"
                + version
            ],
            "RootFS": {"Layers": ["sha256:" + str(number + 3) * 64]},
        }
    ]
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sample_artifacts(builder_image_id: str) -> Dict[str, bytes]:
    artifacts = {
        "diagnostics/back.png": b"back-png\x00",
        "diagnostics/front.png": b"front-png\x00",
        "diagnostics/side.png": b"side-png\x00",
        "model.blend": b"BLENDER-v300\x00fixture",
        "model.glb": b"glTFfixture\x00",
        "model.stl": b"solid fixture\nendsolid fixture\n",
        "preview.png": b"preview-png\x00",
    }
    qa = {
        "checks": {"manifold": True},
        "measurements": {"triangle_count": 12},
        "notes": [],
        "qa_version": "qa/v1",
        "status": "passed",
    }
    artifacts["qa.json"] = (
        json.dumps(qa, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    manifest_entries = {
        path: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        for path, payload in artifacts.items()
    }
    manifest = {
        "artifacts": manifest_entries,
        "execution": {
            "mode": "container",
            "worker_image_id": builder_image_id,
        },
        "manifest_version": "manifest/v1",
        "qa": {"status": "passed"},
    }
    artifacts["manifest.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return artifacts
