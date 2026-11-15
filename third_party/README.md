# Third-party sources

Vendored files preserve upstream copyright and license notices. They are regular
source files so a GitHub source archive is sufficient; no submodule credentials
or floating branch checkout is required.

| Component | Origin | Revision / source hash | License |
|---|---|---|---|
| GC555 | https://github.com/ostrich/gc555 | `7bb51508742adf750b17756b2211ca2bb6eeb361` | GPL-2.0-only; vendor/gc555/COPYING |
| CS8409 | https://github.com/frogro/cs8409-audio-dkms | `a45c14f7fdeaeb855c90af62c92cb261224bbfd1` | Original GPL notices; vendor/cs8409-audio-dkms/LICENSE |
| GStreamer gst-plugins-base | https://gstreamer.freedesktop.org/src/gst-plugins-base/gst-plugins-base-1.26.2.tar.xz | SHA-256 `f4b9fc0be852fe5f65401d18ae6218e4aea3ff7a3c9f8d265939b9c4704915f7` | LGPL-2.0-or-later; COPYING.GStreamer |

The build verifies `SOURCES.sha256` before using vendored drivers and local
patches. GC555 modifications are separate patches 0001–0003. CS8409 is built
without running its upstream installer: no unrelated GRUB, suspend or T2 hooks.
Patch 0004 is a local, narrow GStreamer linear-buffer capability correction,
not a claim that the complete newer upstream GL implementation was backported.
Private libgstgl is loaded only into the receiver's GPU process, not installed
over the system libraries.

The GPU source archive, patch and license are retained with the compiled library
in the generated image. Debian packages and firmware have independent copyright
files under `/usr/share/doc/*/copyright`. No private recordings or third-party
music/video assets are published here.
