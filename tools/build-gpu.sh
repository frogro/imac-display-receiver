#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
set -euo pipefail
P=/opt/imac-receiver
W=/tmp/imac-gst-build
[[ ! -e $W && -f $P/patches/0004-gstreamer-linear-caps.patch ]]
mkdir "$W"
trap 'rm -rf -- "$W"' EXIT
curl --fail --location --retry 3 \
    https://gstreamer.freedesktop.org/src/gst-plugins-base/gst-plugins-base-1.26.2.tar.xz -o "$W/source.tar.xz"
printf '%s  %s\n' f4b9fc0be852fe5f65401d18ae6218e4aea3ff7a3c9f8d265939b9c4704915f7 "$W/source.tar.xz" | sha256sum -c -
tar -xf "$W/source.tar.xz" -C "$W"
cd "$W/gst-plugins-base-1.26.2"
patch -p1 < "$P/patches/0004-gstreamer-linear-caps.patch"
meson setup build --buildtype=release --auto-features=disabled -Dgl=enabled -Ddrm=enabled \
    -Dgl_api=opengl,gles2 -Dgl_platform=egl -Dgl_winsys=gbm,surfaceless -Dorc=enabled
ninja -j2 -C build gst-libs/gst/gl/libgstgl-1.0.so.0.2602.0
mkdir -p "$P/gpu/"{lib,runtime,source}
cp build/gst-libs/gst/gl/libgstgl-1.0.so.0.2602.0 "$P/gpu/lib/libgstgl-1.0.so.0"
cp "$P/receiver/"{receiver,hdmi_mode,source_events,push_meter}.py "$P/gpu/runtime/"
cp "$W/source.tar.xz" "$P/gpu/source/gst-plugins-base-1.26.2.tar.xz"
cp COPYING "$P/gpu/source/"
cp "$P/patches/0004-gstreamer-linear-caps.patch" "$P/gpu/source/"
cd "$P/gpu"
find lib runtime source -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
PYTHONPATH="$P/receiver" python3 - <<'PY'
from pathlib import Path
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
from gpu_supervisor import validate_bundle
validate_bundle(Path('/opt/imac-receiver/gpu'),Gst.version())
PY
