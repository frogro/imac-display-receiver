# Validation and known limitations

## Hardware baseline, 15 November 2026

These results describe the staged installation on the physical iMac19,1, not
an unperformed hardware test of every future generated image.

- User confirmed correct 1080p60 and 4K30 SDR picture, colours and motion.
- GPU test: 600.74 seconds, 17,993 capture/display-submitted frames, no queue
  drops or pipeline errors. Process CPU about 11.2% of one core.
- Capture pad → synchronous sink return: median 14.30 ms, P95 23.25 ms.
  **Not HDMI-to-photon latency**: capture hardware, pre-pad delay, scanout and
  panel response are outside this interval.
- Removing an accidentally inherited serial console resolved a boot failure;
  USB boots and automatic capture were then confirmed.
- Local tone, HDMI tone and YouTube via internal speakers confirmed.
- Original mismatched speaker filters produced a 13–14 dB midrange gap in a
  digital test. Matched LR4 filters corrected it; subsequent −1.51 dB tweeter
  reduction was confirmed as less metallic with clear voices.
- Source HDMI amplification at 139% caused clipped PCM. At 100%, the receiver
  recording differed from the sender HDMI monitor by at most one 16-bit count
  in the measured section, with no clipped samples in the capture.
- Temporary audio outages during exclusive ALSA recordings were intentional;
  continuous playback was confirmed after measurement ended.

## Remaining limitations

- Native 5K output, 4K60, HDR, optical end-to-end latency and exact audio/video
  synchronization are not confirmed. No HID return path is implemented.
- HDMI format changes may produce a buffer error and an automatic restart;
  switching is not seamless. Missing input is retried, not a working picture.
- GPU failure may latch CPU fallback until reboot; inspect
  `/run/imac-receiver/gpu-fallback.json` before clearing it with capture stopped.
- Audio supports 48 kHz stereo PCM, not surround/encoded Dolby or DTS. Some
  starts logged a short 1,920-sample capture drop; steady playback was observed.
- Speaker filters do not reproduce Apple's full dynamic processing/protection.
  Use moderate volume. Uncalibrated microphone tests do not establish a room
  correction curve, RT60, or absence of mechanical distortion.
- Audio autostart was installed after the last physical boot test; a complete
  reboot with all final audio changes has not yet been signed off on hardware.
- Wi-Fi/Bluetooth and arbitrary iMac/GC555 revisions are not validated.
- HDCP-protected sources remain black according to the capture driver's policy.
- No third-display support is created on the sender by adding this receiver.

## Automated checks

Unit/integration tests cover actual GStreamer pipelines, latest-frame behaviour,
source-change events, watchdog exit, GPU fallback, audio channel filtering and
USB writer guards/readback. Pure C checks constrain the scope of the 4K FPGA
policy patch. They use fake sinks/temporary files, not real USB writes or proof
of GPU rendering. The separate manual image workflow builds the complete rootfs.
