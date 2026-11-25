"""Offline verification of pairing, freshness and the receiver handshake."""
import ast
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pc_h743_route as route
from pc_h743_packets import Packetizer

HERE = Path(__file__).resolve().parent


def load_script(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sender = load_script("sender", "pc-h743-bridge.py")
probe = load_script("status_probe", "check-pi-bridge-status.py")


class BridgeTests(unittest.TestCase):
    def test_busy_windows_status_reader_does_not_interrupt_forwarding(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sender, "STATE_DIR", Path(tmp)):
            target = Path(tmp) / "bridge-status.json"
            sender.publish("first")
            busy = PermissionError("status is being read")
            busy.winerror = 5
            with patch.object(sender.os, "replace", side_effect=busy):
                sender.publish("busy")
            self.assertEqual(json.loads(target.read_text())["state"], "first")
            sender.publish("recovered")
            self.assertEqual(json.loads(target.read_text())["state"], "recovered")

    def test_example_cannot_select_real_hardware(self):
        with self.assertRaises(ValueError):
            route.private_profile(HERE / "bridge.example.json")
        ports = [SimpleNamespace(vid=0x1209, pid=0x5741, serial_number="synthetic")]
        self.assertEqual(route.matching_ports(ports, "different"), [])
        self.assertEqual(route.matching_ports(ports, "synthetic"), ports)

    def test_exact_saved_host_key_and_private_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            keyfile = Path(tmp) / "fixture.key"
            hostsfile = Path(tmp) / "known_hosts"
            for path in (keyfile, hostsfile):
                path.touch()
            key = b"offline host identity fixture"
            fingerprint = base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")
            config = dict(ssh_user="fixture", ssh_candidates=["receiver.invalid"],
                          identity_file=str(keyfile), known_hosts_file=str(hostsfile),
                          known_host_alias="receiver.invalid", host_key_sha256="SHA256:" + fingerprint)
            record = "receiver.invalid ssh-ed25519 " + base64.b64encode(key).decode()
            with patch.object(route.subprocess, "run", return_value=SimpleNamespace(returncode=0,stdout=record)):
                peers, command = route.saved_route(config)
                self.assertEqual(peers, ["receiver.invalid"])
                self.assertIn("StrictHostKeyChecking=yes", command)
                self.assertIn("HostKeyAlias=receiver.invalid", command)
                self.assertIn("ForwardAgent=no", command)
                self.assertIn("ClearAllForwardings=yes", command)
                with self.assertRaises(ValueError):
                    route.saved_route({**config, "host_key_sha256":"mismatch"})

    def test_delivered_bootstrap_accepts_only_compatible_receiver(self):
        command = route.receiver_command()
        payload = re.search(r"b64decode\('([a-zA-Z0-9+/=]+)'\)", command).group(1)
        text = base64.b64decode(payload, validate=True).decode("ascii")
        self.assertIn(route.RECEIVER_SHA, text)
        self.assertIn(route.FRAME_SHA, text)
        self.assertIn('Path.home() / "bin" / "pc-h743-input.py"', text)
        parsed = ast.parse(text)
        # Run just the predicate with synthetic file digests; no remote OS action.
        self.assertEqual(ast.unparse(parsed.body[-1]), "bootstrap()")
        raw_receiver, raw_helper = b"receiver test source", b"frame test source"
        simulated = text.replace(route.RECEIVER_SHA, hashlib.sha256(raw_receiver).hexdigest()).replace(
            route.FRAME_SHA, hashlib.sha256(raw_helper).hexdigest())
        code = ast.parse(simulated)
        code.body = [node for node in code.body if isinstance(node, ast.FunctionDef) and node.name == "verified_route"]
        environment = {"hashlib": hashlib}
        exec(compile(code, "<fixture>", "exec"), environment)
        verify = environment["verified_route"]
        settings = dict(enabled=True, kind="serial", device=route.FIFO, baud=115200)
        def test_case(model=b"Orange Pi Zero 3W\0", receiver=raw_receiver, frame=raw_helper, **options):
            return verify(model, {"transports":[{**settings, **options}]}, receiver, frame)
        self.assertTrue(test_case())
        for alteration in (dict(model=b"other"), dict(receiver=b"other"), dict(frame=b"other"),
                           dict(enabled=False), dict(baud=123), dict(device="unused")):
            self.assertFalse(test_case(**alteration))

    def test_no_serial_ownership_until_pinned_handshake_and_second_match(self):
        port = SimpleNamespace(vid=0x1209, pid=0x5741, serial_number="synthetic", device="fixture-port")
        for connected, still_present in ((False, False), (True, False), (True, True)):
            with self.subTest(connected=connected, still_present=still_present):
                serial = Mock(SerialException=OSError)
                listed = Mock()
                listed.comports.side_effect = [[port], [port] if still_present else []]
                stop = Mock()
                stop.exists.side_effect = [False, False, True] if connected else [False, True]
                child = Mock() if connected else None
                with patch.object(sender, "STOP", stop), patch.object(sender, "publish"), patch.object(sender, "pause"), \
                     patch.object(route, "private_profile", return_value=("synthetic", {})), \
                     patch.object(route, "saved_route", return_value=(["receiver.invalid"], [])), \
                     patch.object(route, "open_receiver", return_value=child), patch.object(route, "close_receiver"), \
                     patch.object(sender, "forward") as send:
                    sender.serve(serial, listed)
                self.assertEqual(serial.Serial.called, bool(connected and still_present))
                self.assertEqual(send.called, bool(connected and still_present))
                if send.called:
                    self.assertFalse(serial.Serial.return_value.dtr)
                    self.assertFalse(serial.Serial.return_value.rts)
                    serial.Serial.return_value.close.assert_called_once()

    def test_receiver_challenges(self):
        fixture = """
import sys,time
stream=sys.stdout.buffer
stream.write(b"PC_H743_RECEIVER_CLOCK_V1\\n");stream.flush()
for _ in range(3):
    line=sys.stdin.buffer.readline().split()
    if len(line)!=2:raise SystemExit
    nonce=line[1] if sys.argv[1]=="okay" else b"wrong"
    stream.write(b"T "+nonce+b" "+str(time.time_ns()).encode()+b"\\n");stream.flush()
if sys.stdin.buffer.readline()==b"GO\\n":
    stream.write(b"PC_H743_RECEIVER_READY_V1\\n");stream.flush()
    sys.stdin.buffer.read()
"""
        for phase in ("okay", "mismatch"):
            child = route.open_receiver([sys.executable, "-u", "-c", fixture], phase, lambda: False)
            try:
                self.assertEqual(child is not None, phase == "okay")
            finally:
                route.close_receiver(child)

    def test_clock_window_and_stale_samples(self):
        samples = [(100+i, 100.04+i, 1000.02+i) for i in range(3)]
        with patch.object(route.time, "monotonic", return_value=100), patch.object(route.time,"time",return_value=1000):
            calibration = route.CaptureClock(samples)
            self.assertAlmostEqual(calibration.epoch(103), 1003)
            self.assertTrue(calibration.current(100))
            self.assertFalse(calibration.current(401))
            with patch.object(route.time, "time", return_value=1011):
                self.assertFalse(calibration.current(101))
        with self.assertRaises(ValueError):
            route.CaptureClock([(t, r+1, e) for t,r,e in samples])
        with self.assertRaises(ValueError):
            route.CaptureClock([*samples[:2],(102,102.04,1200)])

    def test_bootstrap_detects_clock_steps_from_its_first_calibration_sample(self):
        # Run the delivered handshake and watcher with only their OS inputs replaced.
        code = ast.parse(route.BOOTSTRAP)
        code.body.pop()  # Invoke bootstrap below, after binding simulated clocks and pipes.
        for steps, labels in (([0, .01], ["S", "S"]), ([691], ["changed"]),
                              ([-691], ["changed"]), ([0, 691], ["S", "changed"])):
            with self.subTest(steps=steps):
                env = {}
                exec(compile(code, "<bootstrap>", "exec"), env)
                remote_os = Mock()
                remote_os.getpid.return_value = 42
                remote_os.fork.return_value = 0
                remote_os.getppid.side_effect = [42] * len(steps) + [1]
                remote_os._exit.side_effect = SystemExit(0)
                clock = Mock()
                clock.time_ns.return_value = 1_000_000_000_000
                clock.monotonic_ns.return_value = 10_000_000_000
                clock.time.side_effect = [1001 + i + step for i, step in enumerate(steps)]
                clock.monotonic.side_effect = [11 + i for i in range(len(steps))]
                stdin = io.BytesIO((b"C " + b"a" * 24 + b"\n") * 3 + b"GO\n")
                stdout = io.BytesIO()
                env.update(os=remote_os, time=clock, verified_route=lambda *args: True,
                           sys=SimpleNamespace(stdin=SimpleNamespace(buffer=stdin),
                                               stdout=SimpleNamespace(buffer=stdout)))
                with patch.object(Path, "read_bytes", return_value=b"fixture"), \
                     patch.object(Path, "read_text", return_value="{}"), \
                     patch.object(route.subprocess, "run", return_value=SimpleNamespace(returncode=0)), \
                     self.assertRaises(SystemExit):
                    env["bootstrap"]()
                self.assertIn(route.READY, stdout.getvalue())
                lines = [args[1] for args, _ in remote_os.write.call_args_list]
                observed = ["changed" if line == route.CLOCK_CHANGED else line.split(b" ")[0].decode()
                            for line in lines]
                self.assertEqual(observed, labels)

    def test_step_invalidates_receipts_and_retries_same_pinned_route_before_backoff(self):
        device = SimpleNamespace(vid=0x1209, pid=0x5741, serial_number="fixture", device="fixture-port")
        stopped = threading.Event()
        serial = Mock(SerialException=OSError)
        listed = Mock()
        listed.comports.return_value = [device]
        first, second = Mock(), Mock()
        first.in_waiting = second.in_waiting = 17
        serial.Serial.side_effect = [first, second]
        old, new = Mock(), Mock()
        for child, offset in ((old, 0), (new, 691)):
            child.poll.return_value = None
            child.capture_clock.epoch.side_effect = lambda t, shift=offset: t + shift
            child.capture_clock.current.return_value = True
            child.capture_clock.rtt = 0
            child.pi_receipts = route.PiReceipts(child.capture_clock)
        previous = b'S [10,"fifo",9.9,4]\n'
        old.pi_receipts.accept(previous, 10)
        self.assertTrue(old.pi_receipts.status(10)["pi_fifo_verified"])
        def step_during_read(n):
            old.pi_receipts.accept(route.CLOCK_CHANGED, 10)
            old.pi_receipts.accept(previous, 10)  # An earlier receipt cannot revive this session.
            return b"stale"
        first.read.side_effect = step_during_read
        heartbeat = bytes.fromhex("fe0900010100000000000203000303d598")
        second.read.return_value = heartbeat
        new.stdin.flush.side_effect = stopped.set
        with patch.object(sender, "STOP", SimpleNamespace(exists=stopped.is_set)), \
             patch.object(sender, "publish") as publish, patch.object(sender, "pause") as pause, \
             patch.object(route, "private_profile", return_value=("fixture", {})), \
             patch.object(route, "saved_route", return_value=(["paired.invalid", "alternate.invalid"], [])), \
             patch.object(route, "open_receiver", side_effect=[old, new]) as connect, \
             patch.object(route, "close_receiver") as close:
            sender.serve(serial, listed)
        self.assertEqual([args[1] for args, _ in connect.call_args_list], ["paired.invalid"] * 2)
        self.assertEqual([args[0] for args, _ in close.call_args_list], [old, new])
        publish.assert_any_call("recalibrating_pi_clock")
        pause.assert_called_once()  # Only after the second session.
        self.assertFalse(old.pi_receipts.status(10)["pi_fifo_verified"])
        old.stdin.write.assert_not_called()
        new.stdin.write.assert_called_once()
        self.assertEqual(base64.b64decode(json.loads(new.stdin.write.call_args.args[0])["data"]), heartbeat)

    def test_status_requires_two_fresh_clock_values_and_correct_transport(self):
        src={"system_id":1,"component_id":1}
        state=dict(transport=route.FIFO, connected=True, h743_source=src, expected_source=src,
                   heartbeat_updated_unix=10, updated_unix=10, authority="read_only_no_mavlink_transmit")
        self.assertTrue(probe.sample(state,11)[0])
        for change in (dict(transport="another"), dict(heartbeat_updated_unix=7), dict(updated_unix=7),
                       dict(connected=False), dict(h743_source=None), dict(authority="another")):
            self.assertFalse(probe.sample({**state, **change},11)[0])

    def test_sender_has_no_serial_write_path(self):
        nodes = ast.walk(ast.parse((HERE / "pc-h743-bridge.py").read_text()))
        calls = [ast.unparse(node.func) for node in nodes if isinstance(node,ast.Call)]
        self.assertIn("port.read",calls)
        self.assertEqual([call for call in calls if call.endswith(".write")],["child.stdin.write"])

    def test_fragmented_packets_keep_origin_and_classify_source(self):
        # Constant disarmed wire fixtures produced with the public MAVLink dialect.
        v1 = bytes.fromhex("fe0900010100000000000203000303d598")
        v2 = bytes.fromhex("fd0900000001010000000000000002030003034f5b")
        other = bytes.fromhex("fd090000000203000000000000000203000303e57e")
        framer = Packetizer()
        self.assertEqual(list(framer.push(v1[:5], 20)), [])
        self.assertEqual(list(framer.push(v1[5:]+v2+other,20.05)),[(v1,20),(v2,20.05),(other,20.05)])
        info = framer.status(20.2)
        self.assertEqual(info["usb_heartbeats_crc_valid"],3)
        self.assertEqual(info["usb_heartbeats_expected"],2)
        self.assertEqual(info["usb_heartbeat_source"],[2,3])
        broken = v2[:-1]+bytes([v2[-1]^1])
        self.assertEqual(b"".join(data for data,_ in framer.push(broken,20.3)),broken)
        self.assertEqual(framer.status(20.3)["usb_heartbeat_crc_errors"],1)
        list(framer.push(v2[:7],21))
        self.assertEqual(list(framer.push(v1,22)),[(v1,22)])
        self.assertEqual(framer.status(22)["usb_partial_bytes_discarded"],7)

    def test_same_session_receipts_expire_and_require_fifo(self):
        from types import SimpleNamespace
        receipt = route.PiReceipts(SimpleNamespace(epoch=lambda t:t))
        def accept(now, path, beat, count):
            receipt.accept(b"S "+json.dumps([now,path,beat,count]).encode(),now)
            return receipt.status(now)
        self.assertFalse(accept(10,"native",9.9,4)["pi_fifo_verified"])
        self.assertFalse(accept(11,"fifo",10.9,1)["pi_fifo_verified"])
        self.assertTrue(accept(12,"fifo",11.9,2)["pi_fifo_verified"])
        self.assertFalse(receipt.status(14.2)["pi_fifo_verified"])
        self.assertFalse(accept(15,"other",None,0)["pi_fifo_verified"])


if __name__ == "__main__":
    unittest.main()
