#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Opt-in GPU receiver with a CPU fallback latched until the next boot.

Only the GPU child receives the private GL library. A missing/changing HDMI
signal is retried by systemd, rather than treated as a broken GPU build.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from hdmi_mode import query_mode


def log(**fields):
    print(json.dumps({'gpu_supervisor': fields}), flush=True)


def validate_bundle(bundle, version):
    if tuple(version[:3]) != (1, 26, 2):
        raise RuntimeError('Private GL build requires GStreamer 1.26.2')
    verified = set()
    for line in (bundle / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        path = (bundle / name).resolve()
        if not path.is_relative_to(bundle.resolve()):
            raise RuntimeError('Bundle manifest path outside bundle')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Bundle checksum mismatch: ' + name)
        verified.add(name)
    required = {'lib/libgstgl-1.0.so.0', 'runtime/receiver.py',
                'runtime/hdmi_mode.py', 'runtime/source_events.py', 'runtime/push_meter.py'}
    if not required <= verified:
        raise RuntimeError('Bundle manifest does not cover required runtime files')


def gpu_arguments(cpu_args):
    # Keep the original CPU argument list intact for the fallback.
    result = []
    skip = False
    for arg in cpu_args:
        if skip:
            skip = False
        elif arg in ('--io-mode', '--converter'):
            skip = True
        elif arg.startswith(('--io-mode=', '--converter=')):
            continue
        elif arg not in ('--cached-output', '--gl-dmabuf'):
            result.append(arg)
    return result + ['--io-mode', 'dmabuf', '--converter', 'gl', '--gl-dmabuf']


class Supervisor:
    def __init__(self, bundle, cpu_runtime, cpu_args, state_dir):
        self.bundle, self.cpu_runtime = bundle, cpu_runtime
        self.cpu_args, self.state_dir = cpu_args, state_dir
        self.child = None
        self.stopping = False
        self.base_env = dict(os.environ)
        # Neither instrumentation nor private libraries may enter the CPU path.
        for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'GST_GL_WINDOW', 'GST_GL_PLATFORM'):
            self.base_env.pop(name, None)

    def stop(self, signum, frame):
        self.stopping = True
        if self.child is not None and self.child.poll() is None:
            try:
                os.killpg(self.child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def cpu(self, reason, latch=True):
        if self.stopping:
            return 0
        if latch:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.state_dir / 'gpu-fallback.json.tmp'
            tmp.write_text(json.dumps({'reason': reason, 'time': time.time()}, indent=2) + '\n')
            tmp.replace(self.state_dir / 'gpu-fallback.json')
        log(path='cpu', reason=reason)
        os.execve(sys.executable, [sys.executable, str(self.cpu_runtime), *self.cpu_args], self.base_env)

    def run(self):
        marker = self.state_dir / 'gpu-fallback.json'
        if marker.exists():
            return self.cpu('GPU fallback already selected for this boot', latch=False)
        try:
            import gi
            gi.require_version('Gst', '1.0')
            from gi.repository import Gst
            validate_bundle(self.bundle, Gst.version())
        except Exception as exc:
            return self.cpu('GPU preflight failed: ' + str(exc))
        if self.stopping:
            return 0
        env = {**self.base_env, 'LD_LIBRARY_PATH': str(self.bundle / 'lib'),
               'GST_GL_WINDOW': 'gbm', 'GST_GL_PLATFORM': 'egl'}
        cmd = [sys.executable, str(self.bundle / 'runtime/receiver.py'), *gpu_arguments(self.cpu_args)]
        log(path='gpu', bundle=str(self.bundle))
        detected, summary, device = None, {}, None
        try:
            self.child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          text=True, bufsize=1, env=env, start_new_session=True)
            if self.stopping:
                self.stop(None, None)
            for line in self.child.stdout:
                print(line, end='', flush=True)
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if 'hdmi_mode' in obj:
                    detected = obj['hdmi_mode']
                if obj.get('device'):
                    device = obj['device']
                if 'completion' in obj:
                    summary = obj
            rc = self.child.wait()
        except OSError as exc:
            if self.child is not None and self.child.poll() is None:
                os.killpg(self.child.pid, signal.SIGKILL)
                self.child.wait()
            return self.cpu('Could not launch GPU receiver: ' + str(exc))
        if self.stopping or rc == 0:
            return 0
        if rc == 75 or summary.get('completion') == 'mode-change':
            log(retry='HDMI source change')
            return 75
        if rc > 0 and '--auto-mode' in self.cpu_args:
            if device is None:
                devices = [str(Path('/dev') / p.name) for p in Path('/sys/class/video4linux').glob('video*')
                           if 'gc555' in (p / 'name').read_text().lower()]
                device = devices[0] if len(devices) == 1 else None
            if device is None:
                log(retry='Capture device unavailable')
                return 75
            try:
                current = vars(query_mode(device))
            except (RuntimeError, subprocess.TimeoutExpired):
                log(retry='HDMI signal unavailable')
                return 75
            except (ValueError, OSError):
                current = None
            if current and detected is not None and detected != current:
                log(retry='HDMI timing changed during capture', previous=detected, current=current)
                return 75
        return self.cpu({'gpu_exit': rc, 'errors': summary.get('errors', [])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--cpu-runtime', type=Path, default=Path(__file__).with_name('receiver.py'))
    parser.add_argument('--state-dir', type=Path, default=Path('/run/imac-receiver'))
    parser.add_argument('receiver_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cpu_args = args.receiver_args
    if cpu_args and cpu_args[0] == '--':
        cpu_args = cpu_args[1:]
    supervisor = Supervisor(args.bundle, args.cpu_runtime, cpu_args, args.state_dir)
    signal.signal(signal.SIGTERM, supervisor.stop)
    signal.signal(signal.SIGINT, supervisor.stop)
    return supervisor.run()


if __name__ == '__main__':
    sys.exit(main())
