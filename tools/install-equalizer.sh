#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Run on an existing receiver after copying the updated receiver files.
set -euo pipefail
[[ $EUID -eq 0 ]]
P=/opt/imac-receiver
[[ -f $P/receiver/equalizer_web.py && -f /etc/imac-audio.conf ]]
gst-inspect-1.0 equalizer-3bands >/dev/null
getent passwd imac-equalizer >/dev/null || useradd --system --no-create-home --shell /usr/sbin/nologin imac-equalizer
install -d -m 750 -o imac-equalizer -g imac-equalizer /var/lib/imac-equalizer
# Preserve the configured amplitude on the first installation.
if [[ ! -f /var/lib/imac-equalizer/settings.json ]]; then
    PYTHONPATH=$P/receiver python3 - <<'PY'
import re
from pathlib import Path
from equalizer_state import DEFAULT, validate, atomic_json, STATE_FILE
text=Path('/etc/imac-audio.conf').read_text()
m=re.search(r'^AUDIO_VOLUME=([0-9.]+)$',text,re.M)
s=dict(DEFAULT,volume=float(m[1])*400 if m else 40)
atomic_json(STATE_FILE,validate(s))
PY
    chown imac-equalizer:imac-equalizer /var/lib/imac-equalizer/settings.json
fi
install -m 644 "$P/receiver/imac-equalizer.service" /etc/systemd/system/
install -m 644 "$P/receiver/imac-audio.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now imac-equalizer
systemctl restart imac-audio
printf 'Equalizer enabled on port 8787. Read /var/lib/imac-equalizer/access-token locally for the private access code.\n'
