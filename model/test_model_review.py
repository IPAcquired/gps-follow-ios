import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import orangepi_model_review as review


def save(path,value):
    path.write_bytes(review.encoded(value));path.chmod(0o600)


class ReviewChecks(unittest.TestCase):
    def setUp(self):
        t=TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.file=self.root/"monitor";self.perf=self.root/"perf"
        self.queue=self.root/"plans";self.queue.mkdir(mode=0o700)
        maintenance=Path(os.environ.get("FIELD_CONTROLLER_KIT","/usr/local/lib/corvon-maintenance"))
        policy_bin=Path(os.environ.get("FIELD_AI_BIN",str(Path.home()/"bin")))
        self.patch=patch.multiple(review,MONITOR=self.file,PERFORMANCE=self.perf,CONTROLLER_QUEUE=self.queue,
                                  MAINTENANCE=maintenance/"companion_maintenance.py",
                                  REVIEWS=self.root/"reviews",REVIEW_POLICY=self.root/"cfg.json",
                                  OWNER_DECISIONS=self.root/"decisions",
                                  POLICY_ROOT=self.root/"policy",POLICY_TOOL=policy_bin/"orangepi-ai-improvement")
        self.patch.start();self.addCleanup(self.patch.stop)
        sid={"system_id":1,"component_id":1}
        self.status=dict(schema=1,updated_unix=time.time(),heartbeat_updated_unix=time.time(),armed=False,
            mode="STABILIZE",system_status="standby",connected=True,expected_source=sid,h743_source=sid,
            transport="/dev/h743",authority="read_only_no_mavlink_transmit",gps={"fix_type":3,"satellites":9,
            "latitude":8.456,"longitude":-68.234},messages=["private content"])
        save(self.file,self.status)
        save(self.perf,dict(schema=1,state="normal",temperature_c=50,cpu_busy_percent=19))

    def plan(self):
        if not review.MAINTENANCE.is_file():self.skipTest("Controller maintenance kit unavailable")
        api=review.installed(review.MAINTENANCE); targets=api["TARGETS"]
        p=self.queue/"local.json";start=int(time.time());before={k:[v,6] for k,v in targets.items()}
        before["MAV3_EXTRA1"]=[5,6]
        rec={"schema":1,"operation":"apply","route":"pi-uart0","board_id":1229,"firmware":"4.7.3",
             "stream_group":"MAV3","protocols":api["PROTOCOLS"],"created":start,"expires":start+900,
             "file_binding":hashlib.sha256(os.fsencode(p.resolve())).hexdigest(),"before":before,"targets":targets,
             "device":{"opaque_hardware_id":"private_board_identifier"}}
        save(p,rec)
        return p,hashlib.sha256(p.read_bytes()).hexdigest(),rec

    def test_live_context_filters_and_stale(self):
        self.assertTrue(review.check_bench(start=True)["fresh"])
        populated=review.encoded(review.telemetry()).decode()
        for word in ("latitude","longitude","messages","private content","transport","h743_source"):
            self.assertNotIn(word,populated)
        for replacement in ({"connected":False},{"armed":True},{"system_status":"active"},
                            {"heartbeat_updated_unix":time.time()-4},{"updated_unix":time.time()+30},
                            {"authority":"other"},{"h743_source":{"system_id":2,"component_id":1}}):
            with self.subTest(replacement=replacement):
                save(self.file,{**self.status,**replacement})
                with self.assertRaises(review.Held):review.check_bench()

    def test_cpu_and_thermal_deferral(self):
        for state,tmp,cpu in (("warm",72,21),("hot",78,35),("power_fault",45,12),("normal",51,70)):
            save(self.perf,dict(schema=1,state=state,temperature_c=tmp,cpu_busy_percent=cpu))
            with self.assertRaises(review.Held):review.check_bench(start=True)

    def test_memory_headroom_and_pressure(self):
        proc=self.root/"proc";proc.mkdir();(proc/"pressure").mkdir()
        (proc/"vmstat").write_text("pswpin 123\npswpout 0\n")
        with patch.object(review,"PROC",proc),patch.object(review,"_swap_sample",None):
            (proc/"meminfo").write_text("MemAvailable: 2000000 kB\n")
            self.assertTrue(review.memory_ready(True))
            (proc/"pressure/memory").write_text("full avg10=2.80 avg60=0.0 total=1\n")
            self.assertFalse(review.memory_ready(False))
            (proc/"pressure/memory").unlink()
            (proc/"meminfo").write_text("MemAvailable: 400000 kB\n")
            self.assertFalse(review.memory_ready(False))

    def test_exact_controller_evidence(self):
        p,digest,rec=self.plan();s=review.subject("controller",p,digest)
        self.assertEqual(s["changes"],{"MAV3_EXTRA1":{"from":5,"to":10}})
        self.assertNotIn("private_board_identifier",str(s))
        for bad in ({**rec,"targets":dict(rec["targets"],UNRELATED=123)},
                    {**rec,"targets":{**rec["targets"],"MAV3_EXTRA1":543}},
                    {**rec,"expires":rec["expires"]-1000},{**rec,"file_binding":"0"*64}):
            save(p,bad)
            with self.assertRaises(review.Held):
                review.subject("controller",p,hashlib.sha256(p.read_bytes()).hexdigest())
        save(p,rec)
        with self.assertRaises(review.Held):review.subject("controller",p,"0"*64)

    def test_policy_pending_matches_current_base(self):
        if not review.POLICY_TOOL.is_file():self.skipTest("AI-improvement tool unavailable")
        root=review.POLICY_ROOT;root.mkdir(mode=0o700);pending=root/"pending";pending.mkdir(mode=0o700)
        api=review.installed(review.POLICY_TOOL);active=api["validated"](api["DEFAULT"])
        save(root/"active.json",active);candidate={**active,"temperature":0.4}
        ev={"authority":"non_flight_ai_policy_only","passed":True}
        data={"candidate":candidate,"candidate_sha256":review.digest_obj(candidate),"evaluation_sha256":review.digest_obj(ev),
              "base_active_sha256":review.digest_obj(active)}
        d=review.digest_obj(data);p=pending/(d[:24]+".json")
        save(p,{"schema":2,"status":"awaiting_human_review","approval_sha256":d,"candidate_id":d[:24],
                "approval_payload":data,"evaluation":ev})
        self.assertEqual(review.subject("ai-policy",p,d)["changes"]["temperature"],{"from":active["temperature"],"to":0.4})
        save(root/"active.json",candidate)
        with self.assertRaises(review.Held):review.subject("ai-policy",p,d)

    def test_unanimity_and_external_pending(self):
        p,d,rec=self.plan();s=review.subject("controller",p,d)
        root=review.receipt_path("controller",d);root.mkdir(parents=True,mode=0o700)
        votes=[dict(profile=n,model=model,vote="approve",reason="evidence_consistent",weight_stamp=[10,20,30]) for n,model in review.MODELS.items()]
        r={"attempt":"a"*32,"kind":"controller","digest":d,"boot":review.boot_id(),"subject_hash":review.digest_obj(s),
           "started_unix":time.time()-1,"expires_unix":time.time()+10,"votes":votes,"status":"ready_for_owner","reason":"unanimous_advisory_review"}
        def publish(r):
            save(root/(r["attempt"]+".json"),r);save(root/"latest.json",r)
        with patch.object(review,"weight_stamp",return_value=(None,[10,20,30])):
            publish(r)
            self.assertEqual(review.eligibility("controller",p,d)["status"],"ready_for_owner")
            save(review.REVIEW_POLICY,{"schema":1,"require_jev_for":["controller"]})
            self.assertEqual(review.eligibility("controller",p,d)["status"],"pending")
            review.REVIEW_POLICY.unlink()
            for bad in (votes[:-1],votes[:3]+[votes[2]],votes[:3]+[{**votes[3],"vote":"abstain"}]):
                publish({**r,"votes":bad});self.assertEqual(review.eligibility("controller",p,d)["status"],"pending")
            publish(r);save(root/"latest.json",{**r,"reason":"tamper"})
            self.assertEqual(review.eligibility("controller",p,d)["status"],"pending")

    def test_owner_decision_is_separate_and_bound(self):
        review.OWNER_DECISIONS.mkdir(mode=0o700)
        d="a"*64;t=time.time()+20
        verdict=dict(status="ready_for_owner",kind="controller",digest=d,expires_unix=t)
        self.assertFalse(review.owner_approved("controller",d,verdict))
        p=review.OWNER_DECISIONS/("controller-"+d+".json")
        r=dict(schema=1,kind="controller",digest=d,decision="approved",source="signed-in-owner-desktop",
               application="separate-guarded-handoff",model_review_expires_unix=t,decided_unix=time.time())
        save(p,{**r,"decision":"declined"})
        self.assertFalse(review.owner_approved("controller",d,verdict))
        save(p,r);self.assertTrue(review.owner_approved("controller",d,verdict))
        self.assertFalse(review.owner_approved("controller",d,{**verdict,"expires_unix":t+1}))


if __name__=="__main__":unittest.main()
