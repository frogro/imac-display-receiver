import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'receiver'))
import gpu_supervisor as g
from hdmi_mode import Mode


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = g.Supervisor(self.root, self.root/'cpu.py',
                              ['--auto-mode', '--io-mode', 'mmap', '--cached-output'], self.root/'state')

    def run_child(self, rc, mode=Mode(3840, 2160, 30), detected=True, completion='error'):
        rows = [{'device': '/dev/video2'}, {'completion': completion, 'errors': ['failure']}]
        if detected:
            rows.insert(0, {'hdmi_mode': vars(Mode(3840, 2160, 30))})
        child = Mock(stdout=io.StringIO(''.join(json.dumps(r)+'\n' for r in rows)))
        child.wait.return_value = rc
        with patch.object(g, 'validate_bundle'), patch.object(g.subprocess, 'Popen', return_value=child), \
             patch.object(g, 'query_mode', side_effect=mode if isinstance(mode, Exception) else None,
                          return_value=mode), patch.object(self.s, 'cpu', return_value=123) as cpu:
            result = self.s.run()
        return result, cpu

    def test_stable_signal_gpu_failure_falls_back(self):
        result, cpu = self.run_child(1)
        self.assertEqual(result, 123)
        cpu.assert_called_once()

    def test_failure_before_mode_detection_falls_back(self):
        result, cpu = self.run_child(1, detected=False)
        self.assertEqual(result, 123)
        cpu.assert_called_once()

    def test_missing_hdmi_retries_without_fallback(self):
        result, cpu = self.run_child(1, mode=RuntimeError('No signal'))
        self.assertEqual(result, 75)
        cpu.assert_not_called()

    def test_changed_hdmi_retries_without_fallback(self):
        result, cpu = self.run_child(1, mode=Mode(1920, 1080, 60))
        self.assertEqual(result, 75)
        cpu.assert_not_called()

    def test_mode_change_exit_retries(self):
        result, cpu = self.run_child(75, completion='mode-change')
        self.assertEqual(result, 75)
        cpu.assert_not_called()

    def test_gpu_crash_falls_back(self):
        result, cpu = self.run_child(-11)
        self.assertEqual(result, 123)
        cpu.assert_called_once()

    def test_clean_exit_does_not_start_cpu(self):
        result, cpu = self.run_child(0, completion='signal')
        self.assertEqual(result, 0)
        cpu.assert_not_called()

    def test_stopping_does_not_start_cpu(self):
        self.s.stopping = True
        with patch.object(g.os, 'execve') as execute:
            self.assertEqual(self.s.cpu('stop'), 0)
            execute.assert_not_called()

    def test_fallback_latches_and_cleans_environment(self):
        with patch.object(g.os, 'execve') as execute:
            self.s.cpu('broken GPU')
            self.assertTrue((self.s.state_dir/'gpu-fallback.json').exists())
            env = execute.call_args.args[2]
            self.assertNotIn('LD_LIBRARY_PATH', env)
            self.assertNotIn('GST_GL_PLATFORM', env)
        with patch.object(self.s, 'cpu', return_value=123) as cpu:
            self.assertEqual(self.s.run(), 123)
            self.assertFalse(cpu.call_args.kwargs['latch'])

    def test_preflight_failure_falls_back(self):
        with patch.object(g, 'validate_bundle', side_effect=RuntimeError('mismatch')), \
             patch.object(self.s, 'cpu', return_value=123) as cpu:
            self.assertEqual(self.s.run(), 123)
            self.assertIn('mismatch', cpu.call_args.args[0])

    def test_argument_conversion_preserves_cpu_options(self):
        original = list(self.s.cpu_args)
        args = g.gpu_arguments(original)
        self.assertNotIn('--cached-output', args)
        self.assertNotIn('mmap', args)
        self.assertIn('--gl-dmabuf', args)
        self.assertEqual(original, self.s.cpu_args)

    def test_manifest_rejects_modified_library(self):
        required = ['lib/libgstgl-1.0.so.0', 'runtime/receiver.py', 'runtime/hdmi_mode.py',
                    'runtime/source_events.py', 'runtime/push_meter.py']
        lines = []
        for name in required:
            target = self.root/name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(b'original')
            lines.append(hashlib.sha256(b'original').hexdigest()+'  '+name)
        (self.root/'SHA256SUMS').write_text('\n'.join(lines))
        g.validate_bundle(self.root, (1,26,2,0))
        (self.root/required[0]).write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            g.validate_bundle(self.root, (1,26,2,0))

    def test_real_exec_fallback_keeps_cpu_arguments(self):
        cpu = self.root/'cpu.py'
        cpu.write_text('import sys,os,json\nprint(json.dumps({"cpu_args":sys.argv[1:],"gl":os.getenv("GST_GL_PLATFORM")}))\n')
        result = subprocess.run([sys.executable, g.__file__, '--bundle', str(self.root/'missing'),
                                 '--cpu-runtime', str(cpu), '--state-dir', str(self.root/'state'),
                                 '--', '--io-mode', 'mmap', '--cached-output'],
                                capture_output=True, text=True, timeout=5,
                                env={**g.os.environ, 'GST_GL_PLATFORM':'egl'})
        self.assertEqual(result.returncode, 0, result.stderr)
        last = json.loads(result.stdout.splitlines()[-1])
        self.assertEqual(last, {'cpu_args':['--io-mode','mmap','--cached-output'], 'gl':None})
        self.assertTrue((self.root/'state/gpu-fallback.json').exists())

if __name__ == '__main__':
    unittest.main()
