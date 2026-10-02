"""Test the observer writer without importing Blender or running author code."""
import ast
import json
from pathlib import Path
import tempfile
import unittest

from experimental_modeling.contracts import MAX_JSON, read_json

OBSERVER = Path(__file__).resolve().parents[2] / 'experimental_modeling/inspect_scene.py'


def writer():
    tree = ast.parse(OBSERVER.read_text())
    selected = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'write_json')
    namespace = {'json': json, 'Path': Path}
    exec(compile(ast.Module(body=[selected], type_ignores=[]), str(OBSERVER), 'exec'), namespace)
    return namespace['write_json']


class ObservationSerializationTests(unittest.TestCase):
    def test_default_writer_keeps_version_one_bytes(self):
        value = {'schema_version': 1, 'parts': {'body': {'world_vertices': [[.125, .25, .5]], 'label': 'snow 雪'}}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observation.json'
            writer()(path, value)
            self.assertEqual(path.read_text(), json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')

    def test_compact_v2_observation_retains_all_evidence_within_existing_limit(self):
        # Similar nested numeric-array load to the real lamp failure. This tests
        # serialization only; it is not a valid geometry or Blender fixture.
        value = {'schema_version': 2, 'parts': {'body': {
            'world_vertices': [[.125, .25, .5]] * 20000,
            'face_world_corner_normals': [[[0., 0., 1.]] * 3] * 20000}}}
        with tempfile.TemporaryDirectory() as tmp:
            pretty, compact = Path(tmp) / 'pretty.json', Path(tmp) / 'compact.json'
            write = writer()
            write(pretty, value)
            self.assertGreater(pretty.stat().st_size, MAX_JSON)
            with self.assertRaisesRegex(ValueError, 'bounded'):
                read_json(pretty)
            write(compact, value, compact=True)
            self.assertLessEqual(compact.stat().st_size, MAX_JSON)
            self.assertEqual(read_json(compact), value)
            self.assertEqual(json.loads(pretty.read_text()), json.loads(compact.read_text()))

    def test_existing_limit_and_nonfinite_rejection_are_not_weakened(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'large.json'
            write = writer()
            write(path, {'payload': 'x' * MAX_JSON}, compact=True)
            with self.assertRaisesRegex(ValueError, 'bounded'):
                read_json(path)
            with self.assertRaises(ValueError):
                write(path, {'value': float('nan')}, compact=True)

    def test_only_v2_observation_writes_select_compact_encoding(self):
        tree = ast.parse(OBSERVER.read_text())
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == 'write_json'
                 and node.args and ast.unparse(node.args[0]) == "output / 'observation.json'"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            compact = next(keyword.value for keyword in call.keywords if keyword.arg == 'compact')
            self.assertEqual(ast.unparse(compact), 'args.observation_version == 2')


if __name__ == '__main__':
    unittest.main()
