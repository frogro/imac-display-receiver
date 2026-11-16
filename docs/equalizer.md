# Local speaker equalizer

The browser controller changes the receiver's iMac speakers, not the macOS
system equalizer. Open `http://imac-receiver.local:8787/` or the receiver's LAN
IP on a Mac, phone or other device in the same network.

## Installation and access

New images enable `imac-equalizer.service` on first boot. Each receiver creates
its own private access token; no shared token is shipped in the image or repo.
For an existing installation, copy the current receiver directory and installer
to `/opt/imac-receiver`, back up the existing audio files/unit, then run:

```sh
sudo bash /opt/imac-receiver/tools/install-equalizer.sh
sudo cat /var/lib/imac-equalizer/access-token
```

Enter that code on the page. A personal link may alternatively include the code
after `#` (`http://RECEIVER-IP:8787/#CODE`). The fragment is removed from the
address bar and stored for the current browser session. Keep that link private.
This is authenticated HTTP for a trusted local network, not an Internet-facing
service. Do not forward port 8787 from the router; HTTP is not encrypted.

The server runs as `imac-equalizer`, has no shell/sudo/audio-device permission,
and can write only its state directory under systemd's filesystem restrictions.
API requests require the token; cross-origin writes are rejected.

## Controls

- Volume: 0–100% maps to the existing 0–0.25 linear amplitude limit. The normal
  0.10 setting appears as 40%; first installation preserves the configured gain.
- Bass (100 Hz), midrange (1.1 kHz), treble (11 kHz): -6 to +6 dB.
- Positive gains reserve headroom equal to the sum of positive band gains.
  Boosting a band can therefore reduce overall loudness. This is conservative
  static headroom, not a calibrated loudspeaker excursion or thermal limiter.
- Neutral, Sprache and Warm presets; up to 12 named custom profiles. Profiles
  change only EQ, never volume, mute or input selection.
- HDMI input: GC555 (`hw:BOLT,0`) or HD60 X (`hw:X,0`). Select the device carrying
  HDMI audio. Source changes restart only the audio process and can take about
  five seconds; video selection is unchanged. GC555 remains the default.

Tone/volume are smoothed in the live GStreamer path. The existing 60 Hz
high-pass, 2 kHz LR4 crossover, four-channel routing and tweeter attenuation
remain in place. Neutral EQ preserves that previous speaker tuning; it does not
bypass the speaker filters.

Status indicates running buffer flow, not a guarantee of audible input. A
capture device can deliver silence even when its audio pipeline is running.

## Persistence and diagnostics

`/var/lib/imac-equalizer/settings.json`, `profiles.json`, and `access-token` are
local private runtime files and must not be committed or copied into public
images. Writes are atomic. Invalid settings are rejected by the API; the audio
process retains its last valid controls if a file becomes unreadable.
Audio status is published to `/run/imac-audio-status/status.json`.

```sh
systemctl status imac-equalizer imac-audio
journalctl -b -u imac-equalizer -u imac-audio
```

Reset access: stop `imac-equalizer`, remove only its `access-token`, then start
it; a fresh token is created. Saved EQ settings and profiles are retained.
To remove the feature, disable the web service and restore the backed-up
`audio.py` and audio unit, then daemon-reload and restart only `imac-audio`.
No display driver or boot configuration is involved.

## Validation (2026-11-16)

38 tests passed; the privileged USB loop test was skipped because this change
only affects audio/UI. Existing crossover/channel tests still pass. New tests
exercise full-scale synthetic PCM with all bands boosted, gain bounds,
authentication, cross-origin rejection, atomic persistence and custom profiles.

On the iMac, the browser applied Warm and Neutral without changing the audio
PID. A custom profile was saved and removed. Both ALSA source selections
produced progressing capture/playback buffers. After restarting the two audio
control services, the saved settings were recovered. Final state: GC555,
40% volume, mute off, neutral EQ. No whole-system reboot or new full image
build was performed for this update. Acoustic preference remains user-adjustable.
