import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys

import companion_maintenance as cm


class MockController:
    def __init__(self):
        self.settings = {f"SERIAL{i}_PROTOCOL": (v, 2) for i, v in enumerate(cm.PROTOCOLS)}
        self.settings.update(SERIAL4_OPTIONS=(0, 6), SERIAL_PASS1=(0, 2), SERIAL_PASS2=(-1, 2))
        self.settings.update({k: (0, 4) for k in cm.TARGETS})
        self.settings["SERIAL4_BAUD"] = (230, 6)
        self.uid = "simulated-board"
        self.armed = False
        self.landed = True
        self.writes = []
        self.fail_once = None
        self.arm_on_fail = False

    def identity(self):
        if not self.uid:
            raise cm.MaintenanceError("Missing device identity")
        return self.uid

    def ground_guard(self, identity):
        if identity != self.uid or self.armed is not False or self.landed is not True:
            raise cm.MaintenanceError("Disarmed and on ground are required")

    def read(self, name):
        return self.settings[name]

    def write(self, name, value, ptype):
        self.writes.append((name, value))
        self.settings[name] = (value, ptype)
        if name == self.fail_once:
            self.fail_once = None
            self.armed = self.arm_on_fail
            raise cm.MaintenanceError("Simulated lost acknowledgement after delivery")


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "rollback.json"
        self.board = MockController()
        self.original = dict(self.board.settings)
        self.counter = 0

    def run_action(self, board, action, journal=None):
        self.counter += 1
        proposal = self.path.parent / f"proposal-{self.counter}.json"
        operation = "undo" if action == "undo" else "apply"
        plan = cm.prepare(board, "usb", operation, proposal, journal)
        if action == "plan":
            return plan
        return cm.execute_approved(board, "usb", operation, proposal, plan["approval_sha256"], journal)

    def test_wrong_approval_and_postplan_edit_fail_before_writes(self):
        path = self.path.parent / "plan"
        plan = cm.prepare(self.board, "usb", "apply", path)
        with self.assertRaisesRegex(cm.MaintenanceError, "digest"):
            cm.execute_approved(self.board, "usb", "apply", path, "0"*64, self.path)
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(cm.MaintenanceError, "digest"):
            cm.execute_approved(self.board, "usb", "apply", path, plan["approval_sha256"], self.path)
        self.assertFalse(self.board.writes)

    def test_expired_approval_and_changed_before_state_fail(self):
        path = self.path.parent / "plan"
        with patch.object(cm.time, "time", return_value=1000):
            digest = cm.prepare(self.board, "usb", "apply", path)["approval_sha256"]
        with patch.object(cm.time, "time", return_value=1000 + cm.PROPOSAL_TTL):
            with self.assertRaisesRegex(cm.MaintenanceError, "expired"):
                cm.execute_approved(self.board, "usb", "apply", path, digest, self.path)
        self.board.settings["MAV3_RAW_SENS"] = (4, 4)
        with patch.object(cm.time, "time", return_value=1010):
            with self.assertRaisesRegex(cm.MaintenanceError, "pre-state changed"):
                cm.execute_approved(self.board, "usb", "apply", path, digest, self.path)
        self.assertFalse(self.board.writes)

    def test_device_route_operation_and_reuse_enforced(self):
        path = self.path.parent / "plan"
        digest = cm.prepare(self.board, "usb", "apply", path)["approval_sha256"]
        self.board.uid = "swapped-controller"
        with self.assertRaisesRegex(cm.MaintenanceError, "pre-state changed"):
            cm.execute_approved(self.board, "usb", "apply", path, digest, self.path)
        self.board.uid = "simulated-board"
        for route, op in (("pi-uart0", "apply"), ("usb", "undo")):
            with self.assertRaisesRegex(cm.MaintenanceError, "different route or operation"):
                cm.execute_approved(self.board, route, op, path, digest, self.path)
        self.assertFalse(self.board.writes)
        cm.execute_approved(self.board, "usb", "apply", path, digest, self.path)
        self.run_action(self.board, "undo", self.path)
        with self.assertRaisesRegex(cm.MaintenanceError, "already used"):
            cm.execute_approved(self.board, "usb", "apply", path, digest, self.path.parent / "different-journal")

    def test_native_path_maintains_baud_and_six_rates(self):
        path = self.path.parent / "plan"
        with self.assertRaisesRegex(cm.MaintenanceError, "separate USB"):
            cm.prepare(self.board, "pi-uart0", "apply", path)
        self.board.settings["SERIAL4_BAUD"] = (115, 6)
        digest = cm.prepare(self.board, "pi-uart0", "apply", path)["approval_sha256"]
        result = cm.execute_approved(self.board, "pi-uart0", "apply", path, digest, self.path)
        self.assertEqual(len(result["changed"]), 6)

    def test_read_only_plan(self):
        plan = self.run_action(self.board, "plan")
        self.assertEqual(set(plan["changes"]), set(cm.TARGETS))
        self.assertEqual(self.board.writes, [])

    def test_full_apply_noop_and_undo(self):
        result = self.run_action(self.board, "apply", self.path)
        self.assertEqual(set(result["changed"]), set(cm.TARGETS))
        writes = self.board.writes[:]
        self.assertEqual(self.run_action(self.board, "apply", self.path)["changed"], [])
        self.assertEqual(self.board.writes, writes)
        self.run_action(self.board, "undo", self.path)
        self.assertEqual(self.board.settings, self.original)
        self.assertEqual(self.run_action(self.board, "undo", self.path)["verified_rollback"], True)

    def test_armed_missing_landed_and_missing_identity(self):
        for key, value in (("armed", True), ("armed", None), ("landed", False), ("landed", None), ("uid", None)):
            with self.subTest(key=key, value=value):
                b = MockController()
                setattr(b, key, value)
                with self.assertRaises(cm.MaintenanceError):
                    self.run_action(b, "apply", self.path)
                self.assertFalse(b.writes)

    def test_mismatched_map_options_and_passthrough(self):
        for key, pair in (("SERIAL2_PROTOCOL", (43, 2)), ("SERIAL4_OPTIONS", (4, 6)), ("SERIAL_PASS2", (4, 2))):
            with self.subTest(key=key):
                b = MockController()
                b.settings[key] = pair
                with self.assertRaises(cm.MaintenanceError):
                    self.run_action(b, "apply", self.path)
                self.assertFalse(b.writes)

    def test_lost_write_ack_restores_even_last_unacknowledged_write(self):
        self.board.fail_once = "MAV3_EXTRA1"
        with self.assertRaisesRegex(cm.MaintenanceError, "rolled back and verified"):
            self.run_action(self.board, "apply", self.path)
        self.assertEqual(self.board.settings, self.original)
        self.assertEqual(json.loads(self.path.read_text())["touched"], [])

    def test_armed_mid_update_does_not_write_rollback_and_can_recover_later(self):
        self.board.fail_once = "MAV3_EXTRA1"
        self.board.arm_on_fail = True
        with self.assertRaisesRegex(cm.MaintenanceError, "Recovery incomplete"):
            self.run_action(self.board, "apply", self.path)
        self.assertEqual(len(self.board.writes), 3)
        self.assertEqual(len(json.loads(self.path.read_text())["touched"]), 3)
        self.board.armed = False
        self.run_action(self.board, "undo", self.path)
        self.assertEqual(self.board.settings, self.original)

    def test_duplicate_journal_prevents_write(self):
        self.path.write_text("reserved")
        with self.assertRaisesRegex(cm.MaintenanceError, "already exists"):
            self.run_action(self.board, "apply", self.path)
        self.assertFalse(self.board.writes)

    def test_undo_rejects_other_device_and_external_change(self):
        self.run_action(self.board, "apply", self.path)
        self.board.writes.clear()
        self.board.uid = "another-simulated-board"
        with self.assertRaisesRegex(cm.MaintenanceError, "different device"):
            self.run_action(self.board, "undo", self.path)
        self.board.uid = "simulated-board"
        self.board.settings["SERIAL4_BAUD"] = (57, 6)
        with self.assertRaisesRegex(cm.MaintenanceError, "independently"):
            self.run_action(self.board, "undo", self.path)
        self.assertFalse(self.board.writes)

    def test_malformed_and_unrelated_parameter_journal(self):
        self.run_action(self.board, "apply", self.path)
        item = json.loads(self.path.read_text())
        item["touched"].insert(0, "UNRELATED")
        self.path.write_text(json.dumps(item))
        self.board.writes.clear()
        with self.assertRaises(cm.MaintenanceError):
            self.run_action(self.board, "undo", self.path)
        self.assertFalse(self.board.writes)

    def test_passive_monitor_fresh_stale_untrusted_and_no_location_echo(self):
        source = {"system_id": 1, "component_id": 1}
        data = dict(schema=1, connected=True, armed=False, transport="/dev/h743", h743_source=source, expected_source=source,
                    authority="read_only_no_mavlink_transmit", updated_unix=99.9, heartbeat_updated_unix=99.5)
        self.path.write_text(json.dumps(data))
        self.assertEqual(cm.monitor(self.path, 100)["armed"], False)
        self.assertIsNone(cm.monitor(self.path, 103)["armed"])
        self.assertIsNone(cm.monitor(self.path, 97)["armed"])
        data["expected_source"] = {"system_id": 2, "component_id": 1}
        self.path.write_text(json.dumps(data))
        self.assertIsNone(cm.monitor(self.path, 100)["armed"])


