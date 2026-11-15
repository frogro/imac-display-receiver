#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Experimental imaccopy pixel equivalence; set GST_PLUGIN_PATH to its build."""
import gi,hashlib
from itertools import product
gi.require_version('Gst','1.0')
from gi.repository import Gst
Gst.init(None)
def frame(w,h,kind,pattern):
    middle='' if kind=='reference' else f' ! imaccopy streaming-stores={str(kind=="stream").lower()}'
    pipe=Gst.parse_launch(f'videotestsrc num-buffers=1 pattern={pattern} ! video/x-raw,format=BGRx,width={w},height={h}'+middle+' ! appsink name=out sync=false')
    pipe.set_state(Gst.State.PLAYING)
    try:
        sample=pipe.get_by_name('out').emit('try-pull-sample',5*Gst.SECOND)
        assert sample is not None, (w,h,kind)
        buffer=sample.get_buffer(); ok,m=buffer.map(Gst.MapFlags.READ); assert ok
        try:return hashlib.sha256(m.data).hexdigest()
        finally:buffer.unmap(m)
    finally:pipe.set_state(Gst.State.NULL)
for w,h in [(1,1),(7,5),(321,181),(1920,1080),(3840,2160)]:
 for pattern in ['smpte','red','gradient']:
  values={k:frame(w,h,k,pattern) for k in ['reference','native','stream']}
  assert len(set(values.values()))==1, (w,h,pattern,values)
  print(w,h,pattern,'PASS')
