# Build and reinstall

The supported target is iMac19,1 with GC555. This is AMD64, **not** the Asahi/M1
kernel or Googlebook project. Build on an x86-64 Linux host with root privileges.

## Complete integration

`tools/build-image.sh` creates a new Debian Trixie rootfs using signed packages.
It never accepts a physical disk. It installs:

- Linux image/headers `6.12.117+deb13-amd64`, matching the tested CS8409 build.
- GC555 source at the pinned revision, with patches 0001–0003, through DKMS.
- CS8409 Apple codec override for this exact kernel, leaving the stock module.
- A freshly compiled private GStreamer 1.26.2 GL library and patch 0004.
- GPU supervisor with hashed bundle and automatic CPU fallback.
- Separate video and audio services; 2 kHz LR4 crossover, tweeter gain 0.63,
  overall linear gain 0.10, shared 60 Hz high-pass, private four-channel map.
- A standalone fallback UEFI bootloader and maintenance entry. **console=tty0**
  only; no serial console on the iMac Bluetooth UART.
- A local maintenance account and persistent logs; no preauthorized TB UUID,
  no SSH key, no shared SSH host identity, no machine-id copied from a host.

The output is an 8 GiB raw image, gzip copy, checksum manifest, package list and
build information. Package repositories are signed but not snapshot-pinned;
the complete build is not claimed to be bit-reproducible. Exact tested kernel
packages and GStreamer ABI must be available. If they disappear, stop and review
new package/API compatibility instead of silently substituting a kernel.

`tools/install-usb.py` handles **only whole USB disks selected through by-id**.
It rejects mounted filesystems, active swap and dependent crypt/LVM/RAID devices,
checks disk size and serial, requires an exact typed erase confirmation, verifies
the compressed and raw image before writing, verifies the entire written image,
then grows the GPT/root partition. It does not unmount disks on your behalf.
Checksums detect corruption, not authenticity: use your own build or a separately
trusted release manifest. There is no unattended `--force` mode.

If an error occurs after writing, the stick is not declared successfully installed.
Resolve the reported error and rerun with the verified image; do not select an
internal disk as a workaround. Keep only one copy of the same generated image
connected when booting, because its filesystem UUID is copied with the image.

## Updates

Rebuild to a spare USB stick and test it before replacing the working one.
The CS8409 override is built for the pinned kernel, not automatically maintained
across arbitrary kernel upgrades. A GStreamer update may invalidate the private
library; version checking then selects the CPU fallback. Do not remove the guard.

The bootstrap leaves its rootfs for investigation and unmounts build-only
filesystems on exit. Remove the build directory only after saving any needed
image, report and logs. Do not copy personal `authorized_keys` into an image
intended for publication.

## Source redistribution

Vendored driver source, notices and patches are in this repository. The generated
image includes the exact GStreamer source archive and build recipe. Debian binary
packages are fetched from their signed repositories during a private build. Before
redistributing a complete OS image, accompany it with the corresponding source
packages and comply with the individual package/firmware distribution terms;
this source-only repository does not provide a blanket license for those binaries.
