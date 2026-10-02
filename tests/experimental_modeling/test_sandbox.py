"""Static fail-closed tests; opt-in Docker smoke is not a security audit."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from experimental_modeling.sandbox import DockerSandbox, Limits, SandboxError, extract_output

IMAGE = 'sha256:' + 'a' * 64


class SandboxTests(unittest.TestCase):
    def backend(self):
        with patch('experimental_modeling.sandbox.shutil.which', return_value='/usr/bin/docker'):
            return DockerSandbox(IMAGE)

    def test_requires_immutable_image(self):
        for image in ('builder:latest', 'sha256:abcd', 'repo@sha256:' + 'a' * 64):
            with self.assertRaises(ValueError): DockerSandbox(image)

    def test_absent_docker_fails_closed(self):
        with patch('experimental_modeling.sandbox.shutil.which', return_value=None):
            with self.assertRaisesRegex(SandboxError, 'No native fallback'):
                DockerSandbox(IMAGE).verify_runtime()

    def test_command_security_and_no_host_output(self):
        sandbox = self.backend()
        cmd = sandbox.create_command('test-container', {'source': Path('/source'), 'params': Path('/params.json')}, 'test-volume')
        for flag in ('--network=none', '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges=true',
                     '--user=65532:65532', '--pids-limit=128', '--cpus=2', '--log-driver=none', '--pull=never', '--ipc=none'):
            self.assertIn(flag, cmd)
        mounts = [cmd[i + 1] for i, flag in enumerate(cmd) if flag == '--mount']
        self.assertEqual(len(mounts), 3)
        self.assertTrue(all(',readonly,bind-recursive=disabled' in mount for mount in mounts if mount.startswith('type=bind')))
        self.assertNotIn('/var/run/docker.sock', ' '.join(mounts))
        self.assertIn('type=volume,source=test-volume,target=/output,volume-nocopy', mounts)
        exported = sandbox.create_command('export', {}, 'test-volume', exporter=True)
        self.assertIn('type=volume,source=test-volume,target=/output,volume-nocopy,readonly', exported)
        self.assertIn('--entrypoint=/bin/tar', exported)
        self.assertEqual(cmd[-2:], [IMAGE, 'infinity'])
        self.assertNotIn('DOCKER_HOST', sandbox.env)
        self.assertNotIn('AWS_ACCESS_KEY_ID', sandbox.env)

    def test_daemon_capabilities_and_image_verified(self):
        info = {'OSType': 'linux', 'SecurityOptions': ['name=seccomp,profile=builtin'],
                'MemoryLimit': True, 'PidsLimit': True, 'CpuCfsQuota': True}
        image = [{'Id': IMAGE, 'Os': 'linux', 'Config': {}}]
        sandbox = self.backend()
        with patch.object(sandbox, '_control', side_effect=[json.dumps(info), json.dumps(image)]):
            self.assertEqual(sandbox.verify_runtime()['image_id'], IMAGE)
        for key, value in [('OSType', 'windows'), ('SecurityOptions', []), ('MemoryLimit', False), ('PidsLimit', False), ('CpuCfsQuota', False)]:
            with self.subTest(key=key), patch.object(sandbox, '_control', return_value=json.dumps(info | {key: value})):
                with self.assertRaises(SandboxError): sandbox.verify_runtime()
        for candidate in ([{'Id': 'wrong', 'Os': 'linux'}], [{'Id': IMAGE, 'Os': 'linux', 'Config': {'Volumes': {'/work': {}}}}], [{'Id': IMAGE, 'Os': 'linux', 'Config': {'Env': ['AWS_ACCESS_KEY_ID=x']}}]):
            with patch.object(sandbox, '_control', side_effect=[json.dumps(info), json.dumps(candidate)]):
                with self.assertRaises(SandboxError): sandbox.verify_runtime()

    def test_owned_cleanup_uses_verified_id(self):
        sandbox = self.backend()
        item = {"Id": "b" * 64, "Config": {"Labels": {"experimental.modeling.owner": "my-volume"}}}
        with patch.object(sandbox, '_control', side_effect=[json.dumps([item]), ""]) as control:
            sandbox._remove_owned('container', 'name', 'my-volume')
            self.assertEqual(control.call_args.args, ('container', 'rm', '--force', 'b' * 64))
        with patch.object(sandbox, '_control', return_value=json.dumps([item])) as control:
            with self.assertRaisesRegex(SandboxError, 'ownership'):
                sandbox._remove_owned('container', 'name', 'other-volume')
            self.assertEqual(control.call_count, 1)

    def test_allowed_image_environment_overridden(self):
        sandbox = self.backend()
        command = sandbox.create_command('name', {}, 'volume')
        for key, value in sandbox.container_env.items():
            self.assertIn('--env=' + key + '=' + value, command)
        self.assertIn('--label', command)
        self.assertIn('experimental.modeling.owner=volume', command)

    def test_roles_and_symlinks_rejected_before_execution(self):
        sandbox = self.backend()
        with self.assertRaises(ValueError): sandbox.run('author', [], {'policy': Path('/policy')}, Path('/out'), Path('/log'))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'source').mkdir(); (root / 'params').write_text('{}')
            (root / 'source' / 'escape').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): sandbox.run('author', [], {'source': root / 'source', 'params': root / 'params'}, root / 'out', root / 'log')

    def archive(self, root, members):
        archive = root / 'out.tar'
        with tarfile.open(archive, 'w') as stream:
            for name, kind, payload in members:
                entry = tarfile.TarInfo(name); entry.type = kind
                if kind == tarfile.REGTYPE:
                    entry.size = len(payload); stream.addfile(entry, io.BytesIO(payload))
                else:
                    entry.linkname = payload.decode(); stream.addfile(entry)
        return archive

    def test_safe_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); output = root / 'out'; output.mkdir()
            extract_output(self.archive(root, [('./scene.blend', tarfile.REGTYPE, b'blend')]), output, Limits())
            self.assertEqual((output / 'scene.blend').read_bytes(), b'blend')

    def test_unsafe_archives(self):
        for members in ([('../escape', tarfile.REGTYPE, b'x')], [('/escape', tarfile.REGTYPE, b'x')],
                        [('link', tarfile.SYMTYPE, b'/etc/passwd')], [('link', tarfile.LNKTYPE, b'scene.blend')],
                        [('fifo', tarfile.FIFOTYPE, b'')], [('file', tarfile.REGTYPE, b'x'), ('file', tarfile.REGTYPE, b'y')]):
            with self.subTest(members=members), tempfile.TemporaryDirectory() as td:
                root = Path(td); output = root / 'out'; output.mkdir()
                with self.assertRaises(SandboxError): extract_output(self.archive(root, members), output, Limits())

    def test_archive_budgets(self):
        for limits in (Limits(output_bytes=1), Limits(max_files=1)):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td); output = root / 'out'; output.mkdir()
                archive = self.archive(root, [('one', tarfile.REGTYPE, b'xx'), ('two', tarfile.REGTYPE, b'xx')])
                with self.assertRaises(SandboxError): extract_output(archive, output, limits)

    def test_bounded_stream(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'log'
            with self.assertRaisesRegex(SandboxError, 'stream byte limit'):
                self.backend()._stream(['/usr/bin/python3', '-c', 'print("x"*10000)'], log, 100, 5)
            self.assertEqual(log.stat().st_size, 100)


    def test_ci_archive_includes_hashed_hidden_runtime_files(self):
        root=Path(__file__).resolve().parents[2]
        workflow=json.loads((root/'.github/workflows/experimental-modeling-sandbox.yml').read_text())
        archive=next(s for s in workflow['jobs']['docker-boundary-and-benchmark']['steps'] if s.get('name')=='Retain bounded experimental evidence')
        self.assertTrue(archive['with']['include-hidden-files'])
        self.assertEqual(set(archive['with']['path'].splitlines()), {'${{ runner.temp }}/modeling-benchmark','${{ runner.temp }}/modeling-desk-benchmark','${{ runner.temp }}/modeling-review-ui','${{ runner.temp }}/modeling-water-relations','${{ runner.temp }}/modeling-review-project','${{ runner.temp }}/modeling-request-bridge','${{ runner.temp }}/modeling-verifier-validation'})
        lamp=next(s for s in workflow['jobs']['docker-boundary-and-benchmark']['steps'] if s.get('name')=='Retain external author lamp evidence')
        self.assertTrue(lamp['with']['include-hidden-files'])
        self.assertEqual(lamp['with']['path'], '${{ runner.temp }}/modeling-external-lamp')


@unittest.skipUnless(os.environ.get('MODELING_SANDBOX_IMAGE'), 'NOT VERIFIED: opt-in Linux Docker runtime required')
class DockerRuntimeSmoke(unittest.TestCase):
    def test_container_boundary_and_export(self):
        sandbox = DockerSandbox(os.environ['MODELING_SANDBOX_IMAGE'], Limits(timeout_seconds=45))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); source = root / 'source'; source.mkdir(mode=0o755)
            params = root / 'params.json'; params.write_text('{}'); params.chmod(0o644)
            (source / 'builder.py').write_text('''import json, os, socket
from pathlib import Path
assert os.getuid() == 65532
assert "AWS_ACCESS_KEY_ID" not in os.environ
assert os.environ["HOME"] == "/output"
for path in ("/inputs/source/builder.py", "/inputs/params", "/root/escape", "/etc/escape"):
    try:
        with open(path, "a") as stream: stream.write("bad")
    except OSError: pass
    else: raise AssertionError("write escaped: " + path)
assert not Path("/var/run/docker.sock").exists()
assert not Path("/inputs/policy").exists()
assert not Path("/inputs/inspector").exists()
s = socket.socket(); s.settimeout(1)
try: s.connect(("1.1.1.1", 443))
except OSError: pass
else: raise AssertionError("network escaped")
Path("/output/probe.json").write_text(json.dumps({"ok": True}))
''')
            (source / 'builder.py').chmod(0o644)
            output = root / 'output'; output.mkdir()
            result = sandbox.run('author', ['--python', '/inputs/source/builder.py'],
                                 {'source': source, 'params': params}, output, root / 'job.log')
            self.assertEqual(result['image_id'], os.environ['MODELING_SANDBOX_IMAGE'])
            self.assertEqual(json.loads((output / 'probe.json').read_text()), {'ok': True})


    def test_limits_and_descendant_cleanup(self):
        image = os.environ['MODELING_SANDBOX_IMAGE']
        cases = [
            ('timeout', 'import time, subprocess; subprocess.Popen(["/bin/sleep","60"]); time.sleep(30)', Limits(timeout_seconds=3), True),
            ('output-limit', 'from pathlib import Path; Path("/output/large").write_bytes(b"x"*65536)', Limits(output_bytes=4096, timeout_seconds=30), True),
            ('diagnostic', 'from pathlib import Path; Path("/output/diagnostic.txt").write_text("retained"); raise RuntimeError("deliberate")', Limits(timeout_seconds=30), True),
            ('descendant', 'import subprocess; from pathlib import Path; subprocess.Popen(["/bin/sleep","60"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); Path("/output/ok").write_text("ok")', Limits(timeout_seconds=30), False),
        ]
        for name, code, limits, rejected in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                backend = DockerSandbox(image, limits)
                before_containers = backend._control('container','ls','--all','--filter','label=experimental.modeling.owner','--format','{{.Names}}')
                before_volumes = backend._control('volume','ls','--filter','label=experimental.modeling.owner','--format','{{.Name}}')
                root=Path(td); source=root/'source'; source.mkdir(mode=0o755)
                (source/'builder.py').write_text(code); (source/'builder.py').chmod(0o644)
                params=root/'params.json'; params.write_text('{}'); params.chmod(0o644)
                output=root/'output'; output.mkdir()
                def execute():
                    return backend.run('author',['--python','/inputs/source/builder.py'],{'source':source,'params':params},output,root/'job.log')
                if rejected:
                    message = 'wall-time limit' if name == 'timeout' else 'failed with exit code'
                    with self.assertRaisesRegex(SandboxError, message): execute()
                    if name == 'output-limit':
                        self.assertLessEqual(sum(p.stat().st_size for p in output.rglob('*') if p.is_file()), limits.output_bytes)
                        self.assertRegex((root/'job.log').read_text(), 'File too large|No space left')
                    if name == 'diagnostic': self.assertEqual((output/'diagnostic.txt').read_text(),'retained')
                else:
                    self.assertEqual(execute()['exit_code'],0)
                    self.assertEqual((output/'ok').read_text(),'ok')
                self.assertEqual(backend._control('container','ls','--all','--filter','label=experimental.modeling.owner','--format','{{.Names}}'), before_containers)
                self.assertEqual(backend._control('volume','ls','--filter','label=experimental.modeling.owner','--format','{{.Name}}'), before_volumes)


if __name__ == '__main__': unittest.main()
