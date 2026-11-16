#!/usr/bin/env python3
"""Independent HDMI stereo-PCM receiver with live EQ; never resets video."""
import json
import math
import os
import signal
import sys
import time

from equalizer_state import DEFAULT, SOURCES, STATUS_FILE, atomic_json, gain, read_settings

import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst


def log(**fields):
    print(json.dumps(fields), flush=True)


def speaker_path(volume, crossover="lr4", tweeter_gain=0.75):
    # iMac19,1: FL/FR tweeters, RL/RR woofers. Conservative crossover only;
    # this does NOT reproduce Apple's proprietary dynamic speaker processing.
    if crossover == "lr4":
        # Matched Linkwitz-Riley fourth order: two Butterworth second-order
        # sections per branch. Avoid the previous unmatched 1.39/3 kHz gap.
        high = ('audiocheblimit mode=high-pass cutoff=2000 poles=2 ripple=0 ! '
                'audiocheblimit mode=high-pass cutoff=2000 poles=2 ripple=0')
        low = ('audiocheblimit mode=low-pass cutoff=2000 poles=2 ripple=0 ! '
               'audiocheblimit mode=low-pass cutoff=2000 poles=2 ripple=0')
    elif crossover == "legacy":
        high = 'audiocheblimit mode=high-pass cutoff=3000 poles=4 ripple=0'
        low = 'audiocheblimit mode=low-pass cutoff=1390 poles=6 ripple=0'
    else:
        raise ValueError("unknown crossover")
    return f'''
      audioconvert ! audioresample !
      audio/x-raw,format=F32LE,rate=44100,channels=2 !
      volume name=gain volume={volume} !
      equalizer-3bands name=equalizer !
      audiocheblimit mode=high-pass cutoff=60 poles=2 ripple=0 ! tee name=split
      split. ! queue max-size-time=100000000 max-size-buffers=0 max-size-bytes=0 !
        {high} ! volume volume={tweeter_gain} !
        audioconvert mix-matrix="<<(float)1,(float)0>,<(float)0,(float)1>,<(float)0,(float)0>,<(float)0,(float)0>>" !
        audio/x-raw,channels=4,channel-mask=(bitmask)0x33 ! mix.
      split. ! queue max-size-time=100000000 max-size-buffers=0 max-size-bytes=0 !
        {low} !
        audioconvert mix-matrix="<<(float)0,(float)0>,<(float)0,(float)0>,<(float)1,(float)0>,<(float)0,(float)1>>" !
        audio/x-raw,channels=4,channel-mask=(bitmask)0x33 ! mix.
      audiomixer name=mix ! audioconvert !
      audio/x-raw,format=S32LE,rate=44100,channels=4,channel-mask=(bitmask)0x33
    '''


