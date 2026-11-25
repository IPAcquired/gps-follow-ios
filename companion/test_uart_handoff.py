"""Offline tests for the native UART handoff. No system units or serial devices are opened."""
import contextlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import uart_handoff as h


def request(action="audit", flags=()):
    return [h.WORKER_PYTHON, str(h.TOOLS / "companion_maintenance.py"),
            action, "--worker", "--route", "pi-uart0", *flags]


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)

    def mock(self, name, **options):
        return self.stack.enter_context(patch.object(h, name, **options))

    def test_only_fixed_arguments_and_worker(self):
        for idx, bad in ((0, "/usr/bin/bash"), (1, "/tmp/a.py"), (2, "flash-anything"),
                         (3, "--worker=false"), (5, "usb")):
            with self.subTest(idx=idx):
                args = request()
                args[idx] = bad
                with self.assertRaises(h.MaintenanceError):
                    h._validate(args)
        for flags in (("--journal", "relative"), ("--foo", "/foo"),
                      ("--proposal", "/one", "--proposal", "/two"), ("--approve", "a"*64)):
            with self.assertRaises(h.MaintenanceError):
                h._validate(request(flags=flags))

    def test_firmware_allowed_fields_and_caps(self):
        for action in sorted(h.FIRMWARE_ACTIONS):
            flags = ["--bundle-dir", "/suite", "--transaction-dir", "/private"]
            if action in ("firmware-cleanup", "firmware-apply"):
                with self.assertRaises(h.MaintenanceError):
                    h._validate(request(action, flags))
                flags.extend(["--approve", "a"*64])
            h._validate(request(action, flags))
            with self.assertRaises(h.MaintenanceError):
                h._validate(request(action, (*flags, "--journal", "/extra")))
        with self.assertRaises(h.MaintenanceError):
            h._validate(request("apply", ("--approve", "xyz")))

    def test_restore_needs_new_publication_and_heartbeat(self):
        sample = {"fresh":True,"armed":False,"publication_age_seconds":0.1,"heartbeat_age_seconds":0.9}
        self.mock("monitor", return_value=sample)
        with patch.object(h.time, "time", return_value=21):
            self.assertTrue(h._healthy())
            self.assertFalse(h._healthy(20.5))
            sample["heartbeat_age_seconds"] = 0.1
            self.assertTrue(h._healthy(20.5))
            sample["armed"] = None
            self.assertFalse(h._healthy())

    def test_spawn_and_restore(self):
        self.mock("_lease", side_effect=contextlib.nullcontext)
        self.mock("_unit", return_value={"LoadState":"not-found","ActiveState":"inactive"})
        self.mock("_owner", return_value="active")
        self.mock("_healthy", return_value=True)
        restore = self.mock("_restore")
        runner = self.stack.enter_context(patch.object(h.subprocess, "run",
                                                      return_value=SimpleNamespace(returncode=23)))
        for action, limit, flags in (("audit", 150, []),
                                     ("firmware-prepare", 2400,
                                      ["--bundle-dir", "/suite", "--transaction-dir", "/private"])):
            self.assertEqual(h.handoff(request(action, flags)), 23)
            command = runner.call_args.args[0]
            self.assertIn("--property=Conflicts=" + h.MONITOR, command)
            self.assertIn("--property=After=" + h.MONITOR, command)
            self.assertIn("--property=User=drone", command)
            self.assertIn("--property=RuntimeMaxSec=" + str(limit), command)
            self.assertIn("--service-type=notify", command)
            self.assertTrue(any(x.startswith("--property=ExecStartPost=+/usr/bin/python3 -I") and x.endswith(" claimed") for x in command))
            self.assertTrue(any(x.startswith("--property=ExecStopPost=+") and "--no-block start " + h.MONITOR in x for x in command))
        runner.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            h.handoff(request())
        runner.side_effect = OSError("systemd-run unavailable")
        with self.assertRaises(OSError):
            h.handoff(request())
        self.assertEqual(restore.call_count, 4)

    def test_never_take_an_existing_or_unhealthy_service(self):
        self.mock("_lease", side_effect=contextlib.nullcontext)
        unit = self.mock("_unit", return_value={"LoadState":"loaded","ActiveState":"active"})
        runner = self.stack.enter_context(patch.object(h.subprocess, "run"))
        with self.assertRaises(h.MaintenanceError):
            h.handoff(request())
        unit.return_value = {"LoadState":"not-found","ActiveState":"inactive"}
        self.mock("_owner", return_value="active")
        self.mock("_healthy", return_value=False)
        with self.assertRaises(h.MaintenanceError):
            h.handoff(request())
        runner.assert_not_called()

    def test_independent_service_recovery_and_new_heartbeat(self):
        self.mock("_unit", return_value={"LoadState":"loaded","ActiveState":"active","Description":"mine"})
        call = self.mock("_call")
        self.mock("_owner", side_effect=["inactive", "active", "active"])
        healthy = self.mock("_healthy", side_effect=[False,True])
        self.stack.enter_context(patch.object(h.time, "sleep"))
        h._restore("mine")
        self.assertEqual([v.args for v in call.call_args_list],
                         [("stop",h.WORKER),("start",h.MONITOR)])
        self.assertEqual(healthy.call_count, 2)
        unit = self.mock("_unit",return_value={"LoadState":"loaded","ActiveState":"active","Description":"someone else"})
        with self.assertRaises(h.MaintenanceError):
            h._restore("mine")
        self.assertEqual(call.call_count, 2)

    @unittest.skipUnless(os.name == "posix" and Path("/dev/null").exists(), "POSIX device metadata")
    def test_supervisor_global_holder_check(self):
        # Substitute a synthetic process tree and an inert character device.
        # The check only stats descriptors and never opens that device.
        from unittest.mock import patch as mock_patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            alias = root / "alias"
            alias.symlink_to("/dev/null")
            proc = root / "proc"
            proc.mkdir()
            program = h.ROOT_CHECK.replace("'/dev/h743'", repr(str(alias))).replace("'/dev/ttyS0'", "'/dev/null'").replace("'/proc'", repr(str(proc)))
            with mock_patch("sys.argv", ["probe", "idle"]):
                exec(program, {})
                ours = proc / "27/fd"
                ours.mkdir(parents=True)
                (ours/"6").symlink_to("/dev/null")
                with self.assertRaisesRegex(SystemExit, "Another process"):
                    exec(program, {})
            with mock_patch("sys.argv", ["probe", "claimed"]), mock_patch.object(subprocess, "check_output", return_value="27"):
                exec(program, {})
                other = proc / "99/fd"
                other.mkdir(parents=True)
                (other/"4").symlink_to("/dev/null")
                with self.assertRaisesRegex(SystemExit, "Another process"):
                    exec(program, {})
                (other/"4").unlink()
                (ours/"6").unlink()
                with self.assertRaisesRegex(SystemExit, "did not claim"):
                    exec(program, {})

    @unittest.skipUnless(os.name == "posix", "POSIX worker cgroup")
    def test_manual_worker_invocation_rejected(self):
        import pwd
        with patch.object(pwd, "getpwnam", return_value=SimpleNamespace(pw_uid=os.geteuid())), patch.object(Path, "read_text", return_value="0::/user.slice/not-authorized"):
            with self.assertRaisesRegex(h.MaintenanceError, "supervised"):
                h.verify_worker_port()

    @unittest.skipUnless(os.name == "posix", "POSIX exclusive-claim protocol")
    def test_worker_waits_for_manager_before_using_claim(self):
        import fcntl
        def set_exclusive(fd, code, value, mutate):
            value[0] = 1
        worker = self.mock("_unit", side_effect=[
            {"LoadState":"loaded","ActiveState":"activating","MainPID":str(os.getpid())},
            {"LoadState":"loaded","ActiveState":"active","MainPID":str(os.getpid())},
        ])
        channel = self.stack.enter_context(patch.object(h.socket, "socket"))
        self.stack.enter_context(patch.dict(os.environ, {"NOTIFY_SOCKET":"/run/systemd/notify"}))
        self.stack.enter_context(patch.object(h.time, "sleep"))
        with patch.object(fcntl, "ioctl", side_effect=set_exclusive):
            h._confirm_claim(456)
        channel.return_value.__enter__.return_value.sendto.assert_called_once_with(
            b"READY=1", "/run/systemd/notify")
        self.assertEqual(worker.call_count, 2)
        with patch.object(fcntl, "ioctl"):
            with self.assertRaisesRegex(h.MaintenanceError, "exclusive"):
                h._confirm_claim(456)


if __name__ == "__main__":
    unittest.main()
