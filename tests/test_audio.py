"""Exercise actual filters and speaker channel routing with synthetic PCM."""
import sys
import unittest
from pathlib import Path

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "receiver"))
from audio import Gst, speaker_path


class SpeakerPathTest(unittest.TestCase):
    def test_crossover_channel_routing(self):
        Gst.init(None)
        for frequency in (200, 1800, 2200, 5000):
            with self.subTest(frequency=frequency):
                pipeline = Gst.parse_launch(
                    f"audiotestsrc freq={frequency} volume=0.2 num-buffers=30 ! "
                    "audio/x-raw,channels=2,rate=44100 ! " + speaker_path(.1, tweeter_gain=.63) +
                    " ! appsink name=out sync=false")
                output = pipeline.get_by_name("out")
                chunks = []
                try:
                    pipeline.set_state(Gst.State.PLAYING)
                    while True:
                        sample = output.emit("try-pull-sample", Gst.SECOND)
                        if sample:
                            buffer = sample.get_buffer()
                            chunks.append(np.frombuffer(buffer.extract_dup(0, buffer.get_size()),
                                                        dtype="<i4").reshape(-1, 4).astype(float))
                        elif output.get_property("eos"):
                            break
                        else:
                            self.fail("Filter pipeline stalled")
                finally:
                    pipeline.set_state(Gst.State.NULL)
                values = np.concatenate(chunks)[4000:]
                self.assertLess(np.max(np.abs(values)), 2**31 - 1)
                rms = np.sqrt(np.mean(values * values, axis=0))
                self.assertAlmostEqual(rms[0], rms[1])
                self.assertAlmostEqual(rms[2], rms[3])
                if frequency == 200:
                    self.assertGreater(rms[2], rms[0] * 100)
                elif frequency == 5000:
                    self.assertGreater(rms[0], rms[2] * 20)
                else:
                    # An ideal same-side acoustic sum must not repeat the
                    # old 14 dB crossover notch. This does not model the room.
                    combined = np.sqrt(np.mean((values[:, 0] + values[:, 2]) ** 2))
                    reference = .2 * .1 * 2**31 / np.sqrt(2)
                    self.assertGreater(combined / reference, .75)


if __name__ == "__main__":
    unittest.main()