def main():
    Gst.init(None)
    volume = float(os.environ.get("AUDIO_VOLUME", "0.10"))
    if not math.isfinite(volume) or not 0 <= volume <= 0.25:
        raise ValueError("AUDIO_VOLUME must be between 0 and 0.25 (software attenuation)")
    tweeter_gain = float(os.environ.get("AUDIO_TWEETER_GAIN", "0.63"))
    if not math.isfinite(tweeter_gain) or not 0 <= tweeter_gain <= 1:
        raise ValueError("AUDIO_TWEETER_GAIN must be between 0 and 1")
    settings = {**DEFAULT, 'volume': volume * 400}
    try:
        settings = read_settings()
    except FileNotFoundError:
        pass
    except (OSError, ValueError, TypeError):
        log(event='invalid_settings', action='using configured defaults')
    source_name = settings['source']
    source = (f'alsasrc name=capture device={SOURCES[source_name]} buffer-time=40000 '
              'latency-time=10000 provide-clock=false slave-method=resample ! '
              'audio/x-raw,channels=2,rate=48000,format=S16LE')
    if "--test-tone" in sys.argv:
        source = ('audiotestsrc name=capture is-live=true wave=sine freq=600 '
                  'volume=0.15 num-buffers=500 samplesperbuffer=441 ! '
                  'audio/x-raw,rate=44100,channels=2')
    pipeline = Gst.parse_launch(source + ' ! ' + speaker_path(volume, tweeter_gain=tweeter_gain) +
        ' ! alsasink name=playback device=imac_speakers buffer-time=40000 latency-time=10000')
    pipeline.get_by_name("gain").set_property("volume", gain(settings))
    for key, prop in (("bass", "band0"), ("mid", "band1"), ("treble", "band2")):
        pipeline.get_by_name("equalizer").set_property(prop, settings[key])
    loop = GLib.MainLoop()
    started = time.monotonic()
    counts = {"capture": 0, "playback": 0}
    last = {"capture": started, "playback": started}
    code = 0

    def probe(pad, info, name):
        counts[name] += 1
        last[name] = time.monotonic()
        return Gst.PadProbeReturn.OK

    for name, padname in (("capture", "src"), ("playback", "sink")):
        pipeline.get_by_name(name).get_static_pad(padname).add_probe(
            Gst.PadProbeType.BUFFER, probe, name)

    def stop(reason, failure=False):
        nonlocal code
        if failure:
            code = 75
        log(event="stop", reason=reason, counts=counts)
        loop.quit()
        return False

    def message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            log(event="error", element=msg.src.get_name(), error=str(err), detail=debug)
            stop("pipeline error; retry after HDMI/device recovery", True)
        elif msg.type == Gst.MessageType.WARNING:
            err, debug = msg.parse_warning()
            log(event="warning", error=str(err), detail=debug)
        elif msg.type == Gst.MessageType.EOS:
            stop("end of stream", "--test-tone" not in sys.argv)
        elif msg.type == Gst.MessageType.LATENCY:
            pipeline.recalculate_latency()

    target = dict(settings)
    applied = dict(settings)
    control_ticks = 0
    status_enabled = STATUS_FILE.parent.exists() and "--test-tone" not in sys.argv

    def publish_status(running):
        if not status_enabled:
            return
        try:
            atomic_json(STATUS_FILE, dict(updated=time.time(), running=running,
                source=source_name, settings=applied, counts=counts,
                idle_seconds={k: round(time.monotonic()-v, 2) for k, v in last.items()}))
            # Nonprivileged web service needs only read access to this status.
            os.chmod(STATUS_FILE, 0o644)
        except OSError as exc:
            log(event="status_write_failed", error=str(exc))

    def controls():
        nonlocal target, control_ticks
        control_ticks += 1
        if control_ticks % 4 == 0:
            try:
                updated = read_settings()
                if updated['source'] != source_name:
                    publish_status(False)
                    return stop("audio source changed", True)
                target = updated
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError):
                # Keep the last valid state; never increase gain on corrupt input.
                pass
        for key, step in (("volume", 1), ("bass", .25), ("mid", .25), ("treble", .25)):
            delta = target[key] - applied[key]
            applied[key] += max(-step, min(step, delta))
        applied['mute'] = target['mute']
        # Reserve target boost headroom before raising any band.
        pipeline.get_by_name('gain').set_property('volume', min(gain(applied), gain(target)))
        for key, prop in (("bass", "band0"), ("mid", "band1"), ("treble", "band2")):
            pipeline.get_by_name('equalizer').set_property(prop, applied[key])
        if control_ticks % 20 == 0:
            publish_status(True)
        return True

    def heartbeat():
        now = time.monotonic()
        idle = {name: round(now - t, 2) for name, t in last.items()}
        log(event="progress", elapsed=round(now-started, 2), counts=counts, idle_seconds=idle)
        if any(t > 12 for t in idle.values()):
            return stop("audio stalled", True)
        return True

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", message)
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop, "signal")
    GLib.timeout_add_seconds(5, heartbeat)
    GLib.timeout_add(50, controls)
    log(event="start", input=source_name + " stereo PCM", output="iMac19,1 four speakers",
        volume=volume, tweeter_gain=tweeter_gain, crossover_hz=2000, output_rate=44100)
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            log(event="start_failed")
            return 75
        loop.run()
    finally:
        pipeline.set_state(Gst.State.NULL)
        publish_status(False)
    return code


if __name__ == "__main__":
    sys.exit(main())
