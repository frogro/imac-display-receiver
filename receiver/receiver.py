#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Instrumented GStreamer MVP. Sink-entry timing is NOT panel presentation timing."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import signal
import sys
import threading
import time
import subprocess
import os
import resource
from hdmi_mode import query_mode, prepare_capture
from source_events import SourceEvents

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib
from push_meter import PushMeter


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--device', default='auto')
    p.add_argument('--auto-mode', action='store_true', help='Detect HDMI timing; exit for supervisor restart after a stable mode change')
    p.add_argument('--width', type=int, default=1920)
    p.add_argument('--height', type=int, default=1080)
    p.add_argument('--fps', default='60/1')
    p.add_argument('--format', choices=['NV12', 'YUY2', 'BGR', 'BGRx', 'P010_10LE'], default='NV12')
    p.add_argument('--io-mode', choices=['mmap', 'dmabuf'], default='mmap')
    p.add_argument('--sink', choices=['kms', 'fake'], default='kms')
    p.add_argument('--driver', default='amdgpu')
    p.add_argument('--bus-id')
    p.add_argument('--connector-id', type=int)
    p.add_argument('--plane-id', type=int)
    p.add_argument('--force-modesetting', action='store_true')
    p.add_argument('--display-format', choices=['BGRx', 'RGBx', 'BGRA'], help='Explicit color conversion for RGB-only display planes')
    p.add_argument('--converter', choices=['cpu', 'gl'], default='cpu')
    p.add_argument('--gl-dmabuf', action='store_true', help='Experimental GL rendering into KMS DMA-BUF buffers; requires validated GL caps correction')
    p.add_argument('--convert-threads', type=int, choices=range(1, 17), default=4)
    p.add_argument('--cached-output', action='store_true', help='Convert into ordinary memory instead of the downstream KMS pool')
    p.add_argument('--display-copy', choices=['native', 'stream'], help='Experimental imaccopy stage before KMS; requires cached BGRx output')
    p.add_argument('--measure-sink', action='store_true', help='Also time the downstream push through kmssink, not physical presentation')
    p.add_argument('--trace-events', action='store_true', help='Bounded in-memory capture/mode/overrun diagnostics, saved at exit')
    p.add_argument('--mode-monitor', choices=['poll', 'events'], default='poll', help='V4L2 source-change events with periodic fallback checks')
    p.add_argument('--mode-check-interval', type=float, default=2, help='HDMI polling interval; 0 disables runtime polling for comparison tests')
    p.add_argument('--queue-depth', type=int, choices=range(1, 9), default=1)
    p.add_argument('--test-pattern', action='store_true')
    p.add_argument('--frames', type=int, default=0, help='Finite source frame count; 0 is unlimited')
    p.add_argument('--seconds', type=float, default=0)
    p.add_argument('--stall-timeout', type=float, default=10)
    p.add_argument('--log-every', type=int, default=1, help='Log every Nth sink submission')
    p.add_argument('--slow-sink-ms', type=int, default=0, help='Synthetic-test fault injection only')
    p.add_argument('--log-dir', type=Path, default=Path('/var/log/imac-receiver'))
    return p


def find_capture():
    candidates = [Path('/dev')/p.name for p in Path('/sys/class/video4linux').glob('video*')
                  if 'gc555' in (p/'name').read_text().lower()]
    if len(candidates) != 1:
        raise RuntimeError(f'Expected exactly one GC555 video node, found {candidates}; use --device')
    return str(candidates[0])


