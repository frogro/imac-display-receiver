#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Only invoked inside the NEW rootfs by build-image.sh; never run on a live host.
set -euo pipefail
P=/opt/imac-receiver
KERNEL=6.12.117+deb13-amd64
[[ -f /usr/sbin/policy-rc.d && -d /lib/modules/$KERNEL/build && -d $P/vendor ]]
cd "$P"
sha256sum --quiet -c third_party/SOURCES.sha256
python3 - <<'PY'
import gi
gi.require_version('Gst','1.0')
from gi.repository import Gst
assert Gst.version()[:3] == (1,26,2), 'GPU patch requires GStreamer 1.26.2; review before upgrading'
PY
SRC=/usr/src/gc555-0.1+git7bb5150imac1
mkdir -p "$SRC"
cp -a vendor/gc555/. "$SRC/"
for file in patches/000[123]-*.patch; do patch -d "$SRC" -p1 < "$file"; done
cat > "$SRC/dkms.conf" <<'EOF'
PACKAGE_NAME="gc555"
PACKAGE_VERSION="0.1+git7bb5150imac1"
AUTOINSTALL="yes"
BUILD_EXCLUSIVE_KERNEL="^6[.]12[.]"
MAKE[0]="make KDIR=/lib/modules/$kernelver/build"
BUILT_MODULE_NAME[0]="gc555"
BUILT_MODULE_LOCATION[0]="."
DEST_MODULE_LOCATION[0]="/updates/dkms"
EOF
dkms add -m gc555 -v 0.1+git7bb5150imac1
dkms install -m gc555 -v 0.1+git7bb5150imac1 -k "$KERNEL"
cp -a vendor/cs8409-audio-dkms /usr/src/imac-cs8409
make -C "/lib/modules/$KERNEL/build" M=/usr/src/imac-cs8409 -j2 modules
install -Dm644 /usr/src/imac-cs8409/snd-hda-codec-cs8409.ko \
    "/lib/modules/$KERNEL/updates/imac-receiver-audio/snd-hda-codec-cs8409.ko"
depmod -a "$KERNEL"
[[ $(modinfo -k "$KERNEL" -F filename snd_hda_codec_cs8409) == */updates/imac-receiver-audio/* ]]
bash tools/build-gpu.sh
cp receiver/imac-receiver.conf /etc/
sed -i 's/^GPU_ENABLED=.*/GPU_ENABLED=1/; s|^GPU_BUNDLE=.*|GPU_BUNDLE=/opt/imac-receiver/gpu|' /etc/imac-receiver.conf
cp receiver/imac-audio.conf /etc/
cp receiver/imac-{receiver,audio,equalizer}.service /etc/systemd/system/
cp vendor/gc555/udev/70-gc555.rules /etc/udev/rules.d/
chmod +x receiver/launch.sh
printf 'imac-receiver\n' > /etc/hostname
printf '127.0.0.1 localhost\n127.0.1.1 imac-receiver\n::1 localhost ip6-localhost\n' > /etc/hosts
useradd -m -s /bin/bash -G sudo,video,render,audio receiver
useradd --system --no-create-home --shell /usr/sbin/nologin imac-equalizer
printf 'receiver ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/receiver
chmod 440 /etc/sudoers.d/receiver
mkdir -p /etc/systemd/system/getty@tty2.service.d /etc/ssh/sshd_config.d /etc/systemd/journald.conf.d
cat > /etc/systemd/system/getty@tty2.service.d/autologin.conf <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin receiver --noclear %I $TERM
EOF
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' > /etc/ssh/sshd_config.d/10-receiver.conf
printf '[Journal]\nStorage=persistent\nSystemMaxUse=128M\n' > /etc/systemd/journald.conf.d/receiver.conf
mkdir -p /var/log/journal /var/log/imac-receiver
systemctl disable ssh.service
# Shared image has no authorized key, SSH host identity or machine identity.
systemctl enable NetworkManager imac-receiver imac-audio imac-equalizer getty@tty2
systemctl set-default multi-user.target
printf 'MODULES=most\n' > /etc/initramfs-tools/conf.d/receiver
printf 'usb_storage\nuas\nxhci_pci\namdgpu\n' >> /etc/initramfs-tools/modules
update-initramfs -u -k "$KERNEL"
python3 -m unittest discover -s tests -v
python3 tests/check_fpga_policy.py
dpkg-query -W -f='${Package}\t${Version}\n' > "$P/packages.tsv"
python3 - <<'PY'
import json, pathlib
pathlib.Path('BUILD-INFO.json').write_text(json.dumps({
 'project':'imac-display-receiver','kernel':'6.12.117+deb13-amd64',
 'gstreamer':'1.26.2','architecture':'amd64','ssh_enabled':False,
 'gc555':'7bb51508742adf750b17756b2211ca2bb6eeb361',
 'cs8409':'a45c14f7fdeaeb855c90af62c92cb261224bbfd1'},indent=2)+'\n')
PY
apt-get clean
rm -f /etc/ssh/ssh_host_* /usr/sbin/policy-rc.d
: > /etc/machine-id
rm -f /var/lib/dbus/machine-id
find /var/log -type f -exec truncate -s0 {} +