class MAVLinkAdapterTests(unittest.TestCase):
    def make_link(self, messages):
        link = object.__new__(cm.SerialLink)
        link.target = None
        link.guard_active = False
        link.bus = Mock()
        link.bus.recv_match.side_effect = lambda blocking, **kw: next(messages) if blocking else None
        return link

    def heartbeat(self, *, armed=False, component=1):
        return SimpleNamespace(autopilot=3, base_mode=128 if armed else 0, type=2,
                               get_srcSystem=lambda: 1, get_srcComponent=lambda: component,
                               get_type=lambda: "HEARTBEAT")

    def version(self, *, board=1229, version=0x040703ff, uid=123):
        return SimpleNamespace(board_version=board << 16, flight_sw_version=version, uid=uid,
                               get_srcSystem=lambda: 1, get_srcComponent=lambda: 1,
                               get_type=lambda: "AUTOPILOT_VERSION")

    def test_identity_rejects_other_version_board_and_missing_uid(self):
        for version in (self.version(board=1179), self.version(version=0x040702ff), self.version(uid=0)):
            link = self.make_link(iter([self.heartbeat(component=42), self.heartbeat(), version]))
            with self.assertRaises(cm.MaintenanceError):
                link.identity()

    def test_guard_rejects_armed_heartbeat(self):
        link = self.make_link(iter([self.heartbeat(armed=True)]))
        with self.assertRaisesRegex(cm.MaintenanceError, "armed"):
            link.ground_guard("unused")
        link.bus.mav.param_set_send.assert_not_called()

    def test_guard_rejects_unknown_landed_state(self):
        state = SimpleNamespace(landed_state=0, get_srcSystem=lambda: 1, get_srcComponent=lambda: 1,
                                get_type=lambda: "EXTENDED_SYS_STATE")
        link = self.make_link(iter([self.heartbeat(), self.version(), self.heartbeat(), self.version(), state]))
        device = link.identity()
        with self.assertRaisesRegex(cm.MaintenanceError, "on-ground"):
            link.ground_guard(device)


class FirmwareDispatchTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.args = SimpleNamespace(action="firmware-prepare", route="pi-uart0", worker=True,
                                    bundle_dir=root, transaction_dir=root / "private-transaction")

    def test_fixed_firmware_dispatcher_requires_approval_for_mutating_actions(self):
        for action in ("firmware-apply", "firmware-cleanup"):
            self.args.action = action
            with self.assertRaisesRegex(cm.MaintenanceError, "reviewed SHA-256"):
                cm.firmware_command(self.args)
        self.args.action = "custom-action"
        with self.assertRaisesRegex(cm.MaintenanceError, "Unknown firmware"):
            cm.firmware_command(self.args)

    def test_prepare_uses_installed_adapter_and_closes_exclusive_link_on_failure(self):
        adapter = Mock(side_effect=cm.MaintenanceError("failed verification"))
        with patch.dict(sys.modules, {"corvon_firmware": SimpleNamespace(run_firmware=adapter, FirmwareError=ValueError)}), \
                patch.object(cm, "SerialLink") as link:
            with self.assertRaisesRegex(cm.MaintenanceError, "failed verification"):
                cm.firmware_command(self.args)
            adapter.assert_called_once_with(link.return_value, "prepare", self.args.bundle_dir,
                                            self.args.transaction_dir, approval=None)
            link.return_value.close.assert_called_once()

    def test_native_handoff_dispatches_only_fixed_firmware_worker_arguments(self):
        self.args.worker = False
        self.args.approve = "a"*64
        self.args.action = "firmware-cleanup"
        handoff = Mock(return_value=0)
        with patch.dict(sys.modules, {"uart_handoff": SimpleNamespace(handoff=handoff)}):
            self.assertEqual(cm.firmware_command(self.args), 0)
        argv = handoff.call_args.args[0]
        self.assertEqual(argv[2:6], ["firmware-cleanup", "--worker", "--route", "pi-uart0"])
        self.assertEqual(argv[6:], ["--bundle-dir", str(self.args.bundle_dir), "--transaction-dir",
                                    str(self.args.transaction_dir), "--approve", "a"*64])


if __name__ == "__main__":
    unittest.main()
