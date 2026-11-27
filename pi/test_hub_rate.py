import unittest
from unittest.mock import Mock, patch

from direct_usb import DirectWire, DirectTimeout, _rate_cooldown


MAC=bytes.fromhex("020000000001")
PACKETS=[b"\x63"+b"x"*60 for _ in range(8)]


class HubRateTests(unittest.TestCase):
    def setUp(self):
        _rate_cooldown.clear()

    def make_wire(self,socket="2-1.3",maximum=None):
        port=Mock(port="/dev/ttyUSB0")
        with patch("direct_usb.port_location",return_value=("/dev/ttyUSB0",socket,"2")):
            wire=DirectWire(port,MAC,lambda:None,max_baud=maximum)
        wire.active=True
        wire.burst_limit=8
        return wire

    def test_topology_and_owner_bench_override(self):
        for socket,override,expected in (("2-1",None,2000000),("2-1.3",None,921600),
                                          ("2-1.3.4",None,921600),("2-1.3",2000000,2000000),
                                          ("2-1",115200,115200)):
            wire=self.make_wire(socket,override)
            session=Mock()
            wire.after_authentication(session)
            self.assertEqual(wire.baud,expected)
            if expected==115200:self.assertFalse(session.send.called)
            else:self.assertEqual(session.send.call_count,2)

    def test_unidentified_virtual_transport_keeps_previous_behavior(self):
        with patch("direct_usb.port_location",side_effect=ValueError("not a native device")):
            wire=DirectWire(Mock(port="fixture"),MAC,lambda:None)
        self.assertEqual(wire.max_baud,2000000)

    def test_genuine_guard_preserves_speed_but_always_aborts(self):
        for receipt,active in (({"error":"rejected_burst"},"priority_alert"),
                               ({"busy":False,"accepted":2,"ack":99,"up_hex":""},"guard"),
                               ({"busy":False,"accepted":2,"ack":99,"up_hex":""},"back")):
            wire=self.make_wire();wire.baud=921600;first=wire.seq
            wire.request=Mock(side_effect=[receipt,{"screen_mac":MAC.hex(),"paired":True,active:True}])
            with self.assertRaises(RuntimeError):wire.send_burst(PACKETS,1)
            self.assertEqual([c.args[0] for c in wire.request.call_args_list],["wired_usb_burst1","wired_status"])
            self.assertNotIn((wire.route,921600),_rate_cooldown)
            self.assertEqual(wire.seq,first)

    def test_unexplained_failure_steps_down_without_replaying(self):
        for status in ({"screen_mac":MAC.hex(),"paired":True,"guard":False},
                       {"screen_mac":"000000000000","paired":True,"guard":True},DirectTimeout("no status")):
            _rate_cooldown.clear()
            wire=self.make_wire();wire.baud=921600
            wire.request=Mock(side_effect=[{"busy":False,"accepted":2,"ack":0,"up_hex":""},status])
            with self.assertRaises(RuntimeError):wire.send_burst(PACKETS,1)
            self.assertIn((wire.route,921600),_rate_cooldown)
            self.assertEqual([c.args[0] for c in wire.request.call_args_list],["wired_usb_burst1","wired_status"])

    def test_preferred_helper_does_not_probe_or_demote(self):
        wire=self.make_wire();wire.baud=921600;wire.request=Mock(return_value={"busy":True})
        with self.assertRaises(RuntimeError):wire.send_burst(PACKETS,1)
        self.assertEqual(wire.request.call_count,1)
        self.assertFalse(_rate_cooldown)
