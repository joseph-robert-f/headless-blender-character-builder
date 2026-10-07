# SPDX-License-Identifier: GPL-3.0-or-later
"""Actual accepted-chain integrity during read-only print assessment."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from experimental_modeling.controller import digest, write_json

DIRECTORY=Path(__file__).resolve().parent
sys.path.insert(0,str(DIRECTORY))
spec=importlib.util.spec_from_file_location('cat_print_export_runner',DIRECTORY/'run_anime_cat_print_export.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)


class PrintExportHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        parent=parent_hash=None
        for revision in ('r0','r1','r2'):
            current=self.root/'accepted'/revision;current.mkdir(parents=True)
            payload=current/'payload.txt';payload.write_text(revision+' original\n')
            manifest={'status':'accepted','revision':revision,'parent':parent,
                      'parent_result_hash':parent_hash,'artifacts':{'payload.txt':digest(payload)}}
            write_json(current/'result.json',manifest)
            parent=revision;parent_hash=digest(current/'result.json')
        write_json(self.root/'last_good.json',{'revision':parent,'result_hash':parent_hash})

    def test_valid_chain_verified_without_changing_any_file(self):
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        measured=runner.history_fingerprints(self.root)
        self.assertEqual(len(measured),7)
        self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_corrupted_old_revision_rejected_despite_valid_current_manifest(self):
        for revision in ('r0','r1'):
            path=self.root/'accepted'/revision/'payload.txt'
            original=path.read_bytes();path.write_text('corrupted protected history\n')
            with self.subTest(revision=revision),self.assertRaises(ValueError):runner.history_fingerprints(self.root)
            path.write_bytes(original)

    def test_tampered_parent_link_rejected_even_after_current_pointer_rehashed(self):
        path=self.root/'accepted/r2/result.json'
        manifest=json.loads(path.read_text());manifest['parent_result_hash']='a'*64
        path.write_text(json.dumps(manifest))
        (self.root/'last_good.json').write_text(json.dumps({'revision':'r2','result_hash':digest(path)}))
        with self.assertRaises(ValueError):runner.history_fingerprints(self.root)

    def test_wrong_parent_order_rejected_even_when_manifest_is_intact(self):
        path=self.root/'accepted/r2/result.json'
        manifest=json.loads(path.read_text());manifest['parent']='r0'
        path.write_text(json.dumps(manifest))
        (self.root/'last_good.json').write_text(json.dumps({'revision':'r2','result_hash':digest(path)}))
        with self.assertRaises(ValueError):runner.history_fingerprints(self.root)


if __name__=='__main__':unittest.main()
