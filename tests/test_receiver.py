import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'receiver/receiver.py'
class PipelineTests(unittest.TestCase):
    def run_case(self,*extra):
        with tempfile.TemporaryDirectory() as d:
            r=subprocess.run(['python3',str(SCRIPT),'--test-pattern','--sink','fake','--width','320','--height','180','--log-dir',d,*extra],capture_output=True,text=True,timeout=15)
            summaries=list(Path(d).glob('*/summary.json'))
            return r,json.loads(summaries[0].read_text()) if summaries else None
    def test_live_pipeline_and_eos(self):
        r,d=self.run_case('--frames','60');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(d['source_frames'],60);self.assertEqual(d['sink_submissions'],60)
        self.assertEqual(d['logging_drops'],0);self.assertEqual(d['completion'],'eos')
    def test_cached_output_and_sink_meter_preserve_caps_and_frames(self):
        r,d=self.run_case('--frames','30','--display-format','BGRx','--cached-output','--measure-sink')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(d['source_frames'],30);self.assertEqual(d['sink_submissions'],30)
        self.assertIn('format=(string)BGRx',d['negotiated_caps']['separate-allocation'])
        self.assertEqual(d['negotiated_caps']['display-format'],d['negotiated_caps']['separate-allocation'])
    def test_latest_frame_drops_backlog(self):
        r,d=self.run_case('--frames','120','--slow-sink-ms','45');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(d['source_frames'],120);self.assertLess(d['sink_submissions'],70)
        self.assertGreater(d['queue_overruns'],30);self.assertLess(d['elapsed_seconds'],4)
    def test_invalid_framerate_fails_before_start(self):
        r,d=self.run_case('--fps','0/1');self.assertNotEqual(r.returncode,0);self.assertIsNone(d)
    def test_dma_display_rejects_incompatible_memory_paths(self):
        # A fake sink cannot supply display buffers, and drop-allocation would
        # disconnect GL from the downstream DMA-BUF pool. Fail before capture.
        for extra in [('--gl-dmabuf',),
                      ('--gl-dmabuf','--converter','gl','--display-format','BGRx','--cached-output')]:
            with self.subTest(extra=extra):
                r,d=self.run_case(*extra)
                self.assertNotEqual(r.returncode,0)
                self.assertIn('requires GL, KMS',r.stderr)
                self.assertIsNone(d)
    def test_stalled_sink_exits_with_diagnostic(self):
        r,d=self.run_case('--frames','120','--slow-sink-ms','1500','--stall-timeout','0.6')
        self.assertNotEqual(r.returncode,0);self.assertEqual(d['completion'],'stall')
if __name__=='__main__':unittest.main()
