#!/bin/bash
# SPDX-License-Identifier: GPL-2.0-only
# Builds a fresh appliance; accepts no physical destination device.
set -Eeuo pipefail
[[ $EUID == 0 && $(uname -m) == x86_64 ]] || { echo 'Run with sudo on x86_64 Linux.' >&2; exit 1; }
WORK=${1:?Usage: sudo tools/build-image.sh NEW_ABSOLUTE_BUILD_DIRECTORY}
[[ $WORK = /* && ! -e $WORK ]] || { echo 'Build directory must be new and absolute.' >&2; exit 1; }
P=$(cd -- "$(dirname -- "$0")/.." && pwd)
for tool in debootstrap sgdisk losetup mkfs.vfat mkfs.ext4 curl python3 gzip; do command -v "$tool" >/dev/null; done
mkdir -p "$WORK"
R=$WORK/rootfs
LOOP=
MOUNT=
cleanup() {
    set +e
    if [[ -n $MOUNT ]]; then
        mountpoint -q "$MOUNT/boot/efi" && umount "$MOUNT/boot/efi"
        mountpoint -q "$MOUNT" && umount "$MOUNT"
    fi
    [[ -z $LOOP ]] || losetup -d "$LOOP"
    for part in sys dev proc; do mountpoint -q "$R/$part" && umount -R "$R/$part"; done
}
trap cleanup EXIT
debootstrap --arch=amd64 --variant=minbase --keyring=/usr/share/keyrings/debian-archive-keyring.gpg \
    trixie "$R" https://deb.debian.org/debian
cat > "$R/etc/apt/sources.list" <<'EOF'
deb https://deb.debian.org/debian trixie main non-free-firmware
deb https://deb.debian.org/debian trixie-updates main non-free-firmware
deb https://security.debian.org/debian-security trixie-security main non-free-firmware
EOF
printf '#!/bin/sh\nexit 101\n' > "$R/usr/sbin/policy-rc.d"
chmod 755 "$R/usr/sbin/policy-rc.d"
mount -t proc proc "$R/proc"
mount --rbind /dev "$R/dev"; mount --make-rslave "$R/dev"
mount --rbind /sys "$R/sys"; mount --make-rslave "$R/sys"
chroot "$R" apt-get update
chroot "$R" env DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    linux-image-6.12.117+deb13-amd64 linux-headers-6.12.117+deb13-amd64 \
    systemd-sysv udev dbus network-manager openssh-server sudo ca-certificates \
    locales console-setup kbd grub-efi-amd64-bin grub2-common dosfstools e2fsprogs \
    pciutils usbutils v4l-utils libdrm-tests bolt polkitd alsa-utils \
    python3 python3-gi python3-numpy gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-tools gstreamer1.0-alsa gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-gl \
    mesa-utils firmware-amd-graphics firmware-brcm80211 build-essential dkms curl jq \
    meson ninja-build pkg-config libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
    libegl-dev libgl-dev libgles-dev libgbm-dev libdrm-dev liborc-0.4-dev libgudev-1.0-dev
mkdir -p "$R/opt/imac-receiver"
for name in receiver tools tests patches vendor third_party docs LICENSE README.md; do
    cp -a "$P/$name" "$R/opt/imac-receiver/"
done
find "$R/opt/imac-receiver" -type d -name __pycache__ -prune -exec rm -rf {} +
chroot "$R" bash /opt/imac-receiver/tools/configure-image.sh
IMAGE=$WORK/imac-receiver.img
truncate -s 8G "$IMAGE"
sgdisk --clear --new=1:2048:+512M --typecode=1:ef00 --change-name=1:IMAC-EFI \
    --new=2:0:0 --typecode=2:8300 --change-name=2:IMAC-ROOT "$IMAGE"
LOOP=$(losetup --find --show --partscan "$IMAGE")
udevadm settle
mkfs.vfat -F32 -n IMAC-EFI "${LOOP}p1"
mkfs.ext4 -F -L IMAC-ROOT -m 1 "${LOOP}p2"
ROOT_UUID=$(blkid -s UUID -o value "${LOOP}p2")
EFI_UUID=$(blkid -s UUID -o value "${LOOP}p1")
cat > "$R/etc/fstab" <<EOF
UUID=$ROOT_UUID / ext4 defaults,noatime 0 1
UUID=$EFI_UUID /boot/efi vfat umask=0077 0 2
EOF
KERNEL=6.12.117+deb13-amd64
mkdir -p "$R/boot/grub" "$R/boot/efi" "$R/tmp/receiver-efi"
cat > "$R/boot/grub/grub.cfg" <<EOF
set timeout=5
set default=0
terminal_output console
menuentry 'iMac Receiver - HDMI video and audio' {
 search --no-floppy --fs-uuid --set=root $ROOT_UUID
 linux /boot/vmlinuz-$KERNEL root=UUID=$ROOT_UUID ro rootwait console=tty0
 initrd /boot/initrd.img-$KERNEL
}
menuentry 'iMac Receiver - maintenance (capture and audio off)' {
 search --no-floppy --fs-uuid --set=root $ROOT_UUID
 linux /boot/vmlinuz-$KERNEL root=UUID=$ROOT_UUID ro rootwait console=tty0 systemd.mask=imac-receiver.service systemd.mask=imac-audio.service
 initrd /boot/initrd.img-$KERNEL
}
EOF
cat > "$R/tmp/receiver-grub.cfg" <<EOF
insmod part_gpt
insmod ext2
insmod search_fs_uuid
search --no-floppy --fs-uuid --set=root $ROOT_UUID
configfile (\$root)/boot/grub/grub.cfg
EOF
chroot "$R" grub-mkstandalone -O x86_64-efi \
    --modules='part_gpt ext2 fat normal search search_fs_uuid linux' \
    -o /tmp/receiver-efi/BOOTX64.EFI 'boot/grub/grub.cfg=/tmp/receiver-grub.cfg'
MOUNT=$(mktemp -d "$WORK/image-mount.XXXXXX")
mount "${LOOP}p2" "$MOUNT"
cp -ax "$R/." "$MOUNT/"
mount "${LOOP}p1" "$MOUNT/boot/efi"
mkdir -p "$MOUNT/boot/efi/EFI/BOOT"
cp "$R/tmp/receiver-efi/BOOTX64.EFI" "$MOUNT/boot/efi/EFI/BOOT/BOOTX64.EFI"
cp "$R/opt/imac-receiver/packages.tsv" "$WORK/packages.tsv"
cp "$R/opt/imac-receiver/BUILD-INFO.json" "$WORK/BUILD-INFO.json"
sync
umount "$MOUNT/boot/efi"; umount "$MOUNT"; rmdir "$MOUNT"; MOUNT=
losetup -d "$LOOP"; LOOP=
gzip -1 -k "$IMAGE"
python3 "$P/tools/image-manifest.py" "$IMAGE" "$WORK/image-manifest.json"
printf 'Built %s.gz\nNo USB device has been written.\n' "$IMAGE"
