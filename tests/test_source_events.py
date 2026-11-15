# SPDX-License-Identifier: GPL-2.0-only
import ctypes
import errno
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'receiver'))
from source_events import SourceEvents, Event, Subscription, SUBSCRIBE, DEQUEUE

class SourceEventTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'C compiler required to verify Linux UAPI ABI')
    def test_ioctl_and_struct_layout_match_system_headers(self):
        source = '''#include <stdio.h>
#include <stddef.h>
#include <linux/videodev2.h>
int main(void) { printf("%zu %zu %lu %lu %zu %zu\\n", sizeof(struct v4l2_event),
sizeof(struct v4l2_event_subscription), (unsigned long)VIDIOC_SUBSCRIBE_EVENT,
(unsigned long)VIDIOC_DQEVENT, offsetof(struct v4l2_event, timestamp), offsetof(struct v4l2_event, id)); }
'''
        with tempfile.TemporaryDirectory() as directory:
            c = Path(directory)/'abi.c'; exe = Path(directory)/'abi'; c.write_text(source)
            subprocess.run(['cc', str(c), '-o', str(exe)], check=True, capture_output=True)
            actual = list(map(int, subprocess.check_output([str(exe)]).split()))
        self.assertEqual(actual, [ctypes.sizeof(Event), ctypes.sizeof(Subscription), SUBSCRIBE, DEQUEUE, Event.timestamp.offset, Event.id.offset])

    def test_idle_poll_does_not_query_or_dequeue(self):
        watcher = SourceEvents.__new__(SourceEvents); watcher.fd = 4; watcher.poller = Mock()
        watcher.poller.poll.return_value = []
        with patch('source_events.fcntl.ioctl') as ioctl:
            self.assertEqual(watcher.drain(), [])
            ioctl.assert_not_called()

    def test_multiple_source_changes_are_drained(self):
        watcher = SourceEvents.__new__(SourceEvents); watcher.fd = 4; watcher.poller = Mock()
        watcher.poller.poll.side_effect = [[(4,select.POLLPRI)], [(4,select.POLLPRI)], []]
        sequence = iter([10,11])
        def ioctl(fd, request, buf, mutate):
            self.assertEqual(request, DEQUEUE)
            buf[:] = bytes(Event(type=5, sequence=next(sequence)))
        with patch('source_events.fcntl.ioctl', side_effect=ioctl):
            self.assertEqual(watcher.drain(), [10,11])

    def test_subscription_failure_closes_fd(self):
        with patch('source_events.platform.machine', return_value='x86_64'), patch('source_events.os.open', return_value=4), patch('source_events.os.close') as close, patch('source_events.fcntl.ioctl', side_effect=OSError(errno.EINVAL, 'unsupported')):
            with self.assertRaises(OSError): SourceEvents('/dev/video2')
            close.assert_called_once_with(4)

    def test_disconnect_is_reported(self):
        watcher = SourceEvents.__new__(SourceEvents); watcher.fd = 4; watcher.poller = Mock()
        watcher.poller.poll.return_value = [(4,select.POLLHUP)]
        with self.assertRaises(OSError): watcher.drain()

if __name__ == '__main__': unittest.main()
