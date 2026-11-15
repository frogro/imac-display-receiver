# SPDX-License-Identifier: GPL-2.0-only
"""Transparent push timer. A completed push is not proof of panel presentation."""
import time
from gi.repository import Gst


class PushMeter(Gst.Element):
    def __init__(self, callback):
        super().__init__()
        self.set_name('display-handoff')
        self.callback = callback
        self.input = Gst.Pad.new('sink', Gst.PadDirection.SINK)
        self.output = Gst.Pad.new('src', Gst.PadDirection.SRC)
        self.input.set_chain_function_full(self.chain)
        self.input.set_event_function_full(lambda pad, parent, event: self.output.push_event(event))
        self.output.set_event_function_full(lambda pad, parent, event: self.input.push_event(event))
        self.input.set_query_function_full(lambda pad, parent, query: self.output.peer_query(query))
        self.output.set_query_function_full(lambda pad, parent, query: self.input.peer_query(query))
        self.add_pad(self.input)
        self.add_pad(self.output)

    def chain(self, pad, parent, buffer):
        pts = buffer.pts
        entered = time.monotonic_ns()
        result = self.output.push(buffer)
        returned = time.monotonic_ns()
        self.callback(pts, entered, returned, result)
        return result
