from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.release.support import ROOT, load_script, write


fetcher = load_script("fetch_corresponding_source_under_test", "fetch-corresponding-source")


class _Response:
    status = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: bytes, url: str) -> None:
        self._payload = payload
        self._url = url
        self._offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        result = self._payload[self._offset : self._offset + size]
        self._offset += len(result)
        return result

    def geturl(self) -> str:
        return self._url

    def close(self) -> None:
        self.closed = True


class CorrespondingSourceTests(unittest.TestCase):
    def _policy(self, root: Path, payload: bytes) -> tuple[Path, dict[str, object]]:
        archive = "blender-4.5.12.tar.xz"
        blender = {
            "archive": archive,
            "bytes": len(payload),
            "license": "GPL-3.0-or-later",
            "official_md5": hashlib.md5(payload).hexdigest(),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "source_url": "https://download.blender.org/source/" + archive,
            "version": "4.5.12",
        }
        policy = {
            "blender": blender,
            "format": "hbcb-corresponding-source-policy/v1",
        }
        path = root / "policy.json"
        write(
            path,
            (json.dumps(policy, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        )
        return path, blender

    def test_import_is_checksum_verified_no_clobber_and_deterministic(self) -> None:
        payload = b"fixture corresponding source\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy, _blender = self._policy(root, payload)
            source = root / "source.tar.xz"
            write(source, payload)
            first = root / "first"
            second = root / "second"

            first_path = fetcher.fetch(policy, first, source)
            second_path = fetcher.fetch(policy, second, source)
            self.assertEqual(first_path.read_bytes(), payload)
            self.assertEqual(second_path.read_bytes(), payload)

            with self.assertRaises(fetcher.SourceFailure) as existing:
                fetcher.fetch(policy, first, source)
            self.assertEqual(existing.exception.code, "output_exists")
            self.assertEqual(first_path.read_bytes(), payload)

            write(source, b"tampered")
            with self.assertRaises(fetcher.SourceFailure) as mismatch:
                fetcher.fetch(policy, root / "third", source)
            self.assertEqual(mismatch.exception.code, "archive_size_mismatch")
            self.assertFalse((root / "third").exists())

    def test_fetch_rejects_redirects_proxies_and_response_identity(self) -> None:
        payload = b"fixture corresponding source\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy_path, blender = self._policy(root, payload)
            loaded = fetcher.load_policy(policy_path)
            self.assertEqual(loaded, blender)

            response = _Response(payload, str(blender["source_url"]))
            opener = mock.Mock()
            opener.open.return_value = response
            with mock.patch.object(fetcher.urllib.request, "build_opener", return_value=opener) as built:
                stream = fetcher._network_stream(
                    str(blender["source_url"]), int(blender["bytes"])
                )
                self.assertIs(stream, response)
            handlers = built.call_args.args
            self.assertTrue(any(isinstance(item, fetcher.RejectRedirects) for item in handlers))
            proxy = next(item for item in handlers if isinstance(item, fetcher.urllib.request.ProxyHandler))
            self.assertEqual(proxy.proxies, {})

            redirected = _Response(payload, "https://example.invalid/redirect")
            opener.open.return_value = redirected
            with mock.patch.object(fetcher.urllib.request, "build_opener", return_value=opener):
                with self.assertRaises(fetcher.SourceFailure) as identity:
                    fetcher._network_stream(
                        str(blender["source_url"]), int(blender["bytes"])
                    )
            self.assertEqual(identity.exception.code, "download_identity_invalid")
            self.assertTrue(redirected.closed)

            broken = _Response(payload, str(blender["source_url"]))
            broken.read = mock.Mock(side_effect=http.client.IncompleteRead(b"partial"))
            with mock.patch.object(fetcher, "_network_stream", return_value=broken):
                with self.assertRaises(fetcher.SourceFailure) as transfer:
                    fetcher.fetch(policy_path, root / "broken", None)
            self.assertEqual(transfer.exception.code, "archive_io_failed")
            self.assertTrue(broken.closed)
            self.assertFalse((root / "broken").exists())

    def test_tracked_policy_matches_verified_official_archive_identity(self) -> None:
        policy = fetcher.load_policy(ROOT / "release" / "corresponding-source-policy.json")
        self.assertEqual(policy["archive"], "blender-4.5.12.tar.xz")
        self.assertEqual(policy["bytes"], 85105056)
        self.assertEqual(
            policy["sha256"],
            "9cb86825c95e4f0a33bfd41eb574426f2f69aa6c310497e289fdb54cc6482f1b",
        )
        self.assertEqual(policy["official_md5"], "5696670e8b7a8d8ffbd33824a140c1c3")


if __name__ == "__main__":
    unittest.main()
