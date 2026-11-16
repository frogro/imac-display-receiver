# SPDX-License-Identifier: GPL-2.0-only
"""Strict, shared state format; no commands or arbitrary ALSA paths from HTTP."""
import json
import math
import os
from pathlib import Path

STATE_DIR = Path(os.environ.get('EQ_STATE_DIR', '/var/lib/imac-equalizer'))
STATE_FILE = STATE_DIR / 'settings.json'
STATUS_FILE = Path(os.environ.get('EQ_STATUS_FILE', '/run/imac-audio-status/status.json'))
DEFAULT = dict(volume=40, mute=False, bass=0, mid=0, treble=0, source='gc555')
PRESETS = {'Neutral': dict(bass=0, mid=0, treble=0),
           'Sprache': dict(bass=-2, mid=2, treble=-1),
           'Warm': dict(bass=2, mid=0, treble=-2)}
SOURCES = {'gc555': 'hw:BOLT,0', 'elgato': 'hw:X,0'}


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT):
        raise ValueError('Unvollständige oder unbekannte Einstellungen')
    result = dict(value)
    for key, lo, hi in [('volume', 0, 100), ('bass', -6, 6), ('mid', -6, 6), ('treble', -6, 6)]:
        n = value[key]
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not lo <= n <= hi:
            raise ValueError(f'{key}: erlaubt sind {lo} bis {hi}')
    if type(value['mute']) is not bool or value['source'] not in SOURCES:
        raise ValueError('Ungültige Stummschaltung oder Tonquelle')
    return result


def read_settings(path=STATE_FILE):
    return validate(json.loads(path.read_text()))


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    with tmp.open('w') as f:
        json.dump(value, f, ensure_ascii=False, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def gain(settings):
    # Preserve the previous 0.25 amplitude ceiling. Reserve conservative
    # headroom for the sum of all positive EQ gains, not only the largest.
    boost = sum(max(0, settings[k]) for k in ('bass', 'mid', 'treble'))
    return 0.0 if settings['mute'] else .25 * settings['volume'] / 100 * 10 ** (-boost / 20)
