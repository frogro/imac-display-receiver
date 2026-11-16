# iMac Display Receiver

Use an **Intel iMac 2019 27-inch (iMac19,1)** as a fullscreen HDMI receiver
with an **AVerMedia Live Gamer BOLT GC555** and a bootable Linux USB stick.
The HDMI source needs no receiver application. This is a capture-and-display
appliance, not Apple's Target Display Mode or a native Thunderbolt video input.

```text
HDMI source ── HDMI ──> GC555 HDMI IN
                            │ Thunderbolt
                            ▼
                     iMac 2019 27-inch
                  Linux boots from USB stick
                 internal screen + speakers
```

## Tested on the physical iMac

- 1920×1080 at 60 Hz and 3840×2160 at 30 Hz SDR, picture and colours confirmed.
- GPU conversion and DMA-BUF display path, automatic CPU fallback.
- HDMI stereo PCM at 48 kHz to the four internal speaker channels.
- Corrected speaker crossover and reduced tweeter gain; clear voices confirmed.
- UEFI removable-media boot. No internal drive or firmware boot order changed.

The current source installer combines the fixes previously installed in stages.
A successful build/VM test is **not** a new hardware acceptance test. See
[validation and known limitations](docs/validation.md).

## Create your USB installation (Linux x86-64)

Use a USB stick of **16 GB or larger**. Building needs approximately **20 GB
free workspace** and Internet access. The writer erases the selected stick,
verifies the complete image and expands its root filesystem. The examples do
not select a physical disk automatically.

```sh
git clone https://github.com/frogro/imac-display-receiver.git
cd imac-display-receiver
sudo apt-get install debootstrap debian-archive-keyring gdisk dosfstools \
  e2fsprogs parted curl python3 util-linux gzip

# Choose a NEW absolute directory on a filesystem with enough free space:
sudo bash tools/build-image.sh /var/tmp/imac-receiver-build

# Inspect disks first:
python3 tools/install-usb.py --list
ls -l /dev/disk/by-id/usb-*

# Replace usb-YOUR_STICK with the whole-disk link for YOUR USB stick.
# Unmount its existing partitions first. The installer asks for its serial.
sudo python3 tools/install-usb.py \
  --image /var/tmp/imac-receiver-build/imac-receiver.img.gz \
  --manifest /var/tmp/imac-receiver-build/image-manifest.json \
  --device /dev/disk/by-id/usb-YOUR_STICK
```

No prebuilt OS image is currently published. The **Build complete USB image**
GitHub Actions workflow verifies the source build and stores its report.
It does not automatically publish an OS image or write any USB device.
Kernel and GStreamer versions deliberately fail closed when unavailable or
different: review the integrations before changing those pins.

## Boot and connect

1. Plug the stick into the iMac. Hold **Alt/Option** while powering on and select
   **EFI Boot**. Select the normal receiver entry.
2. Connect Ethernet for initial setup. Wi-Fi/Bluetooth are not validated.
3. Connect GC555 by **Thunderbolt to the iMac**. Connect the source to **HDMI IN**,
   not HDMI OUT. Initially select 1080p60 SDR on the source.
4. If Thunderbolt authorization is needed, press **Ctrl+Alt+F2** (Apple keyboard:
   Control+Option+F2, possibly Fn), then `boltctl list`. Verify the GC555's own
   displayed device UUID and run `sudo boltctl enroll DEVICE_UUID --policy auto`.
   Do not authorize an unrelated device. Capture starts automatically afterward.
5. Choose HDMI stereo PCM/48 kHz for source audio. Keep the source system volume
   at or below **100%**; amplification above 100% caused measured clipping.

For 4K use 3840×2160/30 SDR; desktop scaling belongs on the HDMI source.
The original iMac is a 5K model, but native 5K output is not established here.
A third screen still requires a usable output on the source machine; this
receiver does not bypass its GPU/display limits.

## Maintenance

The local `receiver` account autologs into **tty2** and has passwordless sudo:
this is a physically accessible appliance, not a locked-down shared workstation.
**SSH is disabled by default**, with no shared password or authorized key.
To enable key-only SSH, locally run:

```sh
sudo /opt/imac-receiver/tools/enable-ssh.sh /path/to/your_public_key.pub
```

Video: `/etc/imac-receiver.conf`. Audio: `/etc/imac-audio.conf`.
`journalctl -b -u imac-receiver -u imac-audio` shows receiver logs.
The maintenance boot entry disables both capture and audio. A normal firmware
reboot may select the iMac's internal OS; use Option → EFI Boot again.

[Build and reinstall details](docs/install.md) ·
[Validation and limits](docs/validation.md) ·
[Third-party provenance](third_party/README.md)

## License

Project scripts and GC555 patches: **GPL-2.0-only**, see [LICENSE](LICENSE).
Vendored drivers retain their original notices and licenses. The private
GStreamer library is LGPL-2.0-or-later; its exact source archive, patch and
license are included in the generated image. Debian packages and firmware
retain their own licenses. No TargetBridge source was copied.

The repository publishes source, not private recordings, device identities,
SSH credentials or a clone of an installed system.

## Live speaker equalizer

The receiver includes a local browser control at `http://imac-receiver.local:8787/`
(or its LAN IP). Bass, midrange, treble, volume and mute apply without restarting
audio. Custom sound profiles survive reboot. The speaker crossover and high-pass
filter remain active. See [setup, access code and rollback](docs/equalizer.md).
