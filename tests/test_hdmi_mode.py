from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'receiver'))
from hdmi_mode import parse_timings, Mode

class TimingTests(unittest.TestCase):
    def timing(self, w=1920,h=1080,rate='59.62',field='progressive'):
        return f'Active width: {w}\nActive height: {h}\nFrame format: {field}\nPixelclock: 147558000 Hz ({rate} frames per second)\n'
    def test_observed_1080p_clock_maps_to_native_format(self):
        mode=parse_timings(self.timing());self.assertEqual(mode,Mode(1920,1080,60));self.assertEqual(mode.capture_format,'NV12')
    def test_observed_4k30_uses_yuy2(self):
        mode=parse_timings(self.timing(3840,2160,'29.81'));self.assertEqual(mode,Mode(3840,2160,30));self.assertEqual(mode.capture_format,'YUY2')
    def test_observed_4k30_clock_after_module_reload(self):
        self.assertEqual(parse_timings(self.timing(3840,2160,'29.54')),Mode(3840,2160,30))
    def test_4k5994_and_1080p50(self):
        self.assertEqual(parse_timings(self.timing(3840,2160,'59.94')),Mode(3840,2160,60))
        self.assertEqual(parse_timings(self.timing(rate='50.00')).capture_format,'YUY2')
    def test_signal_loss_does_not_reuse_stale_mode(self):
        with self.assertRaises(ValueError):parse_timings('VIDIOC_QUERY_DV_TIMINGS: failed: Link has been severed')
    def test_reject_interlace_unknown_rate_and_unsupported_size(self):
        for t in [self.timing(field='interlaced'),self.timing(rate='41.00'),self.timing(5120,2880)]:
            with self.subTest(t=t),self.assertRaises(ValueError):parse_timings(t)
if __name__=='__main__':unittest.main()
