# SPDX-License-Identifier: GPL-2.0-only
"""Nonblocking V4L2 source-change subscription for the x86-64 receiver.

This fd never queues capture buffers or changes device format. Each open file
has its own event queue. Unsupported ABIs/devices fall back to polling.
"""
import ctypes as C
import errno
import fcntl
import os
import platform
import select

class _Data(C.Union):
    _fields_ = [('bytes', C.c_uint8 * 64), ('alignment', C.c_int64)]
class _Timespec(C.Structure):
    _fields_ = [('sec', C.c_long), ('nsec', C.c_long)]
class Event(C.Structure):
    _fields_ = [('type', C.c_uint32), ('data', _Data), ('pending', C.c_uint32),
                ('sequence', C.c_uint32), ('timestamp', _Timespec),
                ('id', C.c_uint32), ('reserved', C.c_uint32 * 8)]
class Subscription(C.Structure):
    _fields_ = [('type', C.c_uint32), ('id', C.c_uint32), ('flags', C.c_uint32),
                ('reserved', C.c_uint32 * 5)]
SUBSCRIBE = (1 << 30) | (C.sizeof(Subscription) << 16) | (ord('V') << 8) | 90
DEQUEUE = (2 << 30) | (C.sizeof(Event) << 16) | (ord('V') << 8) | 89

class SourceEvents:
    def __init__(self, device):
        if platform.machine() != 'x86_64' or C.sizeof(Event) != 136:
            raise OSError(errno.ENOTSUP, 'V4L2 event ABI not verified on this platform')
        self.fd = os.open(device, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            sub = Subscription(type=5)  # V4L2_EVENT_SOURCE_CHANGE, input 0
            fcntl.ioctl(self.fd, SUBSCRIBE, bytes(sub))
            self.poller = select.poll()
            self.poller.register(self.fd, select.POLLPRI | select.POLLERR | select.POLLHUP)
        except BaseException:
            self.close()
            raise

    def drain(self):
        result = []
        for unused in range(16):  # Bounded: never starve the frame watchdog.
            ready = self.poller.poll(0)
            if not ready:
                break
            flags = ready[0][1]
            if flags & (select.POLLHUP | select.POLLNVAL):
                raise OSError(errno.ENODEV, 'V4L2 event fd disconnected')
            if not flags & select.POLLPRI:
                break  # Some capture devices report POLLERR without queued buffers.
            buf = bytearray(C.sizeof(Event))
            try:
                fcntl.ioctl(self.fd, DEQUEUE, buf, True)
            except BlockingIOError:
                break
            event = Event.from_buffer_copy(buf)
            if event.type == 5:
                result.append(event.sequence)
        return result

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
