"""Regression checks for field freshness, source matching, and the owner installer."""
import copy
import os
from pathlib import Path
import tempfile
import unittest
from field_metrics import controller
from install import install


def fixture():
    peer=dict(system_id=1,component_id=1)
    return dict(connected=True,expected_source=peer,h743_source=peer.copy(),updated_unix=99.9,heartbeat_updated_unix=99.5,
        sensors={"ATTITUDE:0":dict(source_system_id=1,source_component_id=1,fresh=True,stale_after_ms=2000,
            field_updated_unix={"roll_deg":99.8},field_fresh={"roll_deg":True},values={"roll_deg":0.0},units={"roll_deg":"deg"})})


class TestHealth(unittest.TestCase):
    def test_real_zero_and_expiration(self):
        d=fixture();r={};controller(r,d,100)
        self.assertEqual(r["fc.ATTITUDE:0.roll_deg"].value,"0 deg")
        controller(r,d,104);self.assertEqual(r["fc.ATTITUDE:0.roll_deg"].value,"—")

    def test_mismatch_future_and_failed_field(self):
        for key,val in (("source_system_id",7),("field_updated_unix",{"roll_deg":101}),("field_fresh",{}),("field_updated_unix",[])):
            d=fixture();d["sensors"]["ATTITUDE:0"][key]=val
            r={};controller(r,d,100);self.assertEqual(r["fc.ATTITUDE:0.roll_deg"].value,"—")
        d=fixture();d["expected_source"]={};r={};controller(r,d,100)
        self.assertEqual(r["fc.link"].value,"Unavailable")
    def test_install_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            h=Path(td);p=h/".local/bin/orangepi-field-health";p.parent.mkdir(parents=True)
            p.write_bytes(b"prior");p.chmod(0o750)
            install(h);install(h)
            self.assertIn(b"pi_health.py",p.read_bytes())
            self.assertTrue((h/".config/autostart/orangepi-field-health.desktop").is_file())
            install(h,True);self.assertEqual(p.read_bytes(),b"prior");self.assertEqual(p.stat().st_mode&0o777,0o750)

if __name__=="__main__":unittest.main()
