import sys
import time
import unittest
from pathlib import Path

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'receiver'))
from push_meter import PushMeter


class PushMeterTests(unittest.TestCase):
    def test_records_downstream_wait_and_preserves_flow(self):
        Gst.init(None)
        results = []
        pipeline = Gst.Pipeline.new('timing-test')
        source = Gst.ElementFactory.make('videotestsrc')
        source.set_property('num-buffers', 8)
        meter = PushMeter(lambda *values: results.append(values))
        sink = Gst.ElementFactory.make('fakesink')
        sink.set_property('sync', False)
        sink.set_property('signal-handoffs', True)
        sink.connect('handoff', lambda *unused: time.sleep(.005))
        for element in (source, meter, sink): pipeline.add(element)
        self.assertTrue(source.link(meter))
        self.assertTrue(meter.link(sink))
        pipeline.set_state(Gst.State.PLAYING)
        try:
            message = pipeline.get_bus().timed_pop_filtered(5 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
            self.assertIsNotNone(message)
            self.assertEqual(message.type, Gst.MessageType.EOS)
            self.assertEqual(len(results), 8)
            for pts, entered, returned, flow in results:
                self.assertGreaterEqual(returned - entered, 4_000_000)
                self.assertEqual(flow, Gst.FlowReturn.OK)
            self.assertIsNotNone(sink.get_static_pad('sink').get_current_caps())
        finally:
            pipeline.set_state(Gst.State.NULL)
