import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import bridge_usb as usb
from paired_system import attach_generation
from paired_wire import SecureSession


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.a=usb.Bridge("/dev/ttyACM0","1-1","1-1/1:3",usb.serial_digest("unit-a112233"))
        self.b=usb.Bridge("/dev/ttyACM1","2-1","2-1/2:3",usb.serial_digest("unit-b112233"))

    def test_pinned_xiao_roams_and_substitution_or_duplicate_fails_closed(self):
        a,b=self.a,self.b
        self.assertEqual(usb.choose_bridge([a,b],b.topology,a.digest,None)[0],a)
        self.assertIsNone(usb.choose_bridge([b],b.topology,a.digest,None)[0])
        moved=b._replace(digest=a.digest)
        self.assertEqual(usb.choose_bridge([moved],a.topology,a.digest,None)[0],moved)
        self.assertIsNone(usb.choose_bridge([a,moved],a.topology,a.digest,None)[0])
        self.assertIsNone(usb.choose_bridge([b],a.topology,None,None)[0])

    def test_authorized_migration_needs_sole_candidate_and_fresh_proof(self):
        a,b=self.a,self.b
        with tempfile.TemporaryDirectory() as d,patch("bridge_usb.profile",return_value=Path(d)):
            root=Path(d);marker=root/"xiao-migration.sha256";final=root/"xiao-serial.sha256"
            usb.pin_once(marker,a.digest)
            with patch("bridge_usb.enumerate_bridges",return_value=[a,b]):
                self.assertIsNone(usb.selection(b.topology)[0])
            with patch("bridge_usb.enumerate_bridges",return_value=[a]):
                with self.assertRaises(PermissionError):
                    usb.confirm_bridge(b.topology,a.node,a.cookie,Mock(ready=False))
                with self.assertRaises(PermissionError):
                    usb.confirm_bridge(b.topology,a.node,"earlier enumeration",Mock(ready=True))
                self.assertFalse(final.exists())
                usb.confirm_bridge(b.topology,a.node,a.cookie,Mock(ready=True))
                self.assertEqual(usb.read_pin(final),a.digest)
                self.assertFalse(marker.exists())
                self.assertEqual(final.stat().st_mode & 0o777,0o600)
                with self.assertRaises(PermissionError):usb.pin_once(final,b.digest)

    def test_real_sysfs_filters_product_and_authorization_without_opening_tty(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);dev=root/"dev";dev.mkdir()
            tty=root/"tty"/"ttyACM0";tty.mkdir(parents=True);(dev/tty.name).touch()
            usbdev=root/"3-2.1";interface=usbdev/"interface";interface.mkdir(parents=True)
            (tty/"device").symlink_to(interface,target_is_directory=True)
            fields=dict(idVendor="2886",idProduct="0058",product="XIAO RP2350",authorized="1",
                        serial="unit-board-777",busnum="3",devnum="2")
            for name,value in fields.items():(usbdev/name).write_text(value+"\n")
            def scan():return usb.enumerate_bridges(dev,tty.parent)
            self.assertEqual(len(scan()),1)
            self.assertNotIn(fields["serial"],str(scan()))
            for name,wrong in (("idProduct","1002"),("product","Other device"),("authorized","0"),
                               ("serial","00000000")):
                (usbdev/name).write_text(wrong)
                self.assertEqual(scan(),[])
                (usbdev/name).write_text(fields[name])

    def test_local_back_survives_transport_switch_and_service_restart(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            first=attach_generation(root,"XIAO:fixture/1:3")
            attach_generation(root,"direct USB:other-attachment")
            self.assertEqual(first,attach_generation(root,"XIAO:fixture/1:3"))
            self.assertNotEqual(first,attach_generation(root,"XIAO:fixture/1:4"))

    def test_reason_codes_require_auth_and_capability(self):
        s=SecureSession(Mock(),Mock(ready=True));s.send=Mock()
        s.blank(2)
        self.assertEqual(s.send.call_args.args,(b"\x03",.45))
        s.capabilities=32;s.send.reset_mock();s.blank(2)
        self.assertEqual(s.send.call_args.args,(b"\x0e\x02",.45))
        s.closed=True;s.send.reset_mock();s.blank(2);s.send.assert_not_called()
        s.closed=False;s.channel.ready=False;s.blank(1);s.send.assert_not_called()
