import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from pack_verifier_evidence import pack


class VerifierEvidenceArchiveTests(unittest.TestCase):
    def test_complete_verifier_files_and_selected_ui_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); evidence = root / 'modeling-verifier-validation'
            (evidence / 'nested').mkdir(parents=True)
            (evidence / 'summary.json').write_text('{"status":"passed"}')
            (evidence / 'nested/.runtime').write_text('bound runtime')
            ui = root / 'modeling-review-ui'; ui.mkdir()
            (ui / 'verifier-v2-desktop.png').write_bytes(b'test fixture, not an image')
            (ui / 'unrelated.png').write_bytes(b'not selected')
            output = root / 'proof.zip'
            result = pack(root, output)
            self.assertEqual(result['files'], 3)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read('modeling-verifier-validation/nested/.runtime'), b'bound runtime')
                self.assertEqual(json.loads(archive.read('modeling-verifier-validation/summary.json')), {'status':'passed'})
                self.assertNotIn('modeling-review-ui/unrelated.png', archive.namelist())
            with self.assertRaises(ValueError): pack(root, output)

    def test_oversized_archive_never_publishes_final_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); evidence = root / 'modeling-verifier-validation'; evidence.mkdir()
            (evidence / 'data').write_bytes(b'bounded evidence')
            with self.assertRaisesRegex(ValueError, 'archive limit'):
                pack(root, root / 'proof.zip', max_archive=1)
            self.assertFalse((root / 'proof.zip').exists())
            self.assertTrue((evidence / 'data').exists())

    def test_links_are_rejected_and_original_evidence_stays_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); evidence = root / 'modeling-verifier-validation'; evidence.mkdir()
            target = root / 'outside'; target.write_bytes(b'unchanged')
            (evidence / 'link').symlink_to(target)
            with self.assertRaisesRegex(ValueError, 'Linked'):
                pack(root, root / 'proof.zip')
            self.assertEqual(target.read_bytes(), b'unchanged')

    def test_empty_directories_count_toward_entry_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); evidence = root / 'modeling-verifier-validation'; evidence.mkdir()
            for name in ('one', 'two', 'three'):
                (evidence / name).mkdir()
            with patch('pack_verifier_evidence.MAX_FILES', 2):
                with self.assertRaisesRegex(ValueError, 'entry limit'):
                    pack(root, root / 'proof.zip')
            self.assertFalse((root / 'proof.zip').exists())


if __name__ == '__main__': unittest.main()