def main():
    args = parser().parse_args()
    if args.width <= 0 or args.height <= 0 or args.frames < 0 or args.seconds < 0 or args.stall_timeout <= 0:
        raise ValueError('Dimensions/timeouts must be positive; frame/time limits must not be negative')
    num, den = map(int, args.fps.split('/'))
    if num <= 0 or den <= 0: raise ValueError('FPS must be positive')
    if args.log_every < 1: raise ValueError('Log sampling must be positive')
    if args.mode_check_interval < 0: raise ValueError('Mode check interval must not be negative')
    if args.display_copy and (not args.cached_output or args.display_format != 'BGRx'):
        raise ValueError('--display-copy requires --cached-output --display-format BGRx')
    if args.gl_dmabuf and (args.converter != 'gl' or args.sink != 'kms' or
                          args.display_format not in ('BGRx', 'BGRA') or
                          args.cached_output or args.display_copy):
        raise ValueError('--gl-dmabuf requires GL, KMS, BGRx/BGRA and downstream allocation')
    if args.slow_sink_ms and not args.test_pattern: raise ValueError('Fault injection requires --test-pattern')
    if args.converter == 'gl':
        if not args.display_format: raise ValueError('--converter gl requires --display-format')
        os.environ.setdefault('GST_GL_WINDOW', 'gbm')
        os.environ.setdefault('GST_GL_PLATFORM', 'egl')
    Gst.init(None)
    device = None if args.test_pattern else (find_capture() if args.device == 'auto' else args.device)
    detected_mode = None
    if args.auto_mode:
        if args.test_pattern:
            raise ValueError('--auto-mode requires a physical HDMI source')
        detected_mode = query_mode(device)
        args.width, args.height = detected_mode.width, detected_mode.height
        args.fps, args.format = f'{detected_mode.fps}/1', detected_mode.capture_format
        num, den = detected_mode.fps, 1
        prepare_capture(device, detected_mode)
        print(json.dumps(dict(hdmi_mode=vars(detected_mode), capture_format=args.format)), flush=True)
    out = args.log_dir/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True)
    (out/'config.json').write_text(json.dumps({**vars(args), 'device_resolved': device,
                                               'gstreamer': Gst.version_string()}, default=str, indent=2)+'\n')
    pipeline = Gst.Pipeline.new('imac-receiver')
    def element(factory, name):
        e = Gst.ElementFactory.make(factory, name)
        if e is None: raise RuntimeError('Missing GStreamer element: '+factory)
        pipeline.add(e)
        return e
    source = element('videotestsrc' if args.test_pattern else 'v4l2src', 'capture')
    if args.test_pattern: source.set_property('is-live', True)
    else:
        source.set_property('device', device)
        source.set_property('io-mode', args.io_mode)
    if args.frames: source.set_property('num-buffers', args.frames)
    caps = element('capsfilter', 'capture-mode')
    caps.set_property('caps', Gst.Caps.from_string(
        f'video/x-raw,format={args.format},width={args.width},height={args.height},framerate={num}/{den}'))
    latest = element('queue', 'latest-frame')
    for key, value in [('max-size-buffers', args.queue_depth), ('max-size-bytes', 0),
                       ('max-size-time', 0), ('leaky', 2)]: latest.set_property(key, value)
    sink = element('kmssink' if args.sink == 'kms' else 'fakesink', 'display')
    sink.set_property('sync', False)
    sink.set_property('enable-last-sample', False)
    if args.sink == 'kms':
        sink.set_property('driver-name', args.driver)
        sink.set_property('force-modesetting', args.force_modesetting)
        for option in ('bus_id', 'connector_id', 'plane_id'):
            if getattr(args, option) is not None: sink.set_property(option.replace('_', '-'), getattr(args, option))
    chain = [source, caps, latest]
    if args.display_format:
        if args.converter == 'cpu':
            convert = element('videoconvert', 'display-convert')
            convert.set_property('n-threads', args.convert_threads)
            chain.append(convert)
            processing_start = processing_end = convert
        else:
            upload = element('glupload', 'display-upload')
            convert = element('glcolorconvert', 'display-convert')
            gl_caps = element('capsfilter', 'gpu-format')
            gl_caps.set_property('caps', Gst.Caps.from_string(f'video/x-raw(memory:GLMemory),format={args.display_format}'))
            download = element('gldownload', 'display-download')
            chain.extend([upload, convert, gl_caps, download])
            processing_start, processing_end = upload, download
        display_caps = element('capsfilter', 'display-format')
        if args.gl_dmabuf:
            drm_format = {'BGRx': 'XR24', 'BGRA': 'AR24'}[args.display_format]
            display_caps.set_property('caps', Gst.Caps.from_string(
                f'video/x-raw(memory:DMABuf),format=DMA_DRM,drm-format={drm_format}'))
        else:
            display_caps.set_property('caps', Gst.Caps.from_string(f'video/x-raw,format={args.display_format}'))
        chain.append(display_caps)
    if args.cached_output:
        allocation = element('identity', 'separate-allocation')
        allocation.set_property('drop-allocation', True)
        allocation.set_property('signal-handoffs', False)
        chain.append(allocation)
    if args.display_copy:
        display_copy = element('imaccopy', 'host-display-copy')
        display_copy.set_property('streaming-stores', args.display_copy == 'stream')
        chain.append(display_copy)
    if args.slow_sink_ms:
        delay = element('identity', 'test-delay'); delay.set_property('sleep-time', args.slow_sink_ms*1000); chain.append(delay)
    if args.measure_sink:
        meter = PushMeter(lambda *values: record_submission(*values))
        pipeline.add(meter)
        chain.append(meter)
    chain.append(sink)
    for a, b in zip(chain, chain[1:]):
        if not a.link(b): raise RuntimeError(f'Cannot link {a.name} to {b.name}')

    loop = GLib.MainLoop()
    lock = threading.Lock()
    seen = {}
    rows = queue.Queue(maxsize=8192)
    stats = dict(source_frames=0, sink_submissions=0, logging_drops=0, queue_overruns=0,
                 errors=[], completion='unknown', start_monotonic_ns=time.monotonic_ns(),
                 mode_checks=0, source_changes=0, mode_query_errors=0, mode_query_max_ns=0)
    cpu_start = time.process_time()
    last_frame = time.monotonic()
    last_sink = last_frame
    mode_events = None
    source_changed = False
    if detected_mode and args.mode_monitor == 'events':
        try:
            mode_events = SourceEvents(device)
        except OSError as exc:
            print(json.dumps(dict(mode_event_fallback=str(exc))), flush=True)
            args.mode_check_interval = 2
    stats['mode_monitor_active'] = 'events' if mode_events else 'poll'
    next_mode_check = last_frame + args.mode_check_interval
    next_progress = last_frame + 15
    pending_mode = None
    writer_errors = []
    events = []
    def trace(kind, value=None):
        if args.trace_events and len(events) < 100000:
            events.append((time.monotonic_ns(), kind, value))
    def write_rows():
        try:
            with (out/'frames.csv').open('w', newline='') as f:
                w = csv.writer(f); w.writerow(['pts_ns','capture_exit_ns','sink_entry_ns','userspace_queue_ns',
                                              'processing_enter_ns','processing_exit_ns','queue_wait_ns','conversion_ns',
                                              'sink_return_ns','sink_push_ns','capture_to_sink_return_ns','flow_return',
                                              'display_copy_ns'])
                while True:
                    row = rows.get()
                    if row is None: break
                    w.writerow(row)
                    f.flush()
        except Exception as e: writer_errors.append(repr(e))
    writer = threading.Thread(target=write_rows, daemon=True); writer.start()
    def capture_probe(pad, info):
        nonlocal last_frame
        b = info.get_buffer()
        if b:
            now = time.monotonic_ns()
            trace('capture', b.pts)
            with lock:
                stats['source_frames'] += 1; last_frame = time.monotonic(); seen[b.pts] = {'capture': now}
                if len(seen) > 256: seen.pop(next(iter(seen)))
        return Gst.PadProbeReturn.OK
    def record_submission(pts, now, returned=None, result=None):
        nonlocal last_sink
        with lock:
            stats['sink_submissions'] += 1; timing = seen.pop(pts, {}); last_sink = time.monotonic()
            sampled = stats['sink_submissions'] % args.log_every == 0
        if not sampled: return
        start, enter, leave = timing.get('capture'), timing.get('enter'), timing.get('leave')
        try: rows.put_nowait([pts, start, now, None if start is None else now-start,
                             enter, leave, None if enter is None or start is None else enter-start,
                             None if enter is None or leave is None else leave-enter,
                             returned, None if returned is None else returned-now,
                             None if returned is None or start is None else returned-start,
                             None if result is None else int(result),
                             timing['copy_leave']-timing['copy_enter'] if 'copy_enter' in timing and 'copy_leave' in timing else None])
        except queue.Full:
            with lock: stats['logging_drops'] += 1
    def sink_probe(pad, info):
        b = info.get_buffer()
        if b:
            record_submission(b.pts, time.monotonic_ns())
        return Gst.PadProbeReturn.OK
    caps.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, capture_probe)
    def stage_probe(pad, info, stage):
        b = info.get_buffer()
        if b:
            now = time.monotonic_ns()
            with lock:
                if b.pts in seen: seen[b.pts][stage] = now
        return Gst.PadProbeReturn.OK
    if args.display_format:
        processing_start.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, stage_probe, 'enter')
        processing_end.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, stage_probe, 'leave')
    if not args.measure_sink:
        sink.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, sink_probe)
    if args.gl_dmabuf:
        gi.require_version('GstAllocators', '1.0')
        from gi.repository import GstAllocators
        stats['dmabuf_frames'] = 0
        def check_dmabuf(pad, info):
            b = info.get_buffer()
            if b:
                if b.n_memory() and all(GstAllocators.is_dmabuf_memory(b.peek_memory(i))
                                        for i in range(b.n_memory())):
                    stats['dmabuf_frames'] += 1
                else:
                    stats['errors'].append(dict(error='Expected DMA-BUF at KMS input'))
                    stats['completion'] = 'error'
                    GLib.idle_add(loop.quit)
                    return Gst.PadProbeReturn.DROP
            return Gst.PadProbeReturn.OK
        sink.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, check_dmabuf)
    if args.display_copy:
        display_copy.get_static_pad('sink').add_probe(Gst.PadProbeType.BUFFER, stage_probe, 'copy_enter')
        display_copy.get_static_pad('src').add_probe(Gst.PadProbeType.BUFFER, stage_probe, 'copy_leave')
    def overrun(*unused):
        trace('queue_overrun')
        with lock: stats['queue_overruns'] += 1
    latest.connect('overrun', overrun)
    def message(bus, msg):
        if msg.type == Gst.MessageType.ERROR:
            error, debug = msg.parse_error(); stats['errors'].append(dict(error=str(error), debug=debug))
            stats['completion'] = 'error'; loop.quit()
        elif msg.type == Gst.MessageType.EOS:
            stats['completion'] = 'eos'; loop.quit()
    bus = pipeline.get_bus(); bus.add_signal_watch(); bus.connect('message', message)
    def tick():
        nonlocal next_mode_check, pending_mode, next_progress, mode_events, source_changed
        if time.monotonic() >= next_progress:
            next_progress = time.monotonic() + 15
            with lock:
                progress = {k: stats[k] for k in ('source_frames', 'sink_submissions', 'queue_overruns', 'logging_drops')}
            progress['elapsed_seconds'] = (time.monotonic_ns()-stats['start_monotonic_ns'])/1e9
            print(json.dumps(dict(progress=progress)), flush=True)
        if mode_events:
            try:
                changes = mode_events.drain()
                if changes:
                    trace('source_change', changes[-1])
                    stats['source_changes'] += len(changes)
                    source_changed = True
                    pending_mode = None
                    next_mode_check = time.monotonic()
            except OSError as exc:
                print(json.dumps(dict(mode_event_fallback=str(exc))), flush=True)
                mode_events.close(); mode_events = None
                stats['mode_monitor_active'] = 'poll-fallback'
                args.mode_check_interval = 2
                next_mode_check = time.monotonic()
        if detected_mode and (args.mode_check_interval or source_changed) and time.monotonic() >= next_mode_check:
            next_mode_check = time.monotonic() + args.mode_check_interval
            trace('mode_check_begin')
            query_start = time.monotonic_ns()
            stats['mode_checks'] += 1
            try:
                current_mode = query_mode(device)
                if (current_mode != detected_mode or source_changed) and current_mode == pending_mode:
                    stats['completion'] = 'mode-change'
                    stats['next_hdmi_mode'] = vars(current_mode)
                    loop.quit(); return False
                pending_mode = current_mode if current_mode != detected_mode or source_changed else None
                if pending_mode is not None:
                    next_mode_check = time.monotonic() + 0.5
            except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                stats['mode_query_errors'] += 1
                pending_mode = None  # Existing frame watchdog handles signal loss.
                if source_changed: next_mode_check = time.monotonic() + 0.5
            finally:
                stats['mode_query_max_ns'] = max(stats['mode_query_max_ns'], time.monotonic_ns()-query_start)
                trace('mode_check_end')
        if writer_errors:
            stats['errors'].append(dict(error='Log writer failed', details=writer_errors));stats['completion']='error';loop.quit();return False
        if time.monotonic()-min(last_frame, last_sink) > args.stall_timeout:
            stats['errors'].append(dict(error='Capture or sink stalled')); stats['completion']='stall'; loop.quit(); return False
        if args.seconds and time.monotonic_ns()-stats['start_monotonic_ns'] >= args.seconds*1e9:
            stats['completion']='time-limit'; loop.quit(); return False
        return True
    GLib.timeout_add(250, tick)
    def stop(*unused): stats['completion']='signal';loop.quit()
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    print(json.dumps(dict(log_directory=str(out), device=device, sink=args.sink)), flush=True)
    try:
        if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            stats['errors'].append(dict(error='PLAYING state rejected'));stats['completion']='error'
        else: loop.run()
    finally:
        stats['sink_stats'] = sink.get_property('stats').to_string()
        stats['negotiated_caps'] = {}
        for e in chain:
            pad = e.get_static_pad('src')
            negotiated = pad.get_current_caps() if pad is not None else None
            if negotiated is not None: stats['negotiated_caps'][e.name] = negotiated.to_string()
        pipeline.set_state(Gst.State.NULL)
        if mode_events: mode_events.close()
        stats['mode_check_interval_seconds'] = args.mode_check_interval
        stats['elapsed_seconds']=(time.monotonic_ns()-stats['start_monotonic_ns'])/1e9
        stats['process_cpu_seconds'] = time.process_time() - cpu_start
        stats['max_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        stats['source_minus_sink']=stats['source_frames']-stats['sink_submissions']
        if writer.is_alive(): rows.put(None, timeout=5);writer.join(timeout=10)
        stats['writer_errors']=writer_errors
        if args.trace_events:
            with (out/'events.csv').open('w', newline='') as f:
                event_writer = csv.writer(f)
                event_writer.writerow(['monotonic_ns', 'event', 'value'])
                event_writer.writerows(events)
            stats['event_trace_limit_reached'] = len(events) >= 100000
        stats['interpretation']='Sink submissions are not displayed frames; timing excludes device capture and panel scanout.'
        (out/'summary.json').write_text(json.dumps(stats,indent=2)+'\n')
        print(json.dumps(stats),flush=True)
    return 75 if stats['completion'] == 'mode-change' else (1 if stats['errors'] or writer_errors else 0)


if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as e: print(str(e), file=sys.stderr);sys.exit(1)
