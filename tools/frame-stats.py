#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Summarize measured receiver stages; never HDMI-to-panel latency."""
import csv,json,sys
from pathlib import Path
rows=list(csv.DictReader(Path(sys.argv[1]).open()))
failed_pushes = sum(r.get('flow_return') not in (None, '', '0') for r in rows)
rows = [r for r in rows if r.get('flow_return') in (None, '', '0')]
def stats(values):
    a=sorted(values)
    if not a:return None
    def q(f):return a[min(len(a)-1,int((len(a)-1)*f))]
    return dict(samples=len(a),minimum=min(a),p50=q(.5),p95=q(.95),p99=q(.99),maximum=max(a),mean=sum(a)/len(a))
def column(name):return [int(r[name])/1e6 for r in rows if r.get(name)]
pts=[int(r['pts_ns']) for r in rows if r.get('pts_ns')]
result=dict(
    receiver_path_ms=stats(column('userspace_queue_ns')),
    queue_wait_ms=stats(column('queue_wait_ns')),
    conversion_and_buffer_preparation_ms=stats(column('conversion_ns')),
    display_copy_ms=stats(column('display_copy_ns')),
    sink_push_ms=stats(column('sink_push_ns')),
    capture_to_sink_return_ms=stats(column('capture_to_sink_return_ns')),
    kept_frames_pts_interval_ms=stats([(b-a)/1e6 for a,b in zip(pts,pts[1:]) if b>a]),
    excluded_unsuccessful_pushes=failed_pushes,
    scope='Receiver path ends at sink entry. Optional sink-push and capture-to-sink-return include the synchronous downstream push but are not presentation timestamps. Same host monotonic clock; excludes HDMI capture, driver-to-source delay and physical panel response. GPU work may be asynchronous. Conversion includes buffer preparation. PTS intervals cover kept/sampled frames only.',
    source_csv=str(Path(sys.argv[1]).resolve()))
print(json.dumps(result,indent=2))
