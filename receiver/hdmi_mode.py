#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read GC555 measured DV timing and select a nominal driver capture mode."""
import os
import re
import subprocess
from dataclasses import dataclass

@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    fps: int

    @property
    def capture_format(self):
        return 'NV12' if (self.width, self.height, self.fps) == (1920, 1080, 60) else 'YUY2'


def parse_timings(text):
    def value(pattern):
        match = re.search(pattern, text)
        if not match:
            raise ValueError('No complete HDMI timing: ' + text.strip()[:200])
        return match.group(1)
    width = int(value(r'Active width:\s*(\d+)'))
    height = int(value(r'Active height:\s*(\d+)'))
    if value(r'Frame format:\s*(\w+)') != 'progressive':
        raise ValueError('Interlaced HDMI is not supported by this receiver')
    measured = float(value(r'\(([0-9.]+) frames per second\)'))
    rates = (24, 25, 30, 50, 60, 75, 100, 120, 144, 240)
    nominal = min(rates, key=lambda r: abs(r-measured))
    # GC555 clock measurement is approximate (observed 59.62/60 and 29.54/30 after link initialization).
    # Caps use the driver's enumerated nominal rates, not invented measured caps.
    if measured <= 0 or abs(nominal-measured) / nominal > 0.02:
        raise ValueError(f'Unrecognized HDMI rate {measured}')
    if not (640 <= width <= 3840 and 480 <= height <= 2160):
        raise ValueError(f'Unsupported HDMI dimensions {width}x{height}')
    return Mode(width, height, nominal)


def query_mode(device):
    result = subprocess.run(['v4l2-ctl', '-d', device, '--query-dv-timings'],
                            capture_output=True, text=True, timeout=2,
                            env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise RuntimeError('HDMI signal unavailable: ' + (result.stderr + result.stdout).strip()[:200])
    return parse_timings(result.stdout)


def prepare_capture(device, mode):
    # Release the previous mode's NV12 restriction before GStreamer sets DV timings.
    fourcc = 'NV12' if mode.capture_format == 'NV12' else 'YUYV'
    result = subprocess.run(['v4l2-ctl', '-d', device,
                             f'--set-fmt-video=width={mode.width},height={mode.height},pixelformat={fourcc}'],
                            capture_output=True, text=True, timeout=2)
    if result.returncode:
        raise RuntimeError('Cannot prepare capture format: ' + result.stderr.strip())
