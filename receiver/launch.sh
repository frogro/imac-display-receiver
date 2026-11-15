#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-only
set -eu
. /etc/imac-receiver.conf
printf 'iMac Receiver: waiting for GC555; diagnosis/login is available on tty2.\n'
while ! python3 -c 'from pathlib import Path; import sys; sys.exit(not any("gc555" in (p/"name").read_text().lower() for p in Path("/sys/class/video4linux").glob("video*")))'; do sleep 5; done
set -- --device "$DEVICE" --width "$WIDTH" --height "$HEIGHT" --fps "$FPS" --format "$FORMAT" --io-mode "$IO_MODE" --driver "$DRIVER" --log-every 60
if [ -n "$CONNECTOR_ID" ]; then set -- "$@" --connector-id "$CONNECTOR_ID"; fi
if [ -n "$BUS_ID" ]; then set -- "$@" --bus-id "$BUS_ID"; fi
if [ -n "${DISPLAY_FORMAT:-}" ]; then set -- "$@" --display-format "$DISPLAY_FORMAT"; fi
if [ "${FORCE_MODESETTING:-0}" = 1 ]; then set -- "$@" --force-modesetting; fi
if [ "${AUTO_MODE:-0}" = 1 ]; then set -- "$@" --auto-mode; fi
set -- "$@" --convert-threads "${CONVERT_THREADS:-4}"
if [ "${CACHED_OUTPUT:-0}" = 1 ]; then set -- "$@" --cached-output; fi
set -- "$@" --mode-monitor "${MODE_MONITOR:-poll}" --mode-check-interval "${MODE_CHECK_INTERVAL:-2}"
if [ "${GPU_ENABLED:-0}" = 1 ]; then
    exec /usr/bin/python3 /opt/imac-receiver/receiver/gpu_supervisor.py \
        --bundle "${GPU_BUNDLE:-/opt/imac-receiver/experimental/gpu-dmabuf-20261115}" -- "$@"
fi
exec /usr/bin/python3 /opt/imac-receiver/receiver/receiver.py "$@"
