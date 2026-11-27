import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from install import BASE,setup
from orangepi_postflight_evidence import SCOPE,history,model_context,show


class TestBridge(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home=Path(tmp.name)
        self.root=self.home/"flight-data"
        self.acq=self.root/"acquisition"
        for path in (self.root,self.acq,self.acq/"reports",self.acq/"snapshots",self.root/"profile"):
            path.mkdir(mode=0o700)
        self.dg=hashlib.sha256(b"fixture-data").hexdigest()
        self.group="APJ-1229/BT-10/BU-2/4.7.3"
        self.put(self.root/"profile/current.json",dict(schema=1,controller_group=self.group,files=0,messages=0))
        self.put(self.acq/"latest-snapshot.json",dict(schema=1,sha256=self.dg,bytes=12,classification="stable_snapshot",queued=False))
        self.sample=dict(schema=1,scope=SCOPE,sha256=self.dg,controller_group=self.group,messages=3,
                         duration_seconds=2.56,message_types={"GPS":1,"private injected text":2},
                         observations={"untrusted":"private injected text"})
        self.raw=self.acq/"snapshots"/(self.dg+".BIN")
        self.raw.write_bytes(b"fixture-data");self.raw.chmod(0o600)
        self.reports(self.sample)
        self.catalog([])
    def put(self,path,data):
        path.write_text(json.dumps(data));path.chmod(0o600)
    def reports(self,data):
        self.put(self.acq/"latest-analysis.json",data)
        self.put(self.acq/"reports"/(self.dg+".json"),data)
    def catalog(self,rows):
        body=b"".join(json.dumps(r).encode()+b"\n" for r in rows)
        path=self.root/"completed-log-index.jsonl"
        path.write_bytes(b'{"kind":"completed_log_catalog","schema":1}\n'+body+json.dumps(dict(
            kind="completed_log_catalog_end",records=len(rows),records_sha256=hashlib.sha256(body).hexdigest())).encode()+b"\n")
        path.chmod(0o600)
    def facts(self):
        return model_context(self.home)["latest_snapshot"]
    def test_allowlist_privacy_and_age(self):
        facts=self.facts()
        self.assertEqual(facts["messages"],3);self.assertEqual(facts["gps_records"],1)
        text=json.dumps(model_context(self.home))
        for val in (self.dg,self.group,"private injected text",str(self.home)):
            self.assertNotIn(val,text)
        self.assertFalse(facts["included_in_completed_totals"])
        past=time.time()-96*3600;os.utime(self.raw,(past,past))
        self.assertEqual(self.facts()["capture_age"],"historical")
    def test_duplicate_and_history(self):
        self.assertEqual(history(self.home),[dict(digest=self.dg,collection="snapshot",messages=3)])
        self.assertEqual(show(self.home,self.dg)["log_duration_seconds"],2.6)
        self.catalog([dict(sha256=self.dg,bytes=12,archive_path="ignored")])
        self.assertEqual(self.facts()["status"],"already_in_completed_catalog")
        self.assertEqual(len(history(self.home)),1)
        dest=self.root/"reports"/"2026"/"01"/("test-"+self.dg[:12])
        dest.mkdir(parents=True,mode=0o700);(self.root/"reports").chmod(0o700)
        self.put(dest/"report.json",dict(schema=2,source={"sha256":self.dg},analysis=self.sample))
        self.assertEqual(show(self.home,self.dg)["collection"],"completed")
        with self.assertRaises(ValueError):show(self.home,"../private")
    def test_failed_provenance(self):
        other=self.sample|{"controller_group":"APJ-10/BT-10/BU-2/4.7.3"}
        self.reports(other);self.assertEqual(self.facts()["status"],"unavailable")
        self.reports(self.sample);self.put(self.acq/"latest-analysis.json",self.sample|{"messages":4})
        self.assertEqual(self.facts()["status"],"unavailable")
        self.reports(self.sample);self.raw.chmod(0o644)
        self.assertEqual(self.facts()["status"],"unavailable")
        self.raw.chmod(0o600);target=self.raw.with_suffix(".target");self.raw.rename(target);self.raw.symlink_to(target)
        self.assertEqual(self.facts()["status"],"unavailable")
    def test_corrupt_measurement_and_catalog(self):
        self.reports(self.sample|{"message_types":{"GPS":True,"secret":2}})
        self.assertEqual(self.facts()["status"],"unavailable")
        self.reports(self.sample);(self.root/"completed-log-index.jsonl").write_text("{}\n")
        self.assertEqual(self.facts()["status"],"unavailable")
    def test_four_normal_profiles_and_reversible_install(self):
        baseline=os.environ.get("FIELD_AI_TEAM")
        if not baseline:self.skipTest("provide the supported AI team source")
        bindir=self.home/"bin";bindir.mkdir()
        team=bindir/"orangepi-ai-team";shutil.copy2(baseline,team)
        self.assertEqual(setup(self.home,"activate"),"active")
        functions=runpy.run_path(str(team))
        context=json.dumps(model_context(self.home))
        outputs=dict(fast="a",balanced="b",quality="c")
        with mock.patch.dict(sys.modules,{"orangepi_model_review":SimpleNamespace(telemetry=lambda:{"fresh":False})}):
            for profile in functions["PROFILES"]:
                prompt=functions["cooperative_prompt"]("offline test",outputs,profile.name,"policy","checked",context)
                self.assertIn(context,prompt)
                self.assertIn("never approval",prompt)
                self.assertIn("policy",prompt)
                self.assertNotIn(self.dg,prompt)
        self.assertEqual(setup(self.home,"rollback"),"stock")
        self.assertEqual(hashlib.sha256(team.read_bytes()).hexdigest(),BASE)
        team.write_bytes(b"owner change")
        with self.assertRaises(ValueError):setup(self.home,"activate")


if __name__=="__main__":unittest.main()
