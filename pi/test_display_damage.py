import queue
import threading
import time
import unittest
from unittest.mock import patch

from desktop_source import CaptureQueue, FrameWorker
from display_damage import observe


class DamageWakeTests(unittest.TestCase):
    def test_drawing_does_not_fill_the_input_queue(self):
        commands = CaptureQueue()
        for _ in range(100):
            commands.activity.set()
        self.assertEqual(commands.qsize(), 0)
        with self.assertRaises(queue.Empty):
            commands.next_command(0)
        for value in range(8):
            commands.put_nowait(value)
        self.assertEqual([commands.next_command(0) for _ in range(8)], list(range(8)))

    def test_guard_failure_closes_source_and_watcher(self):
        closed = threading.Event()
        watch_closed = threading.Event()
        opened = []
        class Source:
            def open(self): opened.append("guard")
            def frame(self): raise PermissionError("locked")
            def close(self): closed.set()
        class Watch:
            def __init__(self, event): opened.append("watch")
            def close(self): watch_closed.set()
        with patch("display_damage.DamageWake", Watch):
            w = FrameWorker(Source(), direct_display=True)
            w.thread.start()
            w.thread.join(2)
        self.assertTrue(closed.is_set() and watch_closed.is_set() and w.error)
        self.assertEqual(opened, ["guard", "watch"])

    def test_remote_display_is_refused_before_connect(self):
        self.assertEqual(observe("example.invalid:0"), 1)
