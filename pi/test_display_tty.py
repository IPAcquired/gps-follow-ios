import fcntl
import os
import struct
import termios
import unittest
from unittest.mock import patch

from direct_usb import BASE_BAUD, DirectAttachment, open_direct


class DisplayTtyTests(unittest.TestCase):
    def setUp(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        self.node = os.ttyname(slave)
        attrs = termios.tcgetattr(slave)
        attrs[2] |= termios.HUPCL
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        original = fcntl.ioctl
        self.lines = []
        def observe(fd, op, *args):
            if op in (termios.TIOCMBIC, termios.TIOCMBIS):
                mask, = struct.unpack("I", args[0])
                self.lines.append((op, mask))
                return 0
            return original(fd, op, *args)
        hook = patch.object(fcntl, "ioctl", observe)
        hook.start()
        self.addCleanup(hook.stop)

    def test_reauthorization_reuses_fd_and_requires_fresh_wire(self):
        holder = DirectAttachment()
        self.addCleanup(holder.close)
        key = b"123456"
        with holder.open(self.node, "attach1", key, lambda:None) as first:
            device = first.serial
            self.assertFalse(termios.tcgetattr(device.fileno())[2] & termios.HUPCL)
            device.baudrate = 2000000
        self.assertTrue(device.is_open)
        with self.assertRaises(PermissionError), holder.open(self.node, "attach1", key, lambda:None) as second:
            self.assertIsNot(first, second)
            self.assertIs(second.serial, device)
            self.assertEqual(device.baudrate, BASE_BAUD)
            self.assertFalse(second.active)
            raise PermissionError("owner guard")
        self.assertTrue(device.is_open)
        both = (termios.TIOCMBIC, termios.TIOCM_DTR | termios.TIOCM_RTS)
        self.assertEqual(self.lines, [both, both])
        with holder.open(self.node, "attach2", key, lambda:None) as third:
            self.assertFalse(device.is_open)
            self.assertTrue(third.serial.is_open)
        holder.close()
        self.assertFalse(third.serial.is_open)
        self.assertEqual(self.lines, [both, both, both, both])

    def test_independent_caller_releases_fd_and_never_pulses_single_line(self):
        with open_direct(self.node, b"123456", lambda:None) as wire:
            self.assertTrue(wire.serial.is_open)
        self.assertFalse(wire.serial.is_open)
        self.assertEqual(self.lines, [(termios.TIOCMBIC, termios.TIOCM_DTR | termios.TIOCM_RTS)] * 2)


if __name__=="__main__":
    unittest.main()
